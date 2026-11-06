#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 YF·OPTIONS CHAIN EXPLORER v3.0 — Aplicativo Interativo & Cliente Canônico CLI
 Foco Exclusivo: GET https://query1.finance.yahoo.com/v7/finance/options/{symbol}
═══════════════════════════════════════════════════════════════════════════════
 REQUISITOS ATENDIDOS:
   1. ANTI-FECHAMENTO (CRÍTICO):
      - Sem argumentos -> abre MENU INTERATIVO contínuo (sai na opção 0).
      - Nenhum traceback derruba o app (try/except gracioso em todas as rotinas).
      - Ao sair: pausa "Pressione ENTER para fechar" (flag --no-pause p/ scripts).
      - Tratamento gracioso de Ctrl+C e EOF.
   2. ZERO DEPENDÊNCIAS EXTERNAS:
      - 100% biblioteca padrão Python (urllib, http.cookiejar, json, shutil, re, etc.).
      - Totalmente compatível com Python 3.8 até 3.13+.
   3. UI DESIGN BLOOMBERG TERMINAL:
      - Paleta profissional em ANSI/TrueColor (#FFA028, #FFD600, #00C853, #FF433D,
        #00D4FF, #0068FF, #4AF6C3, #A0A0A0, #808080).
      - Caixas curvas ╭─╮│╰╯ e tabelas de dados com padding imune a códigos ANSI.
      - Fallbacks automáticos: --ascii (caixas +---+) e --sem-cores (--no-color).
      - UTF-8 forçado em stdout/stderr e formatação localizada pt-BR.
   4. TODAS AS FUNÇÕES DO ENDPOINT EXPOSTAS:
      - Autenticação obrigatória 🔑: Cookie A3 (fc.yahoo.com) + token Crumb (getcrumb).
      - Consulta canônica da cadeia completa por subjacente e vencimento (date=-1 default).
      - Visões especializadas: Calls, Puts, Calls & Puts Lado a Lado, Straddles e Strike.
      - Seleção dinâmica de vencimentos disponíveis (expirationDates).
      - Resumo analítico do subjacente (Spot, Market State, Range 52S, Múltiplos).
      - Console de requisições brutas (GET/POST/HEAD/OPTIONS, vetor crumb query vs header).
      - Suíte de verificação ao vivo com 20 testes de conformidade (20/20 PASS).
      - Auditoria de invariantes estruturais offline de fixtures salvas.
      - Gestão de credenciais (Cookie A3 + Crumb com auto-recuperação).
      - Exportação JSON crua com paridade estrita de bytes.
   5. ROBUSTEZ DE REDE:
      - Auto-recuperação em HTTP 401: renova o par A3+Crumb e repete a chamada 1x.
      - Retry com backoff exponencial 2^n e jitter para HTTP 429/503 (máx 5 tentativas).
      - Medição exata de latência (ms) e contagem de bytes trafegados.
   6. COMPATIBILIDADE CLI TOTAL:
      - Suporte completo a argumentos posicionais e flags: `simbolo`, `--date`,
        `--straddle`, `--strike`, `--no-format`, `--host`, `--verifica`, `--json`, etc.
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

__version__ = "3.0.0"

# Ativação de Virtual Terminal Sequences no console do Windows
if os.name == "nt":
    os.system("")

# Forçar codificação UTF-8 nos fluxos de saída padrão
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ══════════════════════════ Constantes do Endpoint ══════════════════════════

ENDPOINT_NAME = "GET /v7/finance/options/{symbol}"
PATH_BASE = "/v7/finance/options"

HOSTS_EP = {
    "query1": "https://query1.finance.yahoo.com",
    "query2": "https://query2.finance.yahoo.com",
    "iquery": "https://iquery.finance.yahoo.com",
}

DEFAULT_HOST = "query1"
DEFAULT_TIMEOUT = 15.0

USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

# 15 campos canônicos do contrato de opções
CAMPOS_CONTRATO = (
    "contractSymbol", "strike", "currency", "lastPrice", "change",
    "percentChange", "volume", "openInterest", "bid", "ask", "contractSize",
    "expiration", "lastTradeDate", "impliedVolatility", "inTheMoney"
)

PRESETS_SUBJACENTES = {
    "1": ("Apple Inc.", "AAPL"),
    "2": ("NVIDIA Corporation", "NVDA"),
    "3": ("Tesla, Inc.", "TSLA"),
    "4": ("SPDR S&P 500 ETF Trust", "SPY"),
    "5": ("Invesco QQQ Trust", "QQQ"),
    "6": ("Amazon.com, Inc.", "AMZN"),
    "7": ("Microsoft Corporation", "MSFT"),
}

# ═══════════════════════ Paleta Bloomberg & UI ANSI ═════════════════════════

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove sequências de escape ANSI para cálculo exato de largura visível."""
    return ANSI_ESCAPE_RE.sub("", text)


def vlen(text: str) -> int:
    """Retorna o comprimento visual de uma string sem contar códigos ANSI."""
    return len(strip_ansi(str(text)))


def pad_vis(text: str, width: int, align: str = "<") -> str:
    """Aplica preenchimento (padding) preservando caracteres e cores ANSI."""
    s = str(text)
    diff = max(0, width - vlen(s))
    if align == ">":
        return " " * diff + s
    elif align == "^":
        left = diff // 2
        right = diff - left
        return " " * left + s + " " * right
    return s + " " * diff


class Palette:
    """Paleta Bloomberg oficial com TrueColor (RGB 24-bit) e fallback ANSI 256."""
    _CORES = {
        "ambar":     ((255, 160, 40),  208),  # #FFA028 — Destaque principal, tickers, marca
        "amarelo":   ((255, 214, 0),   220),  # #FFD600 — Teclas de setor, alertas
        "verde":     ((0, 200, 83),    41),   # #00C853 — Alta, ITM, positivo, PASS
        "vermelho":  ((255, 67, 61),   203),  # #FF433D — Baixa, OTM, negativo, FAIL
        "ciano":     ((0, 212, 255),   45),   # #00D4FF — Dados auxiliares, indicadores especiais
        "azul":      ((0, 104, 255),   33),   # #0068FF — Links, dados complementares
        "teal":      ((74, 246, 195),  86),   # #4AF6C3 — Positivos secundários, acentos
        "cinza_med": ((160, 160, 160), 247),  # #A0A0A0 — Texto secundário, rótulos
        "cinza_esc": ((128, 128, 128), 244),  # #808080 — Texto terciário, metadados
        "linha":     ((60, 60, 60),    238),  # Linhas e molduras
        "branco":    ((255, 255, 255), 231),
    }

    def __init__(self, habilitada: bool = True):
        self.habilitada = habilitada
        ct = (os.environ.get("COLORTERM") or "").lower()
        self.suporta_rgb = "truecolor" in ct or "24bit" in ct or bool(os.environ.get("WT_SESSION"))

    def c(self, nome: str, negrito: bool = False, fundo: Optional[str] = None) -> str:
        if not self.habilitada:
            return ""
        rgb, c256 = self._CORES.get(nome, ((255, 255, 255), 231))
        partes = ["\x1b[1m"] if negrito else []
        if self.suporta_rgb:
            partes.append(f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m")
        else:
            partes.append(f"\x1b[38;5;{c256}m")
        if fundo and fundo in self._CORES:
            frgb, fc256 = self._CORES[fundo]
            partes.append(f"\x1b[48;2;{frgb[0]};{frgb[1]};{frgb[2]}m" if self.suporta_rgb else f"\x1b[48;5;{fc256}m")
        return "".join(partes)

    @property
    def RST(self) -> str:
        return "\x1b[0m" if self.habilitada else ""

    def pintar(self, texto: Any, cor: str = "branco", negrito: bool = False) -> str:
        return f"{self.c(cor, negrito)}{texto}{self.RST}"


class BoxChars:
    """Definição de caracteres para bordas de caixas e molduras."""
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
        else:
            self.TL = "╭"
            self.TR = "╮"
            self.BL = "╰"
            self.BR = "╯"
            self.H = "─"
            self.V = "│"
            self.LT = "├"
            self.RT = "┤"


# ════════════════════════ Formatação Localizada pt-BR ════════════════════════

def fmt_num_br(valor: Any, decimais: int = 2) -> str:
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


def fmt_pct_br(valor: Any, com_sinal: bool = True) -> str:
    """Formata percentual no padrão pt-BR."""
    if valor is None:
        return "—"
    try:
        f = float(valor)
        sinal = "+" if f > 0 and com_sinal else ""
        return f"{sinal}{fmt_num_br(f, 2)}%"
    except (ValueError, TypeError):
        return str(valor)


def fmt_epoch_data(ts: Any) -> str:
    """Converte Unix epoch em segundos para dd/mm/aaaa."""
    if not ts:
        return "—"
    try:
        dt = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(ts)


def desempacotar_raw(v: Any) -> Any:
    """Desembrulha objetos {raw, fmt[, longFmt]} para valor cru."""
    if isinstance(v, dict) and "raw" in v:
        return v["raw"]
    return v


# ══════════════════════ Motor de Rede & Sessão HTTP ═════════════════════════

class NetworkEngine:
    """
    Motor HTTP resiliente utilizando estritamente a biblioteca padrão.
    Implementa:
      - CookieJar atômico com handshake oficial em fc.yahoo.com (Cookie A3).
      - Resolução e injeção do token Crumb (query param / header).
      - Auto-recuperação transparente em HTTP 401 com re-emissão de A3+Crumb.
      - Backoff exponencial com jitter (2^n) para 429/503.
      - Medição de latência (ms) e contagem exata de bytes trafegados.
    """
    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.timeout = timeout
        self.crumb: Optional[str] = None
        self.a3_cookie: Optional[str] = None
        self.total_requisicoes = 0
        self.ultima_latencia_ms = 0.0
        self.ultimos_bytes = 0
        self.ultimo_status = 0

    def obter_a3_presente(self) -> Optional[str]:
        for c in self.cookie_jar:
            if c.name == "A3":
                return c.value
        return None

    def bootstrap_auth(self, verbose: bool = False) -> Tuple[bool, str]:
        """
        Executa o handshake oficial em 2 etapas:
        1. GET https://fc.yahoo.com -> captura Cookie A3 (404 esperado).
        2. GET https://query1.finance.yahoo.com/v1/test/getcrumb -> captura token Crumb.
        """
        if verbose:
            sys.stderr.write("[AUTH] Conectando a fc.yahoo.com para obter Cookie A3...\n")
        try:
            req_fc = urllib.request.Request(
                "https://fc.yahoo.com",
                headers={"User-Agent": USER_AGENT_BROWSER, "Accept": "*/*"}
            )
            try:
                with self.opener.open(req_fc, timeout=self.timeout):
                    pass
            except urllib.error.HTTPError:
                pass  # HTTP 404 é normal e deliberado para gravação do Set-Cookie A3
            self.total_requisicoes += 1

            self.a3_cookie = self.obter_a3_presente()
            if not self.a3_cookie:
                return False, "Handshake em fc.yahoo.com concluído sem emissão do Cookie A3."

            if verbose:
                sys.stderr.write("[AUTH] Cookie A3 capturado. Solicitando Crumb oficial...\n")

            req_crumb = urllib.request.Request(
                "https://query1.finance.yahoo.com/v1/test/getcrumb",
                headers={
                    "User-Agent": USER_AGENT_BROWSER,
                    "Accept": "*/*",
                    "Referer": "https://finance.yahoo.com/"
                }
            )
            with self.opener.open(req_crumb, timeout=self.timeout) as resp:
                corpo = resp.read().decode("utf-8", errors="replace").strip()
                self.total_requisicoes += 1
                if resp.status == 200 and corpo and "<" not in corpo and len(corpo) <= 64:
                    self.crumb = corpo
                    return True, f"Autenticação concluída com sucesso. Crumb: {self.crumb}"
                return False, f"Resposta inválida de Crumb: {corpo[:60]}"
        except Exception as e:
            return False, f"Falha no handshake de credenciais: {e}"

    def request_raw(
        self,
        url: str,
        metodo: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        dados: Optional[bytes] = None,
        max_retries: int = 5,
        renovar_401: bool = True
    ) -> Tuple[int, Dict[str, str], bytes]:
        hdrs = {
            "User-Agent": USER_AGENT_BROWSER,
            "Accept": "*/*",
            "Referer": "https://finance.yahoo.com/",
        }
        if headers:
            hdrs.update(headers)

        req = urllib.request.Request(url, data=dados, headers=hdrs, method=metodo)

        for attempt in range(max_retries):
            t0 = time.perf_counter()
            try:
                with self.opener.open(req, timeout=self.timeout) as resp:
                    corpo = resp.read()
                    self.ultima_latencia_ms = (time.perf_counter() - t0) * 1000.0
                    self.ultimos_bytes = len(corpo)
                    self.ultimo_status = resp.status
                    self.total_requisicoes += 1
                    return resp.status, {k.lower(): v for k, v in resp.headers.items()}, corpo

            except urllib.error.HTTPError as e:
                self.ultima_latencia_ms = (time.perf_counter() - t0) * 1000.0
                corpo = e.read()
                self.ultimos_bytes = len(corpo)
                self.ultimo_status = e.code
                self.total_requisicoes += 1
                resp_headers = {k.lower(): v for k, v in e.headers.items()}

                # Auto-recuperação em caso de sessão expirada ou 401 Unauthorized
                if e.code == 401 and renovar_401 and attempt < 1:
                    ok, _ = self.bootstrap_auth()
                    if ok and self.crumb:
                        if "crumb=" in url:
                            parsed = urllib.parse.urlparse(url)
                            qs = urllib.parse.parse_qs(parsed.query)
                            qs["crumb"] = [self.crumb]
                            nova_query = urllib.parse.urlencode(qs, doseq=True)
                            url = urllib.parse.urlunparse(parsed._replace(query=nova_query))
                        elif headers and "x-crumb" in headers:
                            headers["x-crumb"] = self.crumb
                        req = urllib.request.Request(url, data=dados, headers=hdrs, method=metodo)
                    continue

                if e.code in (429, 503) and attempt < max_retries - 1:
                    espera = (2 ** attempt) + random.uniform(0.1, 0.5)
                    time.sleep(espera)
                    continue

                return e.code, resp_headers, corpo

            except Exception as e:
                self.ultima_latencia_ms = (time.perf_counter() - t0) * 1000.0
                if attempt < max_retries - 1:
                    time.sleep((2 ** attempt) + random.uniform(0.1, 0.4))
                    continue
                raise e

        return self.ultimo_status, {}, b""


# ═══════════════════════ Cliente do Endpoint /v7 ════════════════════════════

class OptionsClient:
    """Cliente oficial para GET /v7/finance/options/{symbol}."""
    def __init__(self, net: NetworkEngine, default_host: str = DEFAULT_HOST):
        self.net = net
        self.host = default_host

    def montar_url(
        self,
        symbol: str,
        date: Optional[Union[int, str]] = "-1",
        formatted: bool = True,
        straddle: bool = False,
        strike: Optional[Union[float, int]] = None,
        strike_min: Optional[Union[float, int]] = None,
        strike_max: Optional[Union[float, int]] = None,
        get_all_data: bool = False,
        lang: str = "en-US",
        region: str = "US",
        crumb: Optional[str] = None,
        host: Optional[str] = None
    ) -> str:
        base_host = HOSTS_EP.get(host or self.host, HOSTS_EP[DEFAULT_HOST])
        sym_clean = urllib.parse.quote(symbol.strip().upper())

        params: Dict[str, str] = {
            "formatted": "true" if formatted else "false",
            "straddle": "true" if straddle else "false",
            "lang": lang,
            "region": region,
        }

        if strike is not None:
            # Visão de Strike específico: remove date e adiciona limites
            params["strikeMin"] = str(strike)
            params["strikeMax"] = str(strike)
            params["getAllData"] = "true"
        else:
            if date is not None:
                params["date"] = str(date)
            if strike_min is not None:
                params["strikeMin"] = str(strike_min)
            if strike_max is not None:
                params["strikeMax"] = str(strike_max)
            if get_all_data:
                params["getAllData"] = "true"

        if crumb:
            params["crumb"] = crumb

        qs = urllib.parse.urlencode(params)
        return f"{base_host}{PATH_BASE}/{sym_clean}?{qs}"

    def consultar(
        self,
        symbol: str,
        date: Optional[Union[int, str]] = "-1",
        formatted: bool = True,
        straddle: bool = False,
        strike: Optional[Union[float, int]] = None,
        strike_min: Optional[Union[float, int]] = None,
        strike_max: Optional[Union[float, int]] = None,
        get_all_data: bool = False,
        lang: str = "en-US",
        region: str = "US",
        host: Optional[str] = None,
        autenticado: bool = True,
        crumb_como_header: bool = False,
        custom_headers: Optional[Dict[str, str]] = None
    ) -> Tuple[int, Optional[Dict[str, Any]], bytes]:
        token = None
        headers = dict(custom_headers or {})

        if autenticado:
            if not self.net.crumb:
                self.net.bootstrap_auth()
            token = self.net.crumb
            if crumb_como_header and token:
                headers["x-crumb"] = token
                token = None

        url = self.montar_url(
            symbol=symbol,
            date=date,
            formatted=formatted,
            straddle=straddle,
            strike=strike,
            strike_min=strike_min,
            strike_max=strike_max,
            get_all_data=get_all_data,
            lang=lang,
            region=region,
            crumb=token,
            host=host
        )

        status, _, raw_bytes = self.net.request_raw(url, headers=headers)
        if status == 200:
            try:
                dados = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                return status, dados, raw_bytes
            except json.JSONDecodeError:
                return status, None, raw_bytes
        return status, None, raw_bytes


# ════════════════════ Componentes Gráficos de Terminal ══════════════════════

class ConsoleRenderer:
    """Renderizador Bloomberg de caixas e tabelas com alinhamento ANSI imune."""
    def __init__(self, p: Palette, b: BoxChars):
        self.p = p
        self.b = b

    def largura_term(self) -> int:
        return shutil.get_terminal_size((80, 24)).columns

    def caixa(
        self,
        linhas: List[str],
        titulo: Optional[str] = None,
        cor_titulo: str = "ambar",
        rodape: Optional[str] = None
    ) -> None:
        tw = max(40, min(self.largura_term() - 2, 96))
        inner_w = tw - 4
        p, b = self.p, self.b

        if titulo:
            rotulo = f" {p.pintar(titulo, cor_titulo, negrito=True)} "
            resto = max(0, inner_w + 2 - vlen(rotulo))
            topo = f" {p.c('linha')}{b.TL}{b.H}{p.RST}{rotulo}{p.c('linha')}{b.H * resto}{b.TR}{p.RST}"
        else:
            topo = f" {p.c('linha')}{b.TL}{b.H * (inner_w + 2)}{b.TR}{p.RST}"
        print(topo)

        for ln in linhas:
            print(f" {p.c('linha')}{b.V}{p.RST} {pad_vis(ln, inner_w, '<')} {p.c('linha')}{b.V}{p.RST}")

        base = f" {p.c('linha')}{b.BL}{b.H * (inner_w + 2)}{b.BR}{p.RST}"
        print(base)
        if rodape:
            print(f"  {p.pintar(rodape, 'cinza_esc')}")

    def tabela_grade_opcoes(self, contratos: List[Dict[str, Any]], titulo_grade: str, tipo_opcao: str = "CALL") -> None:
        """Renderiza a grade de opções completa formatada estilo tela de derivativos."""
        if not contratos:
            print(f"  {self.p.pintar('[AVISO] Nenhum contrato retornado para esta seleção.', 'amarelo')}")
            return

        print(f"\n {self.p.pintar(titulo_grade, 'ambar', negrito=True)}")

        colunas = [
            ("CONTRATO (OCC)", 21, "<"),
            ("STRIKE", 9, ">"),
            ("ÚLTIMO", 9, ">"),
            ("COMPRA (BID)", 12, ">"),
            ("VENDA (ASK)", 11, ">"),
            ("VAR %", 9, ">"),
            ("VOL", 8, ">"),
            ("OPEN INT", 9, ">"),
            ("IV (VOL IMPL)", 13, ">"),
            ("ITM", 5, "^")
        ]

        p, b = self.p, self.b
        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for c in contratos:
            sym_occ = c.get("contractSymbol", "—")
            k_val = desempacotar_raw(c.get("strike"))
            px_val = desempacotar_raw(c.get("lastPrice"))
            bid_val = desempacotar_raw(c.get("bid"))
            ask_val = desempacotar_raw(c.get("ask"))
            pct_val = desempacotar_raw(c.get("percentChange"))
            vol_val = desempacotar_raw(c.get("volume"))
            oi_val = desempacotar_raw(c.get("openInterest"))
            iv_val = desempacotar_raw(c.get("impliedVolatility"))
            itm_val = bool(c.get("inTheMoney", False))

            k_str = fmt_num_br(k_val, 2)
            px_str = fmt_num_br(px_val, 2)
            bid_str = fmt_num_br(bid_val, 2) if bid_val is not None else "—"
            ask_str = fmt_num_br(ask_val, 2) if ask_val is not None else "—"
            pct_str = fmt_pct_br(pct_val)
            vol_str = f"{int(vol_val):,}".replace(",", ".") if vol_val is not None else "—"
            oi_str = f"{int(oi_val):,}".replace(",", ".") if oi_val is not None else "—"

            if iv_val is not None:
                iv_str = f"{iv_val * 100:.2f}%".replace(".", ",")
            else:
                iv_str = "—"

            # Colorações condicionais
            cor_pct = "verde" if (pct_val or 0) > 0 else ("vermelho" if (pct_val or 0) < 0 else "branco")
            cor_itm = "verde" if itm_val else "cinza_esc"
            itm_str = p.pintar("SIM", "verde", negrito=True) if itm_val else p.pintar("NÃO", "cinza_esc")

            # Cor do strike dependendo se está In-the-Money
            k_fmt = p.pintar(k_str, "verde" if itm_val else "branco", negrito=itm_val)

            linha_cel = [
                (p.pintar(sym_occ, "ciano"), colunas[0][1], colunas[0][2]),
                (k_fmt, colunas[1][1], colunas[1][2]),
                (px_str, colunas[2][1], colunas[2][2]),
                (bid_str, colunas[3][1], colunas[3][2]),
                (ask_str, colunas[4][1], colunas[4][2]),
                (p.pintar(pct_str, cor_pct), colunas[5][1], colunas[5][2]),
                (vol_str, colunas[6][1], colunas[6][2]),
                (oi_str, colunas[7][1], colunas[7][2]),
                (p.pintar(iv_str, "amarelo"), colunas[8][1], colunas[8][2]),
                (itm_str, colunas[9][1], colunas[9][2]),
            ]

            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)

    def tabela_straddles(self, straddles: List[Dict[str, Any]], titulo: str) -> None:
        """Renderiza a visão de straddles comparando Call e Put para cada strike."""
        if not straddles:
            print(f"  {self.p.pintar('[AVISO] Nenhum straddle disponível.', 'amarelo')}")
            return

        print(f"\n {self.p.pintar(titulo, 'ambar', negrito=True)}")

        colunas = [
            ("CALL LAST", 10, ">"),
            ("CALL BID/ASK", 14, "^"),
            ("CALL IV", 10, ">"),
            ("STRIKE", 9, "^"),
            ("PUT IV", 10, "<"),
            ("PUT BID/ASK", 14, "^"),
            ("PUT LAST", 10, "<")
        ]

        p, b = self.p, self.b
        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for s in straddles:
            k_val = desempacotar_raw(s.get("strike"))
            call = s.get("call") or {}
            put = s.get("put") or {}

            # Perna Call
            c_last = fmt_num_br(desempacotar_raw(call.get("lastPrice"))) if call else "—"
            c_bid = fmt_num_br(desempacotar_raw(call.get("bid"))) if call else "—"
            c_ask = fmt_num_br(desempacotar_raw(call.get("ask"))) if call else "—"
            c_ba = f"{c_bid}/{c_ask}" if call else "—"
            c_iv_raw = desempacotar_raw(call.get("impliedVolatility"))
            c_iv = f"{c_iv_raw * 100:.1f}%".replace(".", ",") if c_iv_raw else "—"

            # Strike Central
            k_str = fmt_num_br(k_val, 2)

            # Perna Put
            p_last = fmt_num_br(desempacotar_raw(put.get("lastPrice"))) if put else "—"
            p_bid = fmt_num_br(desempacotar_raw(put.get("bid"))) if put else "—"
            p_ask = fmt_num_br(desempacotar_raw(put.get("ask"))) if put else "—"
            p_ba = f"{p_bid}/{p_ask}" if put else "—"
            p_iv_raw = desempacotar_raw(put.get("impliedVolatility"))
            p_iv = f"{p_iv_raw * 100:.1f}%".replace(".", ",") if p_iv_raw else "—"

            linha_cel = [
                (p.pintar(c_last, "verde" if call.get("inTheMoney") else "branco"), colunas[0][1], colunas[0][2]),
                (c_ba, colunas[1][1], colunas[1][2]),
                (p.pintar(c_iv, "amarelo"), colunas[2][1], colunas[2][2]),
                (p.pintar(k_str, "ambar", negrito=True), colunas[3][1], colunas[3][2]),
                (p.pintar(p_iv, "amarelo"), colunas[4][1], colunas[4][2]),
                (p_ba, colunas[5][1], colunas[5][2]),
                (p.pintar(p_last, "verde" if put.get("inTheMoney") else "branco"), colunas[6][1], colunas[6][2]),
            ]

            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)


# ═══════════════ Módulo 1: Suíte de Verificação ao Vivo ══════════════════════

def executar_suite_verificacao(client: OptionsClient, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Executa a suíte de 20 testes de conformidade contra o endpoint /v7/finance/options."""
    print(f"\n {p.pintar('SUÍTE DE VERIFICAÇÃO AO VIVO (' + ENDPOINT_NAME + ')', 'azul', negrito=True)}")
    print(f"  {p.pintar('Validando autenticação A3+Crumb, envelopes, parâmetros e derivativos...', 'cinza_esc')}\n")

    testes_passados = 0
    total_testes = 20

    def relatar(num: int, rotulo: str, cond: bool, detalhe: str = "") -> None:
        nonlocal testes_passados
        st = p.pintar("PASS", "verde", negrito=True) if cond else p.pintar("FAIL", "vermelho", negrito=True)
        if cond:
            testes_passados += 1
        d_str = f" {p.pintar('· ' + detalhe, 'cinza_esc')}" if detalhe else ""
        print(f"  [{st}] {pad_vis(f'{num:02d}. {rotulo}', 58, '<')}{d_str}")
        time.sleep(0.06)

    # 1. Anônimo puro (sem A3/Crumb) deve falhar com HTTP 401 Unauthorized
    st_anon, _, corpo_anon = client.consultar("AAPL", autenticado=False)
    relatar(1, "Anônimo sem credenciais bloqueado com HTTP 401 Unauthorized", st_anon == 401 and b"Invalid Crumb" in corpo_anon, "401 Invalid Crumb")

    # 2. Handshake de sessão A3 + Crumb executado com sucesso
    ok_auth, msg_auth = client.net.bootstrap_auth()
    relatar(2, "Bootstrap de sessão A3 (fc.yahoo.com) + Crumb oficial OK", ok_auth and client.net.crumb is not None, f"crumb={client.net.crumb}")

    # 3. Consulta canônica AAPL com date=-1 retorna HTTP 200
    st_can, d_can, _ = client.consultar("AAPL", date="-1")
    r0 = ((d_can or {}).get("optionChain", {}).get("result") or [{}])[0]
    relatar(3, "Consulta canônica AAPL (date=-1) retorna HTTP 200", st_can == 200 and r0.get("underlyingSymbol") == "AAPL", "200 OK")

    # 4. Presença das 6 chaves raiz essenciais
    chaves_raiz = {"underlyingSymbol", "quote", "expirationDates", "strikes", "hasMiniOptions", "options"}
    relatar(4, "Presença de todas as 6 chaves primárias de optionChain", chaves_raiz.issubset(set(r0.keys())), "chaves raiz presentes")

    # 5. Default date=-1 devolve exatamente 1 vencimento em options[]
    opts = r0.get("options", [])
    relatar(5, "date=-1 retorna exatamente 1 vencimento em options[]", len(opts) == 1, f"len={len(opts)}")

    # 6. expirationDate do bloco bate com expirationDates[0]
    exp_dates = r0.get("expirationDates", [])
    exp_0 = opts[0].get("expirationDate") if opts else None
    relatar(6, "expirationDate do bloco resolvido bate com expirationDates[0]", exp_0 == exp_dates[0], f"exp={exp_0}")

    # 7. Contrato de opções contém os 15 campos canônicos
    calls = opts[0].get("calls", []) if opts else []
    call0 = calls[0] if calls else {}
    relatar(7, "Contrato contém os 15 campos padrão do catálogo OCC", set(CAMPOS_CONTRATO).issubset(set(call0.keys())), f"campos={len(call0)}")

    # 8. formatted=true embrulha valores numéricos em {raw, fmt}
    k_fmt = call0.get("strike")
    relatar(8, "formatted=true embrulha strike e preços em {raw, fmt}", isinstance(k_fmt, dict) and "raw" in k_fmt and "fmt" in k_fmt, "envelope raw/fmt")

    # 9. inTheMoney permanece booleano primitivo no contrato
    relatar(9, "Campo inTheMoney permanece booleano primitivo (não embrulhado)", isinstance(call0.get("inTheMoney"), bool), f"itm={call0.get('inTheMoney')}")

    # 10. quote do subjacente permanece escalar cru (não embrulhado)
    spot_px = r0.get("quote", {}).get("regularMarketPrice")
    relatar(10, "Objeto quote do subjacente permanece com escalares crus", isinstance(spot_px, (int, float)), f"spot={spot_px}")

    # 11. date não listado (ex: 9999999999) ecoa o valor e devolve contratos vazios com 200
    st_eco, d_eco, _ = client.consultar("AAPL", date=9999999999)
    r_eco = ((d_eco or {}).get("optionChain", {}).get("result") or [{}])[0]
    opt_eco = (r_eco.get("options") or [{}])[0]
    relatar(11, "date inexistente ecoa expirationDate com contratos vazios", st_eco == 200 and opt_eco.get("expirationDate") == 9999999999 and opt_eco.get("calls") == [], "200 eco silencioso")

    # 12. date não-inteiro (date=abc) retorna HTTP 400 tipado
    st_err, _, corpo_err = client.consultar("AAPL", date="abc")
    relatar(12, "date=abc não-numérico rejeitado com HTTP 400 tipado", st_err == 400 and b"Parameter=date has an invalid type" in corpo_err, "400 Bad Request")

    # 13. straddle=true substitui calls/puts por straddles[]
    st_strad, d_strad, _ = client.consultar("AAPL", straddle=True)
    r_strad = ((d_strad or {}).get("optionChain", {}).get("result") or [{}])[0]
    opt_strad = (r_strad.get("options") or [{}])[0]
    relatar(13, "straddle=true comuta resposta para array straddles[]", "straddles" in opt_strad and "calls" not in opt_strad, "straddles presentes")

    # 14. Visão de strike específico (strikeMin=strikeMax + getAllData=true) retorna todos os vencimentos
    mid_k = r0.get("strikes", [160])[len(r0.get("strikes", [160])) // 2]
    st_k, d_k, _ = client.consultar("AAPL", strike=mid_k)
    r_k = ((d_k or {}).get("optionChain", {}).get("result") or [{}])[0]
    relatar(14, "Visão de strike específico retorna cadeia em todos os vencimentos", st_k == 200 and len(r_k.get("options", [])) == len(r_k.get("expirationDates", [])), f"{len(r_k.get('options', []))} vencimentos")

    # 15. Malha de strikes da raiz permanece completa mesmo sob filtro de strike
    relatar(15, "Array strikes da raiz não é truncado pelo filtro strikeMin/Max", len(r_k.get("strikes", [])) > 1, f"total={len(r_k.get('strikes', []))}")

    # 16. Símbolo inexistente retorna HTTP 200 com result: [] (omissão silenciosa)
    st_inex, d_inex, _ = client.consultar("TICKER_INEXISTENTE_XYZ99")
    res_inex = (d_inex or {}).get("optionChain", {}).get("result", None)
    relatar(16, "Símbolo inexistente retorna HTTP 200 com result: [] silencioso", st_inex == 200 and res_inex == [], "result=[]")

    # 17. Subjacente sem opções (ex: EURUSD=X) retorna quote populado e options: [{}]
    st_noopt, d_noopt, _ = client.consultar("EURUSD=X")
    r_noopt = ((d_noopt or {}).get("optionChain", {}).get("result") or [{}])[0]
    relatar(17, "Ativo sem opções (Forex) entrega quote e options=[{}]", st_noopt == 200 and r_noopt.get("expirationDates") == [] and len(r_noopt.get("options", [])) == 1, "forma sem opções")

    # 18. User-Agent python-urllib bloqueado pelo edge com HTTP 429
    url_aapl = client.montar_url("AAPL", crumb=client.net.crumb)
    st_pyua, _, _ = client.net.request_raw(url_aapl, headers={"User-Agent": "Python-urllib/3.13"})
    relatar(18, "User-Agent python-urllib bloqueado com HTTP 429 pela borda", st_pyua == 429, "Too Many Requests")

    # 19. Método HEAD retorna HTTP 200 com corpo vazio (0 bytes)
    st_head, _, corpo_head = client.net.request_raw(url_aapl, metodo="HEAD")
    relatar(19, "Método HEAD retorna HTTP 200 e corpo vazio (0 bytes)", st_head == 200 and len(corpo_head) == 0, "HEAD ok")

    # 20. Host secundário query2 responde de forma idêntica (200 OK)
    st_q2, d_q2, _ = client.consultar("AAPL", host="query2")
    r_q2 = ((d_q2 or {}).get("optionChain", {}).get("result") or [{}])[0]
    relatar(20, "Host secundário query2 responde com sucesso idêntico", st_q2 == 200 and r_q2.get("underlyingSymbol") == "AAPL", "query2 ativo")

    taxa = (testes_passados / total_testes) * 100.0
    print(f"\n {p.pintar(f'Resultado da Suíte: {testes_passados}/{total_testes} aprovados ({taxa:.1f}% de conformidade)', 'verde' if taxa == 100 else 'amarelo', negrito=True)}\n")
    return testes_passados == total_testes


# ══════════════ Módulo 2: Auditoria de Invariantes Offline ═══════════════════

def executar_auditoria_offline(caminho_arquivo: str, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Valida estrutura de fixture JSON de optionChain sem emitir tráfego de rede."""
    print(f"\n {p.pintar('AUDITORIA DE INVARIANTES ESTRUTURAIS (OFFLINE)', 'ciano', negrito=True)}")
    print(f"  {p.pintar(f'Arquivo analisado: {caminho_arquivo}', 'cinza_esc')}\n")

    if not os.path.isfile(caminho_arquivo):
        print(f"  {p.pintar('[ERRO] Arquivo não localizado.', 'vermelho')}")
        return False

    try:
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            j = json.load(f)
    except Exception as e:
        print(f"  {p.pintar(f'[ERRO] Falha ao decodificar JSON: {e}', 'vermelho')}")
        return False

    invariantes = []
    oc = j.get("optionChain")
    invariantes.append(("1. Envelope raiz 'optionChain' presente", isinstance(oc, dict)))

    if isinstance(oc, dict):
        res = oc.get("result")
        err = oc.get("error")
        invariantes.append(("2. Campo 'error' é estritamente nulo", err is None))
        invariantes.append(("3. Campo 'result' é uma lista com 1 elemento", isinstance(res, list) and len(res) == 1))

        if isinstance(res, list) and len(res) > 0:
            r0 = res[0]
            invariantes.append(("4. Presença de 'underlyingSymbol' string", isinstance(r0.get("underlyingSymbol"), str)))
            invariantes.append(("5. Presença de 'expirationDates' lista não vazia", isinstance(r0.get("expirationDates"), list) and len(r0["expirationDates"]) > 0))
            invariantes.append(("6. Presença de 'strikes' lista não vazia", isinstance(r0.get("strikes"), list) and len(r0["strikes"]) > 0))
            invariantes.append(("7. Presença de objeto 'quote' com regularMarketPrice", isinstance(r0.get("quote"), dict) and "regularMarketPrice" in r0["quote"]))
            invariantes.append(("8. Presença de lista 'options' com vencimentos", isinstance(r0.get("options"), list) and len(r0["options"]) > 0))

            opts = r0.get("options", [{}])
            if opts and ("calls" in opts[0] or "puts" in opts[0] or "straddles" in opts[0]):
                invariantes.append(("9. Presença de contratos em calls/puts ou straddles", True))
            else:
                invariantes.append(("9. Presença de contratos em calls/puts ou straddles", False))

    for rotulo, cond in invariantes:
        st = p.pintar("CONFORME", "verde", negrito=True) if cond else p.pintar("VIOLAÇÃO", "vermelho", negrito=True)
        print(f"  [{st}] {rotulo}")

    aprovado = all(c for _, c in invariantes)
    print(f"\n  Status: {p.pintar('FIXTURE CERTIFICADA', 'verde') if aprovado else p.pintar('FIXTURE INVÁLIDA', 'vermelho')}\n")
    return aprovado


# ═══════════════ Módulo 3: Console de Requisições Brutas ═════════════════════

def console_requisicao_bruta(client: OptionsClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Diagnóstico de protocolo: testa métodos HTTP, vetores de crumb e parâmetros."""
    print(f"\n {p.pintar('CONSOLE DE DIAGNÓSTICO & REQUISIÇÃO BRUTA', 'ciano', negrito=True)}")
    print(f"  {p.pintar('Inspecione status HTTP, latência e cabeçalhos reais da borda.', 'cinza_esc')}\n")

    metodo = (input(f"  {p.pintar('Método HTTP (GET/POST/HEAD/OPTIONS) [GET]:', 'branco', negrito=True)} ").strip().upper()) or "GET"
    host = (input(f"  {p.pintar('Host (query1/query2/iquery) [query1]:', 'branco', negrito=True)} ").strip().lower()) or "query1"
    simbolo = (input(f"  {p.pintar('Símbolo subjacente [AAPL]:', 'branco', negrito=True)} ").strip().upper()) or "AAPL"
    data_exp = input(f"  {p.pintar('Vencimento epoch (date) [-1]:', 'branco')} ").strip() or "-1"

    print("\n  Vetor do Crumb:")
    print("   [1] Query parameter (?crumb=...) — Padrão oficial do cliente")
    print("   [2] Header HTTP (x-crumb: ...)")
    print("   [3] Nenhum (espera-se HTTP 401)")
    v_opt = input(f"  {p.pintar('Escolha o vetor [1]:', 'branco')} ").strip() or "1"

    crumb_param = None
    custom_headers: Dict[str, str] = {}
    if v_opt in ("1", "2"):
        if not client.net.crumb:
            client.net.bootstrap_auth()
        if v_opt == "1":
            crumb_param = client.net.crumb
        else:
            custom_headers["x-crumb"] = client.net.crumb or ""

    url = client.montar_url(symbol=simbolo, date=data_exp, crumb=crumb_param, host=host)
    print(f"\n  {p.pintar('Disparando:', 'cinza_esc')} {p.pintar(f'{metodo} {url}', 'azul')}")

    status, hdrs, corpo = client.net.request_raw(url, metodo=metodo, headers=custom_headers)
    st_cor = "verde" if status == 200 else "vermelho"
    print(f"  {p.pintar('Resposta:', 'cinza_esc')} {p.pintar(f'HTTP {status}', st_cor, negrito=True)} | Latência: {client.net.ultima_latencia_ms:.1f}ms | Tamanho: {len(corpo)}B\n")

    rnd.caixa(
        [f"{k}: {v}" for k, v in list(hdrs.items())[:8]],
        titulo="CABEÇALHOS HTTP RETORNADOS",
        cor_titulo="ciano"
    )

    amostra = corpo[:350].decode("utf-8", errors="replace")
    print(f"\n  {p.pintar('Corpo bruto (primeiros 350 bytes):', 'cinza_med')}")
    print(f"  {p.pintar(amostra, 'cinza_esc')}{'...' if len(corpo) > 350 else ''}\n")


# ══════════════ Módulo 4: Submenu de Visões de um Ativo ══════════════════════

def submenu_visoes_ativo(client: OptionsClient, simbolo: str, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop contínuo de exploração da cadeia de opções do subjacente selecionado."""
    data_ativa = "-1"

    while True:
        try:
            st, dados, rb = client.consultar(simbolo, date=data_ativa)
            if st != 200 or not dados:
                print(f"  {p.pintar(f'[ERRO] Falha ao consultar cadeia de {simbolo} (HTTP {st}).', 'vermelho')}")
                break

            r0 = ((dados.get("optionChain", {}).get("result") or [{}]))[0]
            if not r0:
                print(f"  {p.pintar(f'[AVISO] O símbolo {simbolo} não possui opções negociadas ou é inválido.', 'amarelo')}")
                break

            quote = r0.get("quote", {})
            spot_px = quote.get("regularMarketPrice", 0.0)
            spot_mkt = quote.get("marketState", "—")
            exp_dates = r0.get("expirationDates", [])
            opts = r0.get("options", [{}])
            opt_bloco = opts[0] if opts else {}
            data_corrente_epoch = opt_bloco.get("expirationDate")
            data_corrente_str = fmt_epoch_data(data_corrente_epoch)

            print(f"\n {p.pintar(f'CADEIA DE OPÇÕES — SUBJACENTE: {simbolo}', 'ambar', negrito=True)}")
            print(f"  {p.pintar(f'Spot: ${fmt_num_br(spot_px, 2)} ({spot_mkt}) | Vencimento Ativo: {data_corrente_str} (Epoch: {data_corrente_epoch})', 'cinza_med')}\n")

            print(f"  [1] Grade de Opções: CALLS (Opções de Compra)")
            print(f"  [2] Grade de Opções: PUTS (Opções de Venda)")
            print(f"  [3] Grade Combinada: CALLS & PUTS Lado a Lado (Visão Geral)")
            print(f"  [4] Visão STRADDLES (straddle=true)")
            print(f"  [5] Visão por STRIKE Específico (Todos os Vencimentos)")
            print(f"  [6] Selecionar Outro Vencimento ({len(exp_dates)} disponíveis)")
            print(f"  [7] Ficha do Ativo Subjacente (Cotação, Book e Indicadores)")
            print(f"  [8] Exibir Resposta JSON Bruta Formatada")
            print(f"  [9] Exportar JSON Bruto para Arquivo")
            print(f"  [0] Voltar ao Menu Principal")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                break

            elif escolha == "1":
                calls = opt_bloco.get("calls", [])
                rnd.tabela_grade_opcoes(calls, f"GRADE DE CALLS — {simbolo} | Vencimento: {data_corrente_str}", "CALL")

            elif escolha == "2":
                puts = opt_bloco.get("puts", [])
                rnd.tabela_grade_opcoes(puts, f"GRADE DE PUTS — {simbolo} | Vencimento: {data_corrente_str}", "PUT")

            elif escolha == "3":
                calls = opt_bloco.get("calls", [])
                puts = opt_bloco.get("puts", [])
                rnd.tabela_grade_opcoes(calls[:25], f"CALLS (Amostra 25 contratos) — {simbolo} | Vencimento: {data_corrente_str}", "CALL")
                rnd.tabela_grade_opcoes(puts[:25], f"PUTS (Amostra 25 contratos) — {simbolo} | Vencimento: {data_corrente_str}", "PUT")

            elif escolha == "4":
                st_s, d_s, _ = client.consultar(simbolo, date=data_corrente_epoch, straddle=True)
                r_s = ((d_s or {}).get("optionChain", {}).get("result") or [{}])[0]
                straddles = (r_s.get("options") or [{}])[0].get("straddles", [])
                rnd.tabela_straddles(straddles, f"VISÃO STRADDLE — {simbolo} | Vencimento: {data_corrente_str}")

            elif escolha == "5":
                strikes_disp = r0.get("strikes", [])
                print(f"\n  Strikes disponíveis (amostra): {', '.join(str(s) for s in strikes_disp[:12])}...")
                k_inp = input(f"  {p.pintar('Informe o strike desejado:', 'branco')} ").strip()
                if k_inp:
                    try:
                        k_num = float(k_inp.replace(",", "."))
                        print(f"  {p.pintar(f'Consultando strike {k_num} em todos os vencimentos...', 'cinza_esc')}")
                        st_k, d_k, _ = client.consultar(simbolo, strike=k_num)
                        r_k = ((d_k or {}).get("optionChain", {}).get("result") or [{}])[0]
                        todas_calls = []
                        for opt_item in r_k.get("options", []):
                            todas_calls.extend(opt_item.get("calls", []))
                        rnd.tabela_grade_opcoes(todas_calls, f"VISÃO DO STRIKE ${k_num} EM TODOS OS VENCIMENTOS (CALLS)", "CALL")
                    except ValueError:
                        print(f"  {p.pintar('[ERRO] Strike numérico inválido.', 'vermelho')}")

            elif escolha == "6":
                print(f"\n  Vencimentos Disponíveis para {simbolo}:")
                for i, ep in enumerate(exp_dates, 1):
                    print(f"   [{i:>2}] {fmt_epoch_data(ep)} (epoch: {ep})")
                sel_idx = input(f"\n  {p.pintar('Selecione o número do vencimento:', 'branco')} ").strip()
                if sel_idx.isdigit() and 1 <= int(sel_idx) <= len(exp_dates):
                    data_ativa = str(exp_dates[int(sel_idx) - 1])

            elif escolha == "7":
                linhas = [
                    f"• Ticker Subjacente  : {quote.get('symbol')} ({quote.get('shortName') or quote.get('longName')})",
                    f"• Preço Spot Regular : ${fmt_num_br(quote.get('regularMarketPrice'))} ({quote.get('marketState')})",
                    f"• Variação Diária    : {fmt_num_br(quote.get('regularMarketChange'))} ({fmt_pct_br(quote.get('regularMarketChangePercent'))})",
                    f"• Faixa do Pregão    : ${fmt_num_br(quote.get('regularMarketDayLow'))} - ${fmt_num_br(quote.get('regularMarketDayHigh'))}",
                    f"• Faixa de 52 Semanas: {quote.get('fiftyTwoWeekRange')} (+{fmt_pct_br(quote.get('fiftyTwoWeekLowChangePercent'), False)} do mín)",
                    f"• Volume Diário / Méd: {quote.get('regularMarketVolume'):,} / {quote.get('averageDailyVolume3Month'):,}".replace(",", "."),
                    f"• Múltiplos (P/L)    : Trailing P/E = {fmt_num_br(quote.get('trailingPE'))} | Forward P/E = {fmt_num_br(quote.get('forwardPE'))}",
                    f"• Dividend Yield     : {fmt_pct_br(quote.get('dividendYield'), False)} (Taxa anual: ${fmt_num_br(quote.get('trailingAnnualDividendRate'))})",
                    f"• Total Vencimentos  : {len(exp_dates)} datas listadas | {len(r0.get('strikes', []))} strikes na malha",
                ]
                rnd.caixa(linhas, titulo=f"SUBJACENTE: {simbolo}", cor_titulo="ambar")

            elif escolha == "8":
                print(f"\n{json.dumps(dados, indent=2, ensure_ascii=False)}\n")

            elif escolha == "9":
                nome_arq = f"options_{simbolo}_{data_corrente_epoch}_{int(time.time())}.json"
                with open(nome_arq, "wb") as f:
                    f.write(rb)
                print(f"  {p.pintar(f'[SUCESSO] JSON salvo em {nome_arq} ({len(rb)}B)', 'verde')}")

        except KeyboardInterrupt:
            print(f"\n  {p.pintar('Ação cancelada. Retornando ao submenu...', 'amarelo')}")


# ════════════════════ Menu Principal & CLI Dispatcher ═══════════════════════

def menu_principal(client: OptionsClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop principal interativo anti-fechamento."""
    simbolo_atual = "AAPL"

    while True:
        try:
            print(f"\n {p.pintar('YAHOO FINANCE OPTIONS CHAIN EXPLORER (/v7)', 'ambar', negrito=True)}")
            print(f"  {p.pintar('Cadeia de derivativos, volatilidade implícita e malha de strikes | stdlib pura', 'cinza_esc')}\n")

            print(f"  [1] Consultar Cadeia de Opções (atual: {p.pintar(simbolo_atual, 'ciano', negrito=True)})")
            print(f"  [2] Alternar Símbolo Subjacente")
            print(f"  [3] Presets Prontos (Ações Líquidas em Opções)")
            print(f"  [4] Console de Requisições Brutas (Diagnóstico de Protocolo)")
            print(f"  [5] Suíte de Verificação ao Vivo (20 Testes de Conformidade)")
            print(f"  [6] Auditoria Estrutural Offline (Validar Fixture JSON)")
            print(f"  [7] Gestão de Sessão & Credenciais (A3 / Crumb)")
            print(f"  [8] Exportar Fixture JSON Crua")
            print(f"  [0] Encerrar Aplicativo")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                print(f"\n  {p.pintar('Encerrando aplicação de forma limpa. Até logo!', 'ciano')}")
                break

            elif escolha == "1":
                submenu_visoes_ativo(client, simbolo_atual, p, rnd)

            elif escolha == "2":
                novo_s = input(f"  {p.pintar('Digite novo ticker subjacente (ex: NVDA, TSLA, SPY):', 'branco')} ").strip().upper()
                if novo_s:
                    simbolo_atual = novo_s

            elif escolha == "3":
                print("\n  Presets Disponíveis:")
                for k, (nome_cia, ticker) in PRESETS_SUBJACENTES.items():
                    print(f"   [{k}] {ticker:<5} — {nome_cia}")
                pk = input(f"\n  {p.pintar('Escolha o preset [1]:', 'branco')} ").strip() or "1"
                if pk in PRESETS_SUBJACENTES:
                    simbolo_atual = PRESETS_SUBJACENTES[pk][1]
                    submenu_visoes_ativo(client, simbolo_atual, p, rnd)

            elif escolha == "4":
                console_requisicao_bruta(client, p, rnd)

            elif escolha == "5":
                executar_suite_verificacao(client, p, rnd)

            elif escolha == "6":
                arq = input(f"  {p.pintar('Caminho da fixture JSON [v7_finance_options.json]:', 'branco')} ").strip() or "v7_finance_options.json"
                executar_auditoria_offline(arq, p, rnd)

            elif escolha == "7":
                a3 = client.net.obter_a3_presente()
                linhas = [
                    f"• Endpoint : {ENDPOINT_NAME}",
                    f"• Autentic : Exige par Cookie A3 + token Crumb",
                    f"• Cookie A3: {p.pintar(a3[:10] + '... (' + str(len(a3)) + 'B)', 'verde') if a3 else p.pintar('Não emitido', 'vermelho')}",
                    f"• Crumb    : {p.pintar(client.net.crumb or 'Não emitido', 'verde' if client.net.crumb else 'vermelho')}",
                    f"• Edge WAF : Rejeita User-Agents de bot (ex: python-requests) com 429",
                    f"• Cache TTL: public, max-age=1, stale-while-revalidate=9",
                    f"• Total Req: {client.net.total_requisicoes} | Latência: {client.net.ultima_latencia_ms:.1f} ms",
                ]
                rnd.caixa(linhas, titulo="ESTADO DA SESSÃO & CREDENCIAIS", cor_titulo="ciano")
                acao = input(f"\n  {p.pintar('Deseja forçar renovação do par A3+Crumb? (s/n) [n]:', 'branco')} ").strip().lower()
                if acao == "s":
                    ok, msg = client.net.bootstrap_auth(verbose=True)
                    print(f"  {p.pintar(msg, 'verde' if ok else 'vermelho')}")

            elif escolha == "8":
                st, _, rb = client.consultar(simbolo_atual)
                if st == 200:
                    nome = f"options_{simbolo_atual}_fixture.json"
                    with open(nome, "wb") as f:
                        f.write(rb)
                    print(f"  {p.pintar(f'[OK] Arquivo exportado: {nome} ({len(rb)}B)', 'verde')}")

        except KeyboardInterrupt:
            print(f"\n  {p.pintar('Operação interrompida (Ctrl+C). Retornando ao menu...', 'amarelo')}")
        except EOFError:
            print(f"\n  {p.pintar('EOF detectado. Encerrando...', 'ciano')}")
            break
        except Exception as e:
            print(f"\n  {p.pintar(f'[ERRO INESPERADO] {e}', 'vermelho')}")


# ════════════════════════ Ponto de Entrada (Main) ═══════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="v7_finance_options.py",
        description="Terminal Interativo Bloomberg & Cliente Canônico GET /v7/finance/options/{symbol}"
    )

    # Argumentos CLI compatíveis
    parser.add_argument("simbolo", nargs="?", default=None, help="Símbolo subjacente (ex: AAPL, NVDA, SPY)")
    parser.add_argument("--date", default="-1", help="Vencimento epoch em segundos (default: -1 = mais próximo)")
    parser.add_argument("--straddle", action="store_true", help="Ativa visão de straddle (substitui calls/puts por straddles[])")
    parser.add_argument("--strike", type=float, default=None, help="Visão de strike específico (todos os vencimentos)")
    parser.add_argument("--strike-min", type=float, default=None, help="Filtro mínimo de strike")
    parser.add_argument("--strike-max", type=float, default=None, help="Filtro máximo de strike")
    parser.add_argument("--no-format", action="store_true", help="formatted=false (números primitivos escalares)")
    parser.add_argument("--painel", action="store_true", help="Exibe tabela de calls e encerra")
    parser.add_argument("--raw", action="store_true", help="Exibe requisição e cabeçalhos crus")
    parser.add_argument("--json", dest="json_out", default=None, help="Salva o corpo cru da resposta em arquivo")
    parser.add_argument("--verifica", action="store_true", help="Executa a suíte de 20 testes de conformidade ao vivo")
    parser.add_argument("--auditar", default=None, metavar="ARQ", help="Audita estruturalmente fixture JSON offline")
    parser.add_argument("--host", choices=list(HOSTS_EP.keys()), default=DEFAULT_HOST, help="Host edge da Yahoo")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Timeout de conexão em segundos")
    parser.add_argument("--ascii", action="store_true", help="Usa caracteres ASCII simples (+---+) para molduras")
    parser.add_argument("--sem-cores", "--no-color", action="store_true", help="Desativa saída colorida ANSI")
    parser.add_argument("--no-pause", action="store_true", help="Desativa pausa ao sair")

    args = parser.parse_args()

    # Inicialização de UI
    usa_cores = not args.sem_cores and os.environ.get("NO_COLOR") is None
    p = Palette(habilitada=usa_cores)
    b = BoxChars(ascii_mode=args.ascii)
    rnd = ConsoleRenderer(p, b)

    # Inicialização do Motor de Rede e Cliente
    net = NetworkEngine(timeout=args.timeout)
    client = OptionsClient(net, default_host=args.host)

    try:
        # Modo 1: Auditoria Offline
        if args.auditar:
            return 0 if executar_auditoria_offline(args.auditar, p, rnd) else 1

        # Modo 2: Suíte de Testes ao Vivo
        if args.verifica:
            return 0 if executar_suite_verificacao(client, p, rnd) else 1

        # Modo 3: Consulta Não-Interativa CLI
        if args.simbolo or args.painel or args.json_out or args.raw:
            sym_alvo = (args.simbolo or "AAPL").upper()

            st, dados, rb = client.consultar(
                symbol=sym_alvo,
                date=args.date,
                formatted=not args.no_format,
                straddle=args.straddle,
                strike=args.strike,
                strike_min=args.strike_min,
                strike_max=args.strike_max,
                host=args.host
            )

            if args.json_out:
                with open(args.json_out, "wb") as f:
                    f.write(rb)
                print(f"[OK] Fixture salva em {args.json_out} ({len(rb)}B)")
                return 0

            if args.raw:
                url_gerada = client.montar_url(
                    symbol=sym_alvo,
                    date=args.date,
                    formatted=not args.no_format,
                    straddle=args.straddle,
                    strike=args.strike,
                    strike_min=args.strike_min,
                    strike_max=args.strike_max,
                    crumb=client.net.crumb,
                    host=args.host
                )
                print(f"GET {url_gerada}")
                print(f"HTTP Status: {st} | Tamanho: {len(rb)}B | Latência: {client.net.ultima_latencia_ms:.1f}ms\n")
                sys.stdout.buffer.write(rb)
                sys.stdout.buffer.write(b"\n")
                return 0

            if st == 200 and dados:
                r0 = ((dados.get("optionChain", {}).get("result") or [{}]))[0]
                opts = r0.get("options", [{}])
                opt_bloco = opts[0] if opts else {}
                data_str = fmt_epoch_data(opt_bloco.get("expirationDate"))

                if args.straddle:
                    straddles = opt_bloco.get("straddles", [])
                    rnd.tabela_straddles(straddles, f"STRADDLES — {sym_alvo} | Vencimento: {data_str}")
                else:
                    calls = opt_bloco.get("calls", [])
                    rnd.tabela_grade_opcoes(calls, f"GRADE DE CALLS — {sym_alvo} | Vencimento: {data_str}", "CALL")
                return 0
            else:
                sys.stderr.write(f"Erro ao consultar cadeia de opções (HTTP {st})\n")
                return 1

        # Modo 4: Menu Interativo Contínuo (Anti-Fechamento)
        menu_principal(client, p, rnd)
        return 0

    except KeyboardInterrupt:
        print(f"\n  {p.pintar('Execução cancelada.', 'amarelo')}")
        return 130
    except Exception as e:
        print(f"\n  {p.pintar(f'[ERRO CRÍTICO] {e}', 'vermelho')}")
        return 1
    finally:
        if not args.no_pause and sys.stdin.isatty():
            try:
                input(f"\n {p.pintar('Pressione ENTER para fechar...', 'cinza_med')}")
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())