#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 v7_finance_quote.py — Aplicativo Interativo de Terminal & Cliente Canônico
 Endpoint: GET https://query1.finance.yahoo.com/v7/finance/quote (v3.5.0)
═══════════════════════════════════════════════════════════════════════════════
 REQUISITOS ATENDIDOS:
   1. ANTI-FECHAMENTO: Loop interativo contínuo, blindagem contra tracebacks,
      pausa ao fechar, tratamento gracioso de Ctrl+C e EOF.
   2. ZERO DEPENDÊNCIAS EXTERNAS: Apenas Python stdlib (urllib, http.cookiejar,
      json, shutil, etc.). Python 3.8+.
   3. UI DESIGN: Cores ANSI com suporte a VT no Windows, caixas e tabelas com
      padding imune a códigos de escape ANSI, fallbacks (--ascii, --sem-cores),
      formatação localizada pt-BR (milhares, decimais, %, epoch -> local).
   4. FUNÇÕES EXPOSTAS: Consulta canônica, múltiplos hosts (query1/query2),
      console de requisições brutas (GET/POST/HEAD/OPTIONS, vetor duplo de crumb),
      comparador multi-símbolo, suíte de testes ao vivo, auditoria de invariantes,
      gestão de credenciais (A3 + Crumb) e exportação de JSON cru.
   5. REDE ROBUSTA: Auto-recuperação de 401 com renovação A3+Crumb, backoff
      exponencial com jitter em 429/503 (máx 5 retries), medição de latência e bytes.
   6. COMPATIBILIDADE: Mantém 100% das flags CLI para automação e paridade de bytes.
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import datetime
import http.cookiejar
import json
import os
import random
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union

__version__ = "3.5.0"

# Ativação de Virtual Terminal Sequences no Windows
if os.name == "nt":
    os.system("")

# Forçar codificação UTF-8 em stdout/stderr se suportado
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ════════════════════════ Constantes do Protocolo ═══════════════════════════

HOST_QUERY1 = "query1.finance.yahoo.com"
HOST_QUERY2 = "query2.finance.yahoo.com"
ENDPOINT_PATH = "/v7/finance/quote"
URL_FC = "https://fc.yahoo.com"
URL_CRUMB = "https://query1.finance.yahoo.com/v1/test/getcrumb"
DEFAULT_TIMEOUT = 15.0

USER_AGENT_DEFAULT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

# Array Canônico W (34 campos padrão do bundle security.q0vEN2Ok.js)
CANONICAL_W_FIELDS = [
    "customPriceAlertConfidence", "exchangeDataDelayedBy", "exchangeTimezoneName",
    "exchangeTimezoneShortName", "fiftyTwoWeekHigh", "fiftyTwoWeekHighChange",
    "fiftyTwoWeekHighChangePercent", "fiftyTwoWeekLow", "fiftyTwoWeekLowChange",
    "fiftyTwoWeekLowChangePercent", "fiftyTwoWeekRange", "firstTradeDateMilliseconds",
    "fullExchangeName", "gmtOffSetMilliseconds", "hasPrePostMarketData",
    "marketState", "overnightMarketChange", "overnightMarketChangePercent",
    "overnightMarketPrice", "overnightMarketTime", "priceHint",
    "regularMarketChange", "regularMarketChangePercent", "regularMarketDayHigh",
    "regularMarketDayLow", "regularMarketDayRange", "regularMarketPrice",
    "regularMarketTime", "regularMarketVolume", "regularMarketPreviousClose",
    "regularMarketOpen", "sourceInterval", "symbol", "tradeable"
]

PRESET_GROUPS = {
    "1": ("Ações US Blue Chips", ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]),
    "2": ("Brasil B3 (ADRs e Locais)", ["PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "PBR"]),
    "3": ("Macro & Índices Mundiais", ["^GSPC", "^DJI", "^IXIC", "^BVSP", "^FTSE", "^N225"]),
    "4": ("Futuros & Commodities", ["ES=F", "NQ=F", "CL=F", "GC=F", "SI=F"]),
    "5": ("Criptoativos & Câmbio", ["BTC-USD", "ETH-USD", "SOL-USD", "EURUSD=X", "BRL=X"]),
    "6": ("Lote Misto Heterogêneo", ["AAPL", "BOVA11.SA", "^GSPC", "CL=F", "EURUSD=X", "BTC-USD"])
}

# ════════════════════════ UI / ANSI & Formatação ════════════════════════════

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove códigos de escape ANSI para cálculo exato de largura visual."""
    return ANSI_ESCAPE_RE.sub("", text)


def vlen(text: str) -> int:
    """Retorna o comprimento visível real de uma string."""
    return len(strip_ansi(text))


def pad_vis(text: str, width: int, align: str = "<") -> str:
    """Aplica preenchimento (padding) preservando caracteres de cor ANSI."""
    diff = max(0, width - vlen(text))
    if align == ">":
        return " " * diff + text
    elif align == "^":
        left = diff // 2
        right = diff - left
        return " " * left + text + " " * right
    return text + " " * diff


class Palette:
    """Gerenciador centralizado de cores e estilos ANSI com chaveamento dinâmico."""
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _c(self, code: str) -> str:
        return code if self.enabled else ""

    @property
    def RESET(self) -> str: return self._c("\033[0m")
    @property
    def BOLD(self) -> str: return self._c("\033[1m")
    @property
    def DIM(self) -> str: return self._c("\033[2m")
    @property
    def RED(self) -> str: return self._c("\033[91m")
    @property
    def GREEN(self) -> str: return self._c("\033[92m")
    @property
    def YELLOW(self) -> str: return self._c("\033[93m")
    @property
    def BLUE(self) -> str: return self._c("\033[94m")
    @property
    def MAGENTA(self) -> str: return self._c("\033[95m")
    @property
    def CYAN(self) -> str: return self._c("\033[96m")
    @property
    def WHITE(self) -> str: return self._c("\033[97m")
    @property
    def GRAY(self) -> str: return self._c("\033[90m")
    @property
    def BG_BLUE(self) -> str: return self._c("\033[44m")


class BoxChars:
    """Definição de caracteres para bordas de caixas e tabelas."""
    def __init__(self, ascii_mode: bool = False):
        if ascii_mode:
            self.TL = "+"
            self.TR = "+"
            self.BL = "+"
            self.BR = "+"
            self.H = "-"
            self.V = "|"
            self.LT = "+"
            self.RT = "+"
            self.TT = "+"
            self.BT = "+"
            self.X = "+"
        else:
            self.TL = "╭"
            self.TR = "╮"
            self.BL = "╰"
            self.BR = "╯"
            self.H = "─"
            self.V = "│"
            self.LT = "├"
            self.RT = "┤"
            self.TT = "┬"
            self.BT = "┴"
            self.X = "┼"


# ════════════════════════ Funções de Formatação pt-BR ════════════════════════

def fmt_numero_br(valor: Any, decimais: int = 2) -> str:
    """Formata número no padrão brasileiro: 1.234.567,89."""
    if valor is None:
        return "—"
    try:
        f = float(valor)
        partes = f"{f:,.{decimais}f}".split(".")
        inteiro = partes[0].replace(",", ".")
        decimal = partes[1] if len(partes) > 1 else ""
        return f"{inteiro},{decimal}" if decimal else inteiro
    except (ValueError, TypeError):
        return str(valor)


def fmt_grandeza_br(valor: Any) -> str:
    """Formata grandezas monetárias e volumes com sufixos compactos (K, M, B, T)."""
    if valor is None:
        return "—"
    try:
        n = float(valor)
        sinal = "-" if n < 0 else ""
        n = abs(n)
        for suf, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
            if n >= div:
                val = n / div
                return f"{sinal}{fmt_numero_br(val, 2)} {suf}"
        return f"{sinal}{fmt_numero_br(n, 2)}"
    except (ValueError, TypeError):
        return str(valor)


def fmt_percentual_br(valor: Any, com_sinal: bool = True) -> str:
    """
    Formata percentual no padrão pt-BR.
    Nota crítica: regularMarketChangePercent já vem em unidade percentual no Yahoo Finance.
    """
    if valor is None:
        return "—"
    try:
        f = float(valor)
        sinal = "+" if f > 0 and com_sinal else ""
        return f"{sinal}{fmt_numero_br(f, 2)}%"
    except (ValueError, TypeError):
        return str(valor)


def fmt_epoch_local(epoch_val: Any) -> str:
    """Converte Unix timestamp (segundos ou ms) em data/hora local brasileira."""
    if not epoch_val:
        return "—"
    try:
        ts = float(epoch_val)
        if ts > 1e11:  # Timestamp em milissegundos
            ts /= 1000.0
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(epoch_val)


# ══════════════════════ Camada de Rede & Autenticação ═══════════════════════

class NetworkEngine:
    """
    Motor HTTP resiliente utilizando estritamente a biblioteca padrão.
    Implementa:
      - CookieJar atômico com suporte ao Cookie A3.
      - Resolução de Crumb via endpoint ou sessão.
      - Backoff exponencial com jitter (2^n) para 429/503.
      - Renovação automática de sessão em HTTP 401.
      - Medição de latência (ms) e contagem exata de bytes trafegados.
    """
    def __init__(self, user_agent: str = USER_AGENT_DEFAULT):
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.user_agent = user_agent
        self.crumb: Optional[str] = None
        self.a3_cookie: Optional[str] = None
        self.last_latency_ms: float = 0.0
        self.last_bytes_count: int = 0
        self.last_status_code: int = 0

    def obter_a3_presente(self) -> Optional[str]:
        """Varre o CookieJar em busca do cookie de identificação A3."""
        for cookie in self.cookie_jar:
            if cookie.name == "A3":
                return cookie.value
        return None

    def bootstrap_auth(self, verbose: bool = False) -> Tuple[bool, str]:
        """
        Executa o handshake oficial da Yahoo Finance:
        1. Dispara requisição ao host fc.yahoo.com (espera-se 404/redirecionamento para gravação do A3).
        2. Dispara requisição autenticada ao getcrumb com o CookieJar populado.
        """
        if verbose:
            sys.stderr.write("[AUTH] Iniciando handshake com fc.yahoo.com...\n")

        # Passo 1: Captura do Cookie A3
        req_fc = urllib.request.Request(
            URL_FC,
            headers={"User-Agent": self.user_agent, "Accept": "*/*"}
        )
        try:
            with self.opener.open(req_fc, timeout=DEFAULT_TIMEOUT):
                pass
        except urllib.error.HTTPError:
            pass  # HTTP 404 é o comportamento esperado pelo design do portal
        except Exception as e:
            return False, f"Falha de conexão em fc.yahoo.com: {e}"

        self.a3_cookie = self.obter_a3_presente()
        if not self.a3_cookie:
            return False, "Handshake concluído, porém Cookie A3 não foi emitido pelo edge."

        # Passo 2: Emissão do Crumb
        if verbose:
            sys.stderr.write("[AUTH] Cookie A3 capturado. Solicitando Crumb...\n")

        req_crumb = urllib.request.Request(
            URL_CRUMB,
            headers={"User-Agent": self.user_agent, "Accept": "*/*"}
        )
        try:
            with self.opener.open(req_crumb, timeout=DEFAULT_TIMEOUT) as resp:
                raw_crumb = resp.read().decode("utf-8", errors="replace").strip()
                if resp.status == 200 and raw_crumb and "<" not in raw_crumb and len(raw_crumb) <= 64:
                    self.crumb = raw_crumb
                    return True, f"Autenticado com sucesso. Crumb: {self.crumb}"
                return False, f"Resposta de Crumb inesperada: {raw_crumb[:80]}"
        except Exception as e:
            return False, f"Falha ao consultar getcrumb: {e}"

    def request_raw(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[bytes] = None,
        max_retries: int = 5,
        renew_on_401: bool = True
    ) -> Tuple[int, Dict[str, str], bytes]:
        """
        Executa requisição HTTP com telemetria, tratamento de status e retries exponenciais.
        """
        h = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if headers:
            h.update(headers)

        req = urllib.request.Request(url, data=data, headers=h, method=method)

        for attempt in range(max_retries):
            t0 = time.perf_counter()
            try:
                with self.opener.open(req, timeout=DEFAULT_TIMEOUT) as resp:
                    raw_body = resp.read()
                    self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
                    self.last_bytes_count = len(raw_body)
                    self.last_status_code = resp.status
                    resp_headers = {k: v for k, v in resp.headers.items()}
                    return resp.status, resp_headers, raw_body

            except urllib.error.HTTPError as e:
                self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
                raw_body = e.read()
                self.last_bytes_count = len(raw_body)
                self.last_status_code = e.code
                resp_headers = {k: v for k, v in e.headers.items()}

                # Auto-recuperação em caso de sessão expirada / 401
                if e.code == 401 and renew_on_401 and attempt < 1:
                    sys.stderr.write("[REDE] Status 401 recebido. Renovando credenciais A3+Crumb...\n")
                    ok, _ = self.bootstrap_auth(verbose=False)
                    if ok:
                        # Se houver crumb na query string original, atualiza a URL
                        if "crumb=" in url and self.crumb:
                            parsed_url = urllib.parse.urlparse(url)
                            q_dict = urllib.parse.parse_qs(parsed_url.query)
                            q_dict["crumb"] = [self.crumb]
                            new_query = urllib.parse.urlencode(q_dict, doseq=True)
                            url = urllib.parse.urlunparse(parsed_url._replace(query=new_query))
                            req = urllib.request.Request(url, data=data, headers=h, method=method)
                        continue

                # Backoff exponencial para 429 (Rate Limit) ou 503 (Serviço Indisponível)
                if e.code in (429, 503) and attempt < max_retries - 1:
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.6)
                    sys.stderr.write(f"[REDE] Status {e.code}. Tentativa {attempt + 1}/{max_retries}. Pausa de {backoff:.2f}s...\n")
                    time.sleep(backoff)
                    continue

                return e.code, resp_headers, raw_body

            except Exception as e:
                self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
                self.last_bytes_count = 0
                self.last_status_code = 0
                if attempt < max_retries - 1:
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.4)
                    time.sleep(backoff)
                    continue
                raise e

        return self.last_status_code, {}, b""


# ═══════════════════════ Cliente do Endpoint /v7 ════════════════════════════

class QuoteClient:
    """Controlador de alto nível para chamadas ao GET /v7/finance/quote."""
    def __init__(self, net: NetworkEngine, default_host: str = HOST_QUERY1):
        self.net = net
        self.host = default_host

    def build_url(
        self,
        symbols: List[str],
        fields: Optional[List[str]] = None,
        formatted: bool = True,
        lang: str = "en-US",
        region: str = "US",
        crumb: Optional[str] = None,
        cors_domain: Optional[str] = "finance.yahoo.com",
        host: Optional[str] = None
    ) -> str:
        h = host or self.host
        params: Dict[str, Any] = {
            "symbols": ",".join(symbols),
            "formatted": "true" if formatted else "false",
            "lang": lang,
            "region": region
        }
        if fields:
            params["fields"] = ",".join(fields)
        if cors_domain:
            params["corsDomain"] = cors_domain
        if crumb:
            params["crumb"] = crumb

        qs = urllib.parse.urlencode(params)
        return f"https://{h}{ENDPOINT_PATH}?{qs}"

    def fetch_quotes(
        self,
        symbols: List[str],
        fields: Optional[List[str]] = None,
        formatted: bool = True,
        lang: str = "en-US",
        region: str = "US",
        anonimo: bool = False,
        host: Optional[str] = None,
        crumb_as_header: bool = False
    ) -> Tuple[Optional[Dict[str, Any]], bytes]:
        """
        Executa requisição ao endpoint /v7/finance/quote.
        Retorna: (JSON decodificado se sucesso, Bytes brutos recebidos)
        """
        token = None
        custom_headers = {}
        if not anonimo:
            if not self.net.crumb:
                self.net.bootstrap_auth()
            token = self.net.crumb
            if crumb_as_header and token:
                custom_headers["x-crumb"] = token
                token = None

        url = self.build_url(
            symbols=symbols,
            fields=fields,
            formatted=formatted,
            lang=lang,
            region=region,
            crumb=token,
            host=host
        )

        status, _, raw_bytes = self.net.request_raw(url, headers=custom_headers)
        if status == 200:
            try:
                parsed = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                return parsed, raw_bytes
            except json.JSONDecodeError:
                return None, raw_bytes
        return None, raw_bytes


# ════════════════════ Componentes Gráficos de Terminal ══════════════════════

class ConsoleRenderer:
    """Renderizador visual de caixas, tabelas e avisos com suporte a alinhamento ANSI."""
    def __init__(self, palette: Palette, box: BoxChars):
        self.p = palette
        self.b = box

    def get_term_width(self) -> int:
        return shutil.get_terminal_size((80, 24)).columns

    def caixa_titulo(self, titulo: str, subtitulo: Optional[str] = None, max_w: Optional[int] = None) -> None:
        tw = min(self.get_term_width(), max_w or 80)
        inner_w = max(10, tw - 4)

        t_vis = pad_vis(f" {self.p.BOLD}{self.p.CYAN}{titulo}{self.p.RESET} ", inner_w, "<")
        topo = f"{self.p.GRAY}{self.b.TL}{self.b.H}{self.p.RESET}{t_vis}{self.p.GRAY}{self.b.H}{self.b.TR}{self.p.RESET}"
        print(topo)

        if subtitulo:
            s_vis = pad_vis(f" {self.p.DIM}{subtitulo}{self.p.RESET}", inner_w + 2, "<")
            meio = f"{self.p.GRAY}{self.b.V}{self.p.RESET}{s_vis}{self.p.GRAY}{self.b.V}{self.p.RESET}"
            print(meio)

        base = f"{self.p.GRAY}{self.b.BL}{self.b.H * (inner_w + 2)}{self.b.BR}{self.p.RESET}"
        print(base)

    def print_tabela_cotacoes(self, itens: List[Dict[str, Any]]) -> None:
        """Exibe tabela formatada com alinhamento perfeito imune a códigos ANSI."""
        if not itens:
            print(f"{self.p.YELLOW}[AVISO] Nenhum item disponível para renderização.{self.p.RESET}")
            return

        colunas = [
            ("SÍMBOLO", 10, "<"),
            ("NOME", 20, "<"),
            ("TIPO", 13, "<"),
            ("PREÇO", 12, ">"),
            ("VAR", 11, ">"),
            ("VAR %", 10, ">"),
            ("MKT CAP / VOL", 14, ">"),
            ("ESTADO", 8, "^")
        ]

        b = self.b
        # Linha Superior
        t_top = b.TL + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + b.TR
        print(f"{self.p.GRAY}{t_top}{self.p.RESET}")

        # Cabeçalho
        h_cells = []
        for nome, w, al in colunas:
            h_cells.append(f" {pad_vis(f'{self.p.BOLD}{self.p.WHITE}{nome}{self.p.RESET}', w, al)} ")
        print(f"{self.p.GRAY}{b.V}{self.p.RESET}" + f"{self.p.GRAY}{b.V}{self.p.RESET}".join(h_cells) + f"{self.p.GRAY}{b.V}{self.p.RESET}")

        # Separador do Cabeçalho
        t_mid = b.LT + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + b.RT
        print(f"{self.p.GRAY}{t_mid}{self.p.RESET}")

        for it in itens:
            sym = it.get("symbol", "—")
            nome = it.get("shortName") or it.get("longName") or "—"
            tipo = it.get("quoteType", "—")
            moeda = it.get("currency", "")

            # Extração de preço
            pr_val = it.get("regularMarketPrice")
            if isinstance(pr_val, dict): pr_val = pr_val.get("raw")
            pr_str = fmt_numero_br(pr_val, 2)
            if moeda and pr_val is not None:
                pr_str = f"{pr_str}"

            # Extração de variação nominal
            ch_val = it.get("regularMarketChange")
            if isinstance(ch_val, dict): ch_val = ch_val.get("raw")
            ch_str = fmt_numero_br(ch_val, 2)
            if ch_val is not None and float(ch_val) > 0:
                ch_str = f"+{ch_str}"

            # Extração de variação percentual
            pct_val = it.get("regularMarketChangePercent")
            if isinstance(pct_val, dict): pct_val = pct_val.get("raw")
            pct_str = fmt_percentual_br(pct_val)

            # Coloração condicional
            if pct_val is not None:
                cor_v = self.p.GREEN if float(pct_val) > 0 else (self.p.RED if float(pct_val) < 0 else self.p.WHITE)
            else:
                cor_v = self.p.WHITE

            ch_str_c = f"{cor_v}{ch_str}{self.p.RESET}"
            pct_str_c = f"{cor_v}{pct_str}{self.p.RESET}"

            # Grandeza: Market Cap ou Volume das 24h
            mc_val = it.get("marketCap")
            if isinstance(mc_val, dict): mc_val = mc_val.get("raw")
            vol_val = it.get("regularMarketVolume") or it.get("volume24Hr")
            if isinstance(vol_val, dict): vol_val = vol_val.get("raw")

            grandeza_str = fmt_grandeza_br(mc_val) if mc_val else fmt_grandeza_br(vol_val)

            estado = it.get("marketState", "—")
            cor_est = self.p.GREEN if estado == "REGULAR" else self.p.YELLOW
            estado_c = f"{cor_est}{estado[:7]}{self.p.RESET}"

            # Células da linha
            row_vals = [
                (f"{self.p.BOLD}{self.p.CYAN}{sym[:9]}{self.p.RESET}", colunas[0][1], colunas[0][2]),
                (nome[:19], colunas[1][1], colunas[1][2]),
                (tipo[:12], colunas[2][1], colunas[2][2]),
                (pr_str[:11], colunas[3][1], colunas[3][2]),
                (ch_str_c, colunas[4][1], colunas[4][2]),
                (pct_str_c, colunas[5][1], colunas[5][2]),
                (grandeza_str[:13], colunas[6][1], colunas[6][2]),
                (estado_c, colunas[7][1], colunas[7][2])
            ]

            c_cells = [f" {pad_vis(val, w, al)} " for val, w, al in row_vals]
            print(f"{self.p.GRAY}{b.V}{self.p.RESET}" + f"{self.p.GRAY}{b.V}{self.p.RESET}".join(c_cells) + f"{self.p.GRAY}{b.V}{self.p.RESET}")

        # Linha Inferior
        t_bot = b.BL + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + b.BR
        print(f"{self.p.GRAY}{t_bot}{self.p.RESET}")


# ═══════════════ Módulo 1: Suíte de Verificação ao Vivo ══════════════════════

def executar_suite_testes_ao_vivo(client: QuoteClient, p: Palette, box: BoxChars) -> None:
    """Executa e audita em tempo real os 5 comportamentos documentados da API."""
    print(f"\n{p.BOLD}{p.BLUE}══════ INICIANDO SUÍTE DE TESTES AO VIVO (/v7/finance/quote) ══════{p.RESET}\n")

    casos_de_teste = [
        ("1. Autenticação Anônima (HTTP 200 sem A3/Crumb)", ["AAPL"], None, True, True),
        ("2. Lote Misto Heterogêneo (EQUITY, CRYPTO, FUTURE, INDEX)", ["AAPL", "BTC-USD", "ES=F", "^GSPC"], None, True, False),
        ("3. Tolerância a Ticker Inexistente (Não deve falhar o lote)", ["AAPL", "INEXISTENTE_9999_XYZ", "PETR4.SA"], None, True, False),
        ("4. Modo de Alta Performance (formatted=false com primitivos)", ["AAPL", "PETR4.SA"], None, False, False),
        ("5. Projeção Seletiva Aditiva (Array Canônico W de 34 campos)", ["AAPL"], CANONICAL_W_FIELDS, True, False)
    ]

    passou_total = 0

    for titulo, tickers, fields, fmt, anon in casos_de_teste:
        sys.stdout.write(f"{p.BOLD}[TESTE]{p.RESET} {pad_vis(titulo, 62, '<')} ")
        sys.stdout.flush()

        t0 = time.perf_counter()
        dados, raw_bytes = client.fetch_quotes(tickers, fields=fields, formatted=fmt, anonimo=anon)
        lat = (time.perf_counter() - t0) * 1000.0

        if not dados or "quoteResponse" not in dados:
            print(f"{p.RED}[FALHA]{p.RESET} (Erro na resposta HTTP ou JSON inválido)")
            continue

        res = dados["quoteResponse"].get("result", [])
        aprovado = False

        if "Anônima" in titulo:
            aprovado = len(res) == 1 and res[0].get("symbol") == "AAPL"
        elif "Lote Misto" in titulo:
            tipos = {item.get("quoteType") for item in res}
            aprovado = len(res) >= 3 and len(tipos) >= 3
        elif "Tolerância" in titulo:
            retornados = [item.get("symbol") for item in res]
            aprovado = "AAPL" in retornados and "PETR4.SA" in retornados and "INEXISTENTE_9999_XYZ" not in retornados
        elif "formatted=false" in titulo:
            pr = res[0].get("regularMarketPrice") if res else None
            aprovado = isinstance(pr, (int, float))
        elif "Canônico W" in titulo:
            item = res[0] if res else {}
            campos_presentes = sum(1 for c in CANONICAL_W_FIELDS if c in item)
            aprovado = campos_presentes >= 25

        if aprovado:
            passou_total += 1
            print(f"{p.GREEN}[PASS]{p.RESET} {p.DIM}{lat:6.1f}ms | {len(raw_bytes):5d}B{p.RESET}")
        else:
            print(f"{p.RED}[FALHA]{p.RESET} {p.DIM}{lat:6.1f}ms | Resposta fora do contrato esperado{p.RESET}")

    taxa = (passou_total / len(casos_de_teste)) * 100.0
    print(f"\n{p.BOLD}Resultado da Suíte: {passou_total}/{len(casos_de_teste)} aprovados ({taxa:.1f}% de conformidade){p.RESET}\n")


# ══════════════ Módulo 2: Auditoria de Invariantes Offline ═══════════════════

def executar_auditoria_invariantes(json_data: Any, p: Palette) -> None:
    """Verifica e certifica se uma estrutura JSON atende às invariantes do Quote Engine."""
    print(f"\n{p.BOLD}{p.MAGENTA}══════ AUDITORIA DE INVARIANTES OFFLINE ══════{p.RESET}\n")

    invariantes: List[Tuple[str, bool, str]] = []

    # Invariante 1: Envelope de Sucesso
    tem_qr = isinstance(json_data, dict) and "quoteResponse" in json_data
    invariantes.append(("1. Presença do Envelope 'quoteResponse'", tem_qr, "O objeto raiz deve encapsular quoteResponse"))

    if not tem_qr:
        for tit, ok, desc in invariantes:
            st = f"{p.GREEN}[OK]{p.RESET}" if ok else f"{p.RED}[FALHA]{p.RESET}"
            print(f"{st} {tit}: {desc}")
        return

    qr = json_data.get("quoteResponse", {})
    res = qr.get("result")
    err = qr.get("error")

    # Invariante 2: Ausência de Erros e Presença da Lista Result
    invariantes.append(("2. Campo 'error' é estritamente nulo", err is None, "Erros estruturais de servidor devem ser nulos"))
    invariantes.append(("3. Campo 'result' é uma lista válida", isinstance(res, list), "O retorno de instrumentos deve ser um array"))

    if isinstance(res, list) and len(res) > 0:
        # Invariante 4: Identidade do Ticker
        todos_com_symbol = all("symbol" in it and isinstance(it["symbol"], str) for it in res)
        invariantes.append(("4. Todos os itens contêm 'symbol' string", todos_com_symbol, "Chave primária de identificação obrigatória"))

        # Invariante 5: Tipagem Polimórfica Válida
        quote_types_validos = {"EQUITY", "ETF", "MUTUALFUND", "INDEX", "FUTURE", "OPTION", "CURRENCY", "CRYPTOCURRENCY"}
        todos_quote_types = all(it.get("quoteType") in quote_types_validos for it in res)
        invariantes.append(("5. Tipos de Ativo ('quoteType') conhecidos", todos_quote_types, f"Deve pertencer a: {quote_types_validos}"))

        # Invariante 6: Regra Crítica de Percentual (Unidade %)
        # Verifica se o raw de regularMarketChangePercent não foi equivocadamente multiplicado por 100
        pct_normal = True
        for it in res:
            pct = it.get("regularMarketChangePercent")
            if isinstance(pct, dict): pct = pct.get("raw")
            if pct is not None and abs(float(pct)) > 1000.0:
                pct_normal = False
                break
        invariantes.append(("6. Unidade de 'regularMarketChangePercent' (<1000%)", pct_normal, "Percentuais brutos não devem ser inflados"))

    for tit, ok, desc in invariantes:
        st = f"{p.GREEN}[CONFORME]{p.RESET}" if ok else f"{p.RED}[VIOLAÇÃO]{p.RESET}"
        print(f"{st} {pad_vis(tit, 52, '<')} {p.DIM}{desc}{p.RESET}")

    print(f"\n{p.BOLD}Auditoria concluída.{p.RESET}\n")


# ═══════════════ Módulo 3: Console de Requisições Brutas ═════════════════════

def console_requisicao_bruta(net: NetworkEngine, p: Palette, box: BoxChars) -> None:
    """Interface interativa de diagnóstico de baixo nível de rede."""
    print(f"\n{p.BOLD}{p.CYAN}══════ CONSOLE DE REQUISIÇÃO BRUTA ══════{p.RESET}")
    print("Permite configurar método HTTP, host, parâmetros manuais e vetor de Crumb.\n")

    metodo = input(f"{p.BOLD}Método HTTP (GET/POST/HEAD/OPTIONS) [GET]: {p.RESET}").strip().upper() or "GET"
    host = input(f"{p.BOLD}Host ({HOST_QUERY1} ou {HOST_QUERY2}) [{HOST_QUERY1}]: {p.RESET}").strip() or HOST_QUERY1
    tickers_str = input(f"{p.BOLD}Símbolos (separados por vírgula) [AAPL]: {p.RESET}").strip() or "AAPL"

    print("\nVetor do Crumb:")
    print(" [1] Query String (?crumb=...)")
    print(" [2] Header HTTP (x-crumb: ...)")
    print(" [3] Sem Crumb (Requisição Anônima Pura)")
    opt_crumb = input(f"{p.BOLD}Escolha o vetor [1]: {p.RESET}").strip() or "1"

    token = None
    custom_headers: Dict[str, str] = {}
    if opt_crumb in ("1", "2"):
        if not net.crumb:
            print(f"{p.DIM}[AUTH] Crumb ausente. Executando bootstrap...{p.RESET}")
            net.bootstrap_auth()
        token = net.crumb
        if opt_crumb == "2" and token:
            custom_headers["x-crumb"] = token
            token = None

    params: Dict[str, str] = {
        "symbols": tickers_str,
        "formatted": "true"
    }
    if token:
        params["crumb"] = token

    extra_params_str = input(f"{p.BOLD}Parâmetros extras de Query (ex: fields=marketCap,beta) [Enter para nenhum]: {p.RESET}").strip()
    if extra_params_str:
        for par in extra_params_str.split("&"):
            if "=" in par:
                k, v = par.split("=", 1)
                params[k.strip()] = v.strip()

    qs = urllib.parse.urlencode(params)
    url = f"https://{host}{ENDPOINT_PATH}?{qs}"

    print(f"\n{p.DIM}Disparando: {metodo} {url}{p.RESET}\n")
    try:
        status, headers, body = net.request_raw(url, method=metodo, headers=custom_headers)
        cor_st = p.GREEN if status == 200 else p.RED
        print(f"Status HTTP: {cor_st}{status}{p.RESET} | Latência: {net.last_latency_ms:.1f}ms | Tamanho: {len(body)} bytes\n")

        print(f"{p.BOLD}Cabeçalhos de Resposta:{p.RESET}")
        for hk, hv in list(headers.items())[:8]:
            print(f"  {p.GRAY}{hk}:{p.RESET} {hv}")

        print(f"\n{p.BOLD}Prévia do Corpo (primeiros 400 bytes):{p.RESET}")
        print(f"{p.DIM}{body[:400].decode('utf-8', errors='replace')}{p.RESET}...")

    except Exception as e:
        print(f"{p.RED}[ERRO]{p.RESET} Falha ao executar requisição bruta: {e}")


# ══════════════ Módulo 4: Comparador Multi-Símbolo ═══════════════════════════

def comparador_multi_simbolo(client: QuoteClient, p: Palette, box: BoxChars) -> None:
    """Compara métricas e atributos entre diferentes símbolos selecionados."""
    print(f"\n{p.BOLD}{p.YELLOW}══════ COMPARADOR MULTI-SÍMBOLO ══════{p.RESET}")
    print("Digite símbolos de classes iguais ou distintas para comparar lado a lado.\n")

    entrada = input(f"{p.BOLD}Informe símbolos (ex: AAPL,MSFT,BTC-USD,PETR4.SA): {p.RESET}").strip()
    if not entrada:
        print(f"{p.YELLOW}[AVISO] Nenhum símbolo informado.{p.RESET}")
        return

    syms = [s.strip().upper() for s in entrada.split(",") if s.strip()]
    dados, _ = client.fetch_quotes(syms, formatted=False)

    if not dados or "quoteResponse" not in dados:
        print(f"{p.RED}[ERRO] Falha ao coletar dados para comparação.{p.RESET}")
        return

    itens = dados["quoteResponse"].get("result", [])
    if not itens:
        print(f"{p.RED}[ERRO] Nenhum instrumento retornado.{p.RESET}")
        return

    metricas = [
        ("quoteType", "Classe do Ativo"),
        ("currency", "Moeda"),
        ("regularMarketPrice", "Preço Atual"),
        ("regularMarketChangePercent", "Variação Diária"),
        ("marketCap", "Valor de Mercado"),
        ("regularMarketVolume", "Volume Regular"),
        ("fiftyTwoWeekRange", "Faixa 52 Semanas"),
        ("trailingPE", "Múltiplo P/L (LTM)"),
        ("marketState", "Estado da Sessão")
    ]

    col_w = max(18, min(24, (shutil.get_terminal_size((80, 24)).columns - 26) // max(1, len(itens))))
    label_w = 24

    # Cabeçalho
    linha_cab = pad_vis("MÉTRICA / ATRIBUTO", label_w, "<") + " " + " ".join(pad_vis(it.get("symbol", ""), col_w, "^") for it in itens)
    print(f"\n{p.BOLD}{p.BG_BLUE}{linha_cab}{p.RESET}")

    for chave, label in metricas:
        valores_linha = []
        for it in itens:
            v = it.get(chave)
            if v is None:
                v_str = "—"
            elif chave == "regularMarketPrice":
                v_str = fmt_numero_br(v, 2)
            elif chave == "regularMarketChangePercent":
                v_str = fmt_percentual_br(v)
            elif chave in ("marketCap", "regularMarketVolume"):
                v_str = fmt_grandeza_br(v)
            else:
                v_str = str(v)
            valores_linha.append(pad_vis(v_str, col_w, "^"))

        lbl_formatado = pad_vis(label, label_w, "<")
        print(f"{p.BOLD}{lbl_formatado}{p.RESET} " + " ".join(valores_linha))
    print()


# ══════════════ Módulo 5: Gestão de Sessão & Autenticação ════════════════════

def gestao_autenticacao(net: NetworkEngine, p: Palette, box: BoxChars) -> None:
    """Exibe estado dos cookies, tokens e permite renovação ou inspeção."""
    print(f"\n{p.BOLD}{p.CYAN}══════ GESTÃO DE SESSÃO & CREDENCIAIS ══════{p.RESET}\n")

    a3 = net.obter_a3_presente()
    print(f" • {p.BOLD}Cookie A3 Presente:{p.RESET} " + (f"{p.GREEN}Sim{p.RESET} ({len(a3)} chars)" if a3 else f"{p.RED}Não{p.RESET}"))
    print(f" • {p.BOLD}Crumb em Memória:{p.RESET}   " + (f"{p.GREEN}{net.crumb}{p.RESET}" if net.crumb else f"{p.YELLOW}Não emitido{p.RESET}"))
    print(f" • {p.BOLD}Última Latência:{p.RESET}     {net.last_latency_ms:.1f} ms")
    print(f" • {p.BOLD}Último Status HTTP:{p.RESET}  {net.last_status_code}")

    print("\nAções Disponíveis:")
    print(" [1] Forçar Handshake Completo (fc.yahoo.com -> getcrumb)")
    print(" [2] Limpar Cookies e Descartar Crumb")
    print(" [3] Voltar ao Menu Principal")

    opt = input(f"\n{p.BOLD}Escolha uma opção: {p.RESET}").strip()
    if opt == "1":
        ok, msg = net.bootstrap_auth(verbose=True)
        if ok:
            print(f"{p.GREEN}[SUCESSO]{p.RESET} {msg}")
        else:
            print(f"{p.RED}[FALHA]{p.RESET} {msg}")
    elif opt == "2":
        net.cookie_jar.clear()
        net.crumb = None
        net.a3_cookie = None
        print(f"{p.YELLOW}[AVISO] Sessão redefinida. Credenciais removidas.{p.RESET}")


# ════════════════════ Menu Principal & CLI Dispatcher ═══════════════════════

def menu_interativo(client: QuoteClient, renderer: ConsoleRenderer, p: Palette, box: BoxChars) -> None:
    """Loop principal de navegação interativa sem risco de fechamento inesperado."""
    while True:
        try:
            renderer.caixa_titulo("YAHOO FINANCE QUOTE EXPLORER v7", "Endpoint: /v7/finance/quote | stdlib puro | pt-BR")
            print(" [1] Consulta Rápida de Símbolos Customizados")
            print(" [2] Tabela Rápida de Mercados por Preset")
            print(" [3] Comparador Multi-Símbolo")
            print(" [4] Console de Requisições Brutas (Diagnóstico de Rede)")
            print(" [5] Executar Suíte de Testes ao Vivo (Validação do Endpoint)")
            print(" [6] Auditoria de Invariantes Estruturais Offline")
            print(" [7] Gestão de Sessão, Autenticação e Credenciais")
            print(" [8] Exportar Resposta JSON Integral para Arquivo")
            print(" [0] Encerrar Aplicativo")

            escolha = input(f"\n{p.BOLD}Opção desejada: {p.RESET}").strip()

            if escolha == "0":
                print(f"\n{p.CYAN}Encerrando aplicação de forma limpa. Até logo!{p.RESET}")
                break

            elif escolha == "1":
                inp = input(f"\n{p.BOLD}Digite os símbolos (ex: PETR4.SA,AAPL,BTC-USD): {p.RESET}").strip()
                if inp:
                    syms = [s.strip().upper() for s in inp.split(",") if s.strip()]
                    dados, _ = client.fetch_quotes(syms)
                    if dados:
                        res = dados.get("quoteResponse", {}).get("result", [])
                        renderer.print_tabela_cotacoes(res)
                    else:
                        print(f"{p.RED}[ERRO] Falha ao consultar símbolos informados.{p.RESET}")

            elif escolha == "2":
                print("\nPresets Disponíveis:")
                for k, (nome, syms) in PRESET_GROUPS.items():
                    print(f" [{k}] {nome} ({', '.join(syms)})")
                pk = input(f"\n{p.BOLD}Escolha o preset [1]: {p.RESET}").strip() or "1"
                if pk in PRESET_GROUPS:
                    _, syms = PRESET_GROUPS[pk]
                    dados, _ = client.fetch_quotes(syms)
                    if dados:
                        res = dados.get("quoteResponse", {}).get("result", [])
                        renderer.print_tabela_cotacoes(res)

            elif escolha == "3":
                comparador_multi_simbolo(client, p, box)

            elif escolha == "4":
                console_requisicao_bruta(client.net, p, box)

            elif escolha == "5":
                executar_suite_testes_ao_vivo(client, p, box)

            elif escolha == "6":
                print("\nOrigem dos Dados:")
                print(" [1] Coletar payload atual de lote misto ao vivo")
                print(" [2] Carregar arquivo JSON salvo localmente")
                opt_aud = input(f"{p.BOLD}Opção [1]: {p.RESET}").strip() or "1"
                if opt_aud == "1":
                    dados, _ = client.fetch_quotes(["AAPL", "BTC-USD", "ES=F", "^GSPC"])
                    if dados:
                        executar_auditoria_invariantes(dados, p)
                else:
                    caminho = input(f"{p.BOLD}Informe o caminho do arquivo JSON: {p.RESET}").strip()
                    if os.path.isfile(caminho):
                        try:
                            with open(caminho, "r", encoding="utf-8") as f:
                                carregar = json.load(f)
                            executar_auditoria_invariantes(carregar, p)
                        except Exception as e:
                            print(f"{p.RED}[ERRO] Falha ao ler arquivo: {e}{p.RESET}")
                    else:
                        print(f"{p.RED}[ERRO] Arquivo não encontrado.{p.RESET}")

            elif escolha == "7":
                gestao_autenticacao(client.net, p, box)

            elif escolha == "8":
                inp = input(f"\n{p.BOLD}Símbolos para exportação [AAPL,PETR4.SA]: {p.RESET}").strip() or "AAPL,PETR4.SA"
                syms = [s.strip().upper() for s in inp.split(",") if s.strip()]
                fmt_opt = input(f"{p.BOLD}Manter formatação 'raw/fmt'? (s/n) [s]: {p.RESET}").strip().lower() != "n"
                _, raw_bytes = client.fetch_quotes(syms, formatted=fmt_opt)
                if raw_bytes:
                    nome_arq = f"quotes_export_{int(time.time())}.json"
                    with open(nome_arq, "wb") as f:
                        f.write(raw_bytes)
                    print(f"{p.GREEN}[SUCESSO]{p.RESET} Arquivo exportado com paridade de bytes: {nome_arq} ({len(raw_bytes)} bytes)")

            else:
                print(f"{p.YELLOW}[AVISO] Opção inválida. Tente novamente.{p.RESET}")

        except KeyboardInterrupt:
            print(f"\n\n{p.YELLOW}[AVISO] Operação cancelada pelo usuário (Ctrl+C). Retornando ao menu...{p.RESET}")
        except EOFError:
            print(f"\n\n{p.CYAN}Entrada encerrada (EOF). Fechando aplicativo...{p.RESET}")
            break
        except Exception as e:
            print(f"\n{p.RED}[ERRO NÃO TRATADO]{p.RESET} Ocorreu uma exceção: {e}")

        time.sleep(0.3)


# ════════════════════════ Ponto de Entrada (Main) ═══════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cliente de Terminal & Aplicativo Interativo do Endpoint /v7/finance/quote da Yahoo Finance",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Argumentos de Compatibilidade com Versões Anteriores
    parser.add_argument("--symbols", "-s", default=None, help="Lista de símbolos CSV para consulta em batch")
    parser.add_argument("--fields", "-f", default=None, help="Campos projetados separados por vírgula")
    parser.add_argument("--canonical", action="store_true", help="Utiliza a lista canônica W de 34 campos")
    parser.add_argument("--raw", action="store_true", help="formatted=false: recebe números primitivos diretos")
    parser.add_argument("--anonimo", action="store_true", help="Força chamada anônima sem credenciais")
    parser.add_argument("--host", choices=[HOST_QUERY1, HOST_QUERY2], default=HOST_QUERY1, help="Host edge da Yahoo")
    parser.add_argument("--table", action="store_true", help="Imprime resultado como tabela estilizada")
    parser.add_argument("--json", action="store_true", help="Gera saída estritamente em JSON (paridade de bytes)")
    parser.add_argument("--test-live", action="store_true", help="Executa suíte de validação ao vivo direto via CLI")
    parser.add_argument("--audit", metavar="ARQ", default=None, help="Executa auditoria de invariantes em um arquivo JSON")

    # Modos Visuais e Comportamento
    parser.add_argument("--ascii", action="store_true", help="Utiliza caracteres ASCII simples para caixas e tabelas")
    parser.add_argument("--sem-cores", "--no-color", action="store_true", help="Desativa saída de cores ANSI")
    parser.add_argument("--no-pause", action="store_true", help="Não pausa com 'Pressione ENTER' ao finalizar a execução")
    parser.add_argument("-v", "--verbose", action="store_true", help="Ativa mensagens detalhadas de diagnóstico de rede")

    args = parser.parse_args()

    # Inicialização de UI
    usa_cores = not args.sem_cores and os.environ.get("NO_COLOR") is None
    p = Palette(enabled=usa_cores)
    box = BoxChars(ascii_mode=args.ascii)
    renderer = ConsoleRenderer(p, box)

    # Inicialização da Rede
    net = NetworkEngine()
    client = QuoteClient(net, default_host=args.host)

    try:
        # Modo 1: Auditoria Offline via CLI
        if args.audit:
            with open(args.audit, "r", encoding="utf-8") as f:
                dados_json = json.load(f)
            executar_auditoria_invariantes(dados_json, p)
            return 0

        # Modo 2: Suíte de Testes ao Vivo via CLI
        if args.test_live:
            executar_suite_testes_ao_vivo(client, p, box)
            return 0

        # Modo 3: Consulta Direta em Linha de Comando (Automação / Scripts)
        if args.symbols:
            syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            fields = CANONICAL_W_FIELDS if args.canonical else ([f.strip() for f in args.fields.split(",")] if args.fields else None)

            dados, raw_bytes = client.fetch_quotes(
                symbols=syms,
                fields=fields,
                formatted=not args.raw,
                anonimo=args.anonimo,
                host=args.host
            )

            if args.json:
                sys.stdout.buffer.write(raw_bytes)
                sys.stdout.buffer.write(b"\n")
                return 0

            if args.table:
                if dados:
                    res = dados.get("quoteResponse", {}).get("result", [])
                    renderer.print_tabela_cotacoes(res)
                else:
                    sys.stderr.write("Erro: Falha ao obter dados.\n")
                    return 1
            else:
                # Saída JSON indentada padrão
                if dados:
                    print(json.dumps(dados, indent=2, ensure_ascii=False))
                else:
                    sys.stdout.buffer.write(raw_bytes)
            return 0

        # Modo 4: Modo Interativo Completo (Anti-Fechamento)
        menu_interativo(client, renderer, p, box)
        return 0

    except KeyboardInterrupt:
        print(f"\n{p.YELLOW}[AVISO] Execução interrompida.{p.RESET}")
        return 130
    except Exception as e:
        print(f"\n{p.RED}[ERRO CRÍTICO]{p.RESET} {e}")
        return 1
    finally:
        # Blindagem Anti-Fechamento para duplo-clique no Windows
        if not args.no_pause and sys.stdin.isatty():
            try:
                input(f"\n{p.DIM}Pressione ENTER para fechar a janela...{p.RESET}")
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())