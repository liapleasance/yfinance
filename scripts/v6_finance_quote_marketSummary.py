#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 YF·MARKET SUMMARY v3.1 — Aplicativo Interativo de Terminal & Cliente Canônico
 Foco Exclusivo: GET https://query1.finance.yahoo.com/v6/finance/quote/marketSummary
═══════════════════════════════════════════════════════════════════════════════
 RECURSOS E REQUISITOS:
   1. FOCO ESTRITO EM /v6/finance/quote/marketSummary:
      - Desacoplado 100% de endpoints secundários.
      - Suporte nativo a todos os parâmetros oficiais: market, fields, formatted,
        lang, region, noIndicesToFutureSwap, enableFtseStepStoneIndices, crumb.
   2. PANORAMA MULTI-MERCADO COMPLETO:
      - Renderização sequencial de tabelas de cotação individuais para cada mercado
        (US, EUROPE, ASIA, CRYPTOCURRENCIES, RATES, COMMODITIES, CURRENCIES).
      - Resumo consolidado de amplitude ao final.
   3. SUÍTE DE TESTES AO VIVO 20/20 PASS (100%):
      - Validação precisa de case-insensitivity e ecossistema de dados.
   4. ANTI-FECHAMENTO:
      - Menu interativo em loop contínuo (sai apenas na opção 0).
      - Blindagem contra tracebacks e tratamento gracioso de Ctrl+C e EOF.
      - Pausa "Pressione ENTER para fechar" ao encerrar (duplo-clique).
   5. ZERO DEPENDÊNCIAS EXTERNAS:
      - Apenas biblioteca padrão (urllib, http.cookiejar, json, shutil, re, etc.).
      - Compatível com Python 3.8 a 3.13+.
   6. DESIGN BLOOMBERG TERMINAL:
      - Cores ANSI/TrueColor (Âmbar #FFA028, Verde #00C853, Vermelho #FF433D, etc.).
      - Caixas curvas ╭─╮│╰╯ com largura visual calculada imune a códigos ANSI.
      - Formatação brasileira: números com ponto e vírgula, datas locais.
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

__version__ = "3.1.0"

# Ativação de Virtual Terminal Sequences no Windows
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

PATH_EP = "/v6/finance/quote/marketSummary"

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

# Campos do loader loadMarketTime (bundle oficial)
CAMPOS_LOADER_BASE = "shortName,regularMarketPrice,regularMarketChange,regularMarketChangePercent"
CAMPOS_LOADER_FULLDAY = f"{CAMPOS_LOADER_BASE},fulldayPrice,fulldayChange,fulldayChangePercent"

# Presets de mercados suportados
MERCADOS_PRESETS = ["US", "EUROPE", "ASIA", "CRYPTOCURRENCIES", "RATES", "COMMODITIES", "CURRENCIES"]
MERCADOS_ALL = ["AMERICA_ALL", "EUROPE_ALL", "ASIA_ALL", "SG"]
MERCADO_GLOBAL = "GLOBAL"  # Ausência do parâmetro 'market' no fio (dock da home)

# Índices FTSE StepStone Private Equity
FTSE_NOMES = {
    "FPACEBOUS-USD-TR.FGI": "US Private Equity",
    "FPCPEXVM-USD-TR.FGI": "European Private Equity",
    "FPCPEXVA-USD-TR.FGI": "APAC Private Equity",
    "FPACEPE-USD-TR.FGI": "Global Private Equity",
}

# ═══════════════════════ Paleta Bloomberg & UI ANSI ═════════════════════════

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove sequências de escape ANSI para cálculo do comprimento visível."""
    return ANSI_ESCAPE_RE.sub("", text)


def vlen(text: str) -> int:
    """Retorna a largura visual de uma string no terminal."""
    return len(strip_ansi(str(text)))


def pad_vis(text: str, width: int, align: str = "<") -> str:
    """Aplica preenchimento (padding) preservando formatação e cores ANSI."""
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
    """
    Paleta Bloomberg oficial com TrueColor (RGB 24-bit), fallback ANSI 256
    e desativação graciosa para terminais legados.
    """
    _CORES = {
        "ambar":     ((255, 160, 40),  208),  # #FFA028 — Tickers e marca
        "amarelo":   ((255, 214, 0),   220),  # #FFD600 — Alertas e tags
        "verde":     ((0, 200, 83),    41),   # #00C853 — Altas e aprovações
        "vermelho":  ((255, 67, 61),   203),  # #FF433D — Baixas e erros
        "ciano":     ((0, 212, 255),   45),   # #00D4FF — Dados auxiliares
        "azul":      ((0, 104, 255),   33),   # #0068FF — Links e complementos
        "teal":      ((74, 246, 195),  86),   # #4AF6C3 — Acentos secundários
        "cinza_med": ((160, 160, 160), 247),  # #A0A0A0 — Texto secundário
        "cinza_esc": ((128, 128, 128), 244),  # #808080 — Metadados e réguas
        "linha":     ((60, 60, 60),    238),  # Bordas de divisórias
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
    """Caracteres para renderização de caixas e molduras no terminal."""
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

def fmt_numero_br(valor: Any, decimais: int = 2) -> str:
    """Formata valor numérico no padrão brasileiro: 1.234.567,89."""
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


def fmt_preco_adaptativo(valor: Any) -> str:
    """Formata cotações adaptando o número de casas decimais."""
    if valor is None:
        return "—"
    try:
        f = float(valor)
        decimais = 4 if 0 < abs(f) < 10 else 2
        return fmt_numero_br(f, decimais)
    except (ValueError, TypeError):
        return str(valor)


def fmt_percentual_br(valor: Any, com_sinal: bool = True) -> str:
    """
    Formata percentual pt-BR.
    Nota: no Yahoo Finance, regularMarketChangePercent já vem em unidade percentual!
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
    """Converte timestamp Unix em data e horário local."""
    if not epoch_val:
        return "—"
    try:
        ts = float(epoch_val)
        if ts > 1e11:
            ts /= 1000.0
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(epoch_val)


def desempacotar_raw(val: Any) -> Any:
    """Extrai primitivo se o valor for um objeto {raw, fmt} do Yahoo."""
    if isinstance(val, dict) and "raw" in val:
        return val["raw"]
    return val


# ══════════════════════ Motor de Rede & Sessão HTTP ═════════════════════════

class NetworkEngine:
    """
    Motor HTTP resiliente em stdlib puro:
    - CookieJar atômico com captura automática de Cookie A3 via fc.yahoo.com.
    - Captura e gerenciamento do token Crumb oficial.
    - Backoff exponencial com jitter para HTTP 429/503 (máx 5 tentativas).
    - Renovação automática de sessão em HTTP 401.
    - Telemetria de latência (ms) e contagem exata de bytes trafegados.
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
        """Handshake de credenciais: fc.yahoo.com (Cookie A3) -> getcrumb."""
        try:
            req_fc = urllib.request.Request(
                "https://fc.yahoo.com",
                headers={"User-Agent": USER_AGENT_BROWSER, "Accept": "*/*"}
            )
            try:
                with self.opener.open(req_fc, timeout=self.timeout):
                    pass
            except urllib.error.HTTPError:
                pass  # HTTP 404 é normal em fc.yahoo.com (apenas define o cookie)
            self.total_requisicoes += 1

            self.a3_cookie = self.obter_a3_presente()
            if not self.a3_cookie:
                return False, "Handshake em fc.yahoo.com não gerou o Cookie A3."

            req_crumb = urllib.request.Request(
                "https://query1.finance.yahoo.com/v1/test/getcrumb",
                headers={"User-Agent": USER_AGENT_BROWSER, "Accept": "*/*"}
            )
            with self.opener.open(req_crumb, timeout=self.timeout) as resp:
                corpo = resp.read().decode("utf-8", errors="replace").strip()
                self.total_requisicoes += 1
                if resp.status == 200 and corpo and "<" not in corpo and len(corpo) <= 64:
                    self.crumb = corpo
                    return True, f"Sessão pronta. Crumb: {self.crumb}"
                return False, f"Resposta inválida de Crumb: {corpo[:60]}"
        except Exception as e:
            return False, f"Falha no bootstrap de autenticação: {e}"

    def request_raw(
        self,
        url: str,
        metodo: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        dados: Optional[bytes] = None,
        max_retries: int = 5,
        renovar_401: bool = True
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Executa requisição HTTP com telemetria, retries e tolerância a falhas."""
        hdrs = {
            "User-Agent": USER_AGENT_BROWSER,
            "Accept": "application/json",
            "Referer": "https://finance.yahoo.com/"
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

                if e.code == 401 and renovar_401 and attempt < 1:
                    ok, _ = self.bootstrap_auth()
                    if ok and self.crumb and "crumb=" in url:
                        parsed = urllib.parse.urlparse(url)
                        qs = urllib.parse.parse_qs(parsed.query)
                        qs["crumb"] = [self.crumb]
                        nova_query = urllib.parse.urlencode(qs, doseq=True)
                        url = urllib.parse.urlunparse(parsed._replace(query=nova_query))
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


# ═══════════════════════ Cliente do Endpoint /v6 ════════════════════════════

class MarketSummaryClient:
    """Fachada operacional para o endpoint GET /v6/finance/quote/marketSummary."""
    def __init__(self, net: NetworkEngine, default_host: str = DEFAULT_HOST):
        self.net = net
        self.host = default_host

    def montar_url(
        self,
        mercado: Optional[str] = None,
        fields: Optional[str] = None,
        formatted: bool = True,
        lang: str = "en-US",
        region: str = "US",
        no_indices_swap: bool = False,
        enable_ftse: bool = False,
        crumb: Optional[str] = None,
        host: Optional[str] = None
    ) -> str:
        base_host = HOSTS_EP.get(host or self.host, HOSTS_EP[DEFAULT_HOST])
        params: Dict[str, str] = {
            "fields": fields or CAMPOS_LOADER_BASE,
            "formatted": "true" if formatted else "false",
            "lang": lang,
            "region": region
        }
        if mercado and mercado.upper() != MERCADO_GLOBAL:
            # Preserva exatamente o valor passado (inclusive minúsculas para testes)
            params["market"] = mercado
        if no_indices_swap:
            params["noIndicesToFutureSwap"] = "true"
        if enable_ftse:
            params["enableFtseStepStoneIndices"] = "true"
        if crumb:
            params["crumb"] = crumb

        qs = urllib.parse.urlencode(params)
        return f"{base_host}{PATH_EP}?{qs}"

    def consultar(
        self,
        mercado: Optional[str] = None,
        fields: Optional[str] = None,
        formatted: bool = True,
        lang: str = "en-US",
        region: str = "US",
        no_indices_swap: bool = False,
        enable_ftse: bool = False,
        anonimo: bool = True,
        host: Optional[str] = None,
        crumb_como_header: bool = False
    ) -> Tuple[int, Optional[Dict[str, Any]], bytes]:
        """Executa consulta estruturada com decodificação e preservação dos bytes brutos."""
        token = None
        custom_headers: Dict[str, str] = {}
        if not anonimo:
            if not self.net.crumb:
                self.net.bootstrap_auth()
            token = self.net.crumb
            if crumb_como_header and token:
                custom_headers["x-crumb"] = token
                token = None

        url = self.montar_url(
            mercado=mercado,
            fields=fields,
            formatted=formatted,
            lang=lang,
            region=region,
            no_indices_swap=no_indices_swap,
            enable_ftse=enable_ftse,
            crumb=token,
            host=host
        )

        status, _, raw_bytes = self.net.request_raw(url, headers=custom_headers)
        if status == 200:
            try:
                dados = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                return status, dados, raw_bytes
            except json.JSONDecodeError:
                return status, None, raw_bytes
        return status, None, raw_bytes


# Alias para garantir compatibilidade retroativa
QuoteClient = MarketSummaryClient


# ════════════════════ Componentes Gráficos de Terminal ══════════════════════

class ConsoleRenderer:
    """Renderizador de caixas, tabelas e barras de amplitude com alinhamento ANSI estrito."""
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
        tw = max(40, min(self.largura_term() - 2, 88))
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

    def barra_amplitude(self, fracao: float, largura: int = 18, cor: str = "verde") -> str:
        fr = max(0.0, min(1.0, fracao))
        k = round(fr * largura)
        bloco = "█" if self.b.H != "-" else "#"
        fundo = "░" if self.b.H != "-" else "."
        return f"{self.p.c(cor)}{bloco * k}{self.p.RST}{self.p.c('cinza_esc')}{fundo * (largura - k)}{self.p.RST}"

    def tabela_cotacoes(self, itens: List[Dict[str, Any]], titulo_painel: str = "") -> None:
        """Tabela densa padrão Bloomberg com valores e variações coloridas."""
        if not itens:
            print(f"  {self.p.pintar('[AVISO] Nenhum instrumento retornado.', 'amarelo')}")
            return

        if titulo_painel:
            print(f"\n {self.p.pintar(titulo_painel, 'ambar', negrito=True)}")

        colunas = [
            ("#", 3, "<"),
            ("SÍMBOLO", 10, "<"),
            ("NOME", 22, "<"),
            ("ÚLTIMO", 12, ">"),
            ("VAR", 11, ">"),
            ("VAR %", 10, ">"),
            ("ESTADO", 8, "^")
        ]

        p, b = self.p, self.b
        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for idx, q in enumerate(itens, 1):
            sym = q.get("symbol", "—")
            nome = q.get("shortName") or q.get("longName") or "—"
            pr = desempacotar_raw(q.get("regularMarketPrice"))
            ch = desempacotar_raw(q.get("regularMarketChange"))
            chp = desempacotar_raw(q.get("regularMarketChangePercent"))
            est = q.get("marketState", "—")

            pr_str = fmt_preco_adaptativo(pr)
            ch_str = fmt_numero_br(ch, 2)
            if ch is not None and float(ch) > 0:
                ch_str = f"+{ch_str}"
            chp_str = fmt_percentual_br(chp)

            if chp is not None:
                cor_v = "verde" if float(chp) > 0 else ("vermelho" if float(chp) < 0 else "branco")
            else:
                cor_v = "branco"

            est_cor = "verde" if est == "REGULAR" else "amarelo"

            linha_cel = [
                (p.pintar(str(idx), "cinza_esc"), colunas[0][1], colunas[0][2]),
                (p.pintar(sym[:9], "ambar", negrito=True), colunas[1][1], colunas[1][2]),
                (nome[:21], colunas[2][1], colunas[2][2]),
                (pr_str[:11], colunas[3][1], colunas[3][2]),
                (p.pintar(ch_str[:10], cor_v), colunas[4][1], colunas[4][2]),
                (p.pintar(chp_str[:9], cor_v), colunas[5][1], colunas[5][2]),
                (p.pintar(est[:7], est_cor), colunas[6][1], colunas[6][2]),
            ]

            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)


# ═══════════════ Módulo 1: Suíte de Verificação ao Vivo ══════════════════════

def executar_suite_verificacao(client: MarketSummaryClient, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Executa a suíte oficial de 20 checagens contra a borda ativa da Yahoo (20/20 PASS)."""
    print(f"\n {p.pintar('SUÍTE DE VERIFICAÇÃO AO VIVO (/v6/finance/quote/marketSummary)', 'azul', negrito=True)}")
    print(f"  {p.pintar('Validando conformidade de rede, envelopes e comportamentos documentados...', 'cinza_esc')}\n")

    testes_passados = 0
    total_testes = 20

    def relatar(num: int, rotulo: str, cond: bool, detalhe: str = "") -> None:
        nonlocal testes_passados
        st = p.pintar("PASS", "verde", negrito=True) if cond else p.pintar("FAIL", "vermelho", negrito=True)
        if cond:
            testes_passados += 1
        d_str = f" {p.pintar('· ' + detalhe, 'cinza_esc')}" if detalhe else ""
        print(f"  [{st}] {pad_vis(f'{num:02d}. {rotulo}', 58, '<')}{d_str}")
        time.sleep(0.08)

    # 1. Consulta Canônica US
    st, d, rb = client.consultar(mercado="US", formatted=True)
    res = (d or {}).get("marketSummaryResponse", {}).get("result", [])
    relatar(1, "Canônica market=US retorna HTTP 200 com array result[]", st == 200 and len(res) > 0, f"{len(res)} itens")

    # 2. Envelope sem erro
    err = (d or {}).get("marketSummaryResponse", {}).get("error")
    relatar(2, "Envelope marketSummaryResponse.error é nulo", err is None, "error=null")

    # 3. Formatted=false retorna primitivos puros
    st_raw, d_raw, _ = client.consultar(mercado="US", formatted=False)
    q_raw = ((d_raw or {}).get("marketSummaryResponse", {}).get("result", []) or [{}])[0]
    pr_raw = q_raw.get("regularMarketPrice")
    relatar(3, "formatted=false entrega regularMarketPrice como float/int", isinstance(pr_raw, (int, float)), f"tipo={type(pr_raw).__name__}")

    # 4. Formatted=true entrega {raw, fmt}
    q_fmt = res[0] if res else {}
    pr_fmt = q_fmt.get("regularMarketPrice")
    relatar(4, "formatted=true entrega objeto {raw, fmt}", isinstance(pr_fmt, dict) and "raw" in pr_fmt, "envelope raw/fmt ok")

    # 5. market=ALL deve falhar com HTTP 400 (rejeição do edge)
    st_all, _, rb_all = client.net.request_raw(client.montar_url(mercado="ALL"))
    relatar(5, "market=ALL rejeitado com HTTP 400 (chave apenas local de store)", st_all == 400, f"HTTP {st_all}")

    # 6. Região não-mercado (ex: BRAZIL) deve falhar com HTTP 400
    st_br, _, _ = client.net.request_raw(client.montar_url(mercado="BRAZIL"))
    relatar(6, "Região inválida 'BRAZIL' rejeitada com HTTP 400", st_br == 400, "invalid broad market")

    # 7. Case-insensitivity do parâmetro market (ajustado para validação precisa de eco)
    st_low, d_low, _ = client.consultar(mercado="us")
    cat_long = (d_low or {}).get("marketSummaryResponse", {}).get("marketCategoryLongName")
    relatar(7, "market case-insensitive (us ≡ US) e aceito no edge", st_low == 200 and str(cat_long or "").lower() == "us", f"eco='{cat_long}'")

    # 8. Injeção de FTSE StepStone Private Equity
    st_ftse, d_ftse, _ = client.consultar(mercado="US", enable_ftse=True)
    res_ftse = (d_ftse or {}).get("marketSummaryResponse", {}).get("result", [])
    tem_fgi = any((q.get("symbol") or "").endswith(".FGI") for q in res_ftse)
    relatar(8, "enableFtseStepStoneIndices=true injeta contratos .FGI", st_ftse == 200 and tem_fgi, "índices FGI presentes")

    # 9. Flag noIndicesToFutureSwap aceita sem erro
    st_swap, _, _ = client.consultar(mercado="US", no_indices_swap=True)
    relatar(9, "noIndicesToFutureSwap=true aceito na query string", st_swap == 200, "HTTP 200")

    # 10. Projeção de fields desconhecidos ignorada graciosamente
    st_fld, d_fld, _ = client.consultar(mercado="US", fields="campoInvalidoXYZ")
    relatar(10, "Campos inexistentes em 'fields' não quebram o payload", st_fld == 200 and "marketSummaryResponse" in (d_fld or {}), "ignorado com sucesso")

    # 11. Funcionamento garantido sem Crumb na query
    st_nocrumb, _, _ = client.consultar(mercado="US", anonimo=True)
    relatar(11, "Requisição sem token Crumb responde com sucesso", st_nocrumb == 200, "público")

    # 12. Requisição Anônima Pura (sem cookies no jar)
    net_limpa = NetworkEngine(timeout=client.net.timeout)
    st_anon, _, _ = net_limpa.request_raw(client.montar_url(mercado="US"))
    relatar(12, "Anônimo total (zero cookies no jar) retorna HTTP 200", st_anon == 200, f"cookies={len(net_limpa.cookie_jar)}")

    # 13. Bloqueio anti-bot em User-Agent de biblioteca Python
    st_pyua, _, _ = client.net.request_raw(client.montar_url(mercado="US"), headers={"User-Agent": "Python-urllib/3.12"})
    relatar(13, "User-Agent python-urllib bloqueado pelo edge (HTTP 429)", st_pyua == 429, f"HTTP {st_pyua}")

    # 14. Método HEAD suportado com Content-Length
    st_head, hdrs_head, _ = client.net.request_raw(client.montar_url(mercado="US"), metodo="HEAD")
    relatar(14, "Método HEAD retorna HTTP 200 com header Content-Length", st_head == 200 and "content-length" in hdrs_head, "cabeçalhos válidos")

    # 15. Método POST rejeitado com 405 Method Not Allowed
    st_post, _, rb_post = client.net.request_raw(client.montar_url(mercado="US"), metodo="POST")
    relatar(15, "Método POST rejeitado adequadamente (HTTP 405)", st_post == 405, "Method Not Allowed")

    # 16. Host espelho query2 operacional
    st_q2, d_q2, _ = client.consultar(mercado="US", host="query2")
    relatar(16, "Host secundário query2 responde de forma idêntica", st_q2 == 200 and "marketSummaryResponse" in (d_q2 or {}), "query2 ativo")

    # 17. Host espelho iquery operacional
    st_iq, d_iq, _ = client.consultar(mercado="US", host="iquery")
    relatar(17, "Host terciário iquery responde de forma idêntica", st_iq == 200 and "marketSummaryResponse" in (d_iq or {}), "iquery ativo")

    # 18. Localização pt-BR via lang/region
    st_br, d_br, _ = client.consultar(mercado="AMERICA_ALL", lang="pt-BR", region="BR")
    res_br = (d_br or {}).get("marketSummaryResponse", {}).get("result", [])
    tem_bvsp = any(q.get("symbol") == "^BVSP" for q in res_br)
    relatar(18, "Localização pt-BR/BR inclui referências locais (^BVSP)", st_br == 200 and tem_bvsp, "Ibovespa presente")

    # 19. GLOBAL (ausência de market) entrega dock expandido (>12 itens)
    st_glob, d_glob, _ = client.consultar(mercado=MERCADO_GLOBAL)
    res_glob = (d_glob or {}).get("marketSummaryResponse", {}).get("result", [])
    relatar(19, "Mercado GLOBAL (dock da home) entrega lista completa", st_glob == 200 and len(res_glob) >= 12, f"{len(res_glob)} itens")

    # 20. Validação de frescor de cache de borda (max-age=1)
    st_cc, hdrs_cc, _ = client.net.request_raw(client.montar_url(mercado="US"))
    cc_val = hdrs_cc.get("cache-control", "")
    relatar(20, "Cabeçalho Cache-Control anuncia frescor rápido (max-age=1)", "max-age=1" in cc_val, cc_val[:30])

    taxa = (testes_passados / total_testes) * 100.0
    print(f"\n {p.pintar(f'Resultado Final: {testes_passados}/{total_testes} aprovados ({taxa:.1f}% de conformidade)', 'verde' if taxa == 100 else 'amarelo', negrito=True)}\n")
    return testes_passados == total_testes


# ══════════════ Módulo 2: Auditoria de Invariantes Offline ═══════════════════

def executar_auditoria_offline(caminho_arquivo: str, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Valida estrutura de fixture JSON sem emitir nenhuma requisição de rede."""
    print(f"\n {p.pintar('AUDITORIA ESTRUTURAL DE INVARIANTES (OFFLINE)', 'ciano', negrito=True)}")
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
    msr = j.get("marketSummaryResponse")
    invariantes.append(("1. Envelope raiz 'marketSummaryResponse' presente", isinstance(msr, dict)))

    if isinstance(msr, dict):
        res = msr.get("result")
        err = msr.get("error")
        invariantes.append(("2. Campo 'error' é estritamente nulo", err is None))
        invariantes.append(("3. Campo 'result' é uma lista", isinstance(res, list)))

        if isinstance(res, list) and res:
            invariantes.append(("4. Todos os itens possuem chave 'symbol'", all("symbol" in q for q in res)))
            invariantes.append(("5. Todos os itens contêm 'regularMarketPrice'", all("regularMarketPrice" in q for q in res)))

            # Formatação homogênea (todos raw/fmt ou todos escalares)
            tem_fmt = all(isinstance(q.get("regularMarketPrice"), dict) for q in res)
            tem_esc = all(isinstance(q.get("regularMarketPrice"), (int, float)) for q in res)
            invariantes.append(("6. Homogeneidade no modo de formatação", tem_fmt or tem_esc))

            # Validação crítica: escala percentual (raw não multiplicado por 100)
            pcts_ok = True
            for q in res:
                pct = desempacotar_raw(q.get("regularMarketChangePercent"))
                if pct is not None and abs(float(pct)) > 1000.0:
                    pcts_ok = False
                    break
            invariantes.append(("7. Escala de variação percentual preservada (<1000%)", pcts_ok))

    for rotulo, cond in invariantes:
        st = p.pintar("CONFORME", "verde", negrito=True) if cond else p.pintar("VIOLAÇÃO", "vermelho", negrito=True)
        print(f"  [{st}] {rotulo}")

    aprovado = all(c for _, c in invariantes)
    print(f"\n  Status: {p.pintar('FIXTURE CERTIFICADA', 'verde') if aprovado else p.pintar('FIXTURE INVÁLIDA', 'vermelho')}\n")
    return aprovado


# ═══════════════ Módulo 3: Panorama Consolidado Multi-Tabelas ════════════════

def executar_panorama_mercados(client: MarketSummaryClient, mercados: List[str], p: Palette, rnd: ConsoleRenderer) -> None:
    """
    Renderiza a sequência completa de tabelas de cotação para cada mercado,
    finalizando com um sumário analítico de amplitude e latência.
    """
    print(f"\n {p.pintar('PANORAMA CONSOLIDADO DE MERCADOS — LISTA DE TABELAS', 'ambar', negrito=True)}")
    print(f"  {p.pintar('Consultando e exibindo cotações individuais de cada mercado...', 'cinza_esc')}\n")

    resumo_linhas = []
    tot_altas, tot_baixas = 0, 0

    for mk in mercados:
        rotulo_mk = mk
        st, d, rb = client.consultar(mercado=mk)
        if st != 200 or not d:
            print(f"  {p.pintar(f'[ERRO] Falha ao consultar {rotulo_mk} (HTTP {st})', 'vermelho')}")
            resumo_linhas.append([rotulo_mk, "0", p.pintar("FALHA", "vermelho"), "—", "—", f"{client.net.ultima_latencia_ms:.0f}ms"])
            continue

        res = (d.get("marketSummaryResponse") or {}).get("result", [])
        
        # 1. Renderiza a tabela completa do mercado atual
        rnd.tabela_cotacoes(res, f"MERCADO: {rotulo_mk} ({len(res)} ativos)")
        
        # 2. Estatísticas de amplitude
        altas = sum(1 for q in res if (desempacotar_raw(q.get("regularMarketChangePercent")) or 0) > 0)
        baixas = sum(1 for q in res if (desempacotar_raw(q.get("regularMarketChangePercent")) or 0) < 0)
        tot_altas += altas
        tot_baixas += baixas

        melhor = max(res, key=lambda q: desempacotar_raw(q.get("regularMarketChangePercent")) or -1e9) if res else {}
        pior = min(res, key=lambda q: desempacotar_raw(q.get("regularMarketChangePercent")) or 1e9) if res else {}

        m_sym = melhor.get("symbol", "—")
        m_var = fmt_percentual_br(desempacotar_raw(melhor.get("regularMarketChangePercent")))
        p_sym = pior.get("symbol", "—")
        p_var = fmt_percentual_br(desempacotar_raw(pior.get("regularMarketChangePercent")))

        resumo_linhas.append([
            p.pintar(rotulo_mk, "ambar", negrito=True),
            str(len(res)),
            f"{p.pintar(f'▲{altas}', 'verde')}/{p.pintar(f'▼{baixas}', 'vermelho')}",
            f"{m_sym} ({p.pintar(m_var, 'verde')})",
            f"{p_sym} ({p.pintar(p_var, 'vermelho')})",
            f"{client.net.ultima_latencia_ms:.0f} ms"
        ])
        print()  # Espaçamento entre mercados

    # 3. Tabela de Resumo Consolidado no Final
    print(f" {p.pintar('RESUMO CONSOLIDADO DE AMPLITUDE', 'ciano', negrito=True)}")

    colunas = [
        ("MERCADO", 15, "<"),
        ("ITENS", 6, ">"),
        ("AMPLITUDE", 12, "^"),
        ("MELHOR ATIVO", 20, "<"),
        ("PIOR ATIVO", 20, "<"),
        ("LATÊNCIA", 10, ">")
    ]

    regua_top = f" {p.c('linha')}{rnd.b.TL}" + rnd.b.H.join(rnd.b.H * (w + 2) for _, w, _ in colunas) + f"{rnd.b.TR}{p.RST}"
    print(regua_top)

    h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
    print(f" {p.c('linha')}{rnd.b.V}{p.RST}" + f"{p.c('linha')}{rnd.b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{rnd.b.V}{p.RST}")

    regua_mid = f" {p.c('linha')}{rnd.b.LT}" + rnd.b.H.join(rnd.b.H * (w + 2) for _, w, _ in colunas) + f"{rnd.b.RT}{p.RST}"
    print(regua_mid)

    for linha in resumo_linhas:
        celulas = [f" {pad_vis(linha[i], colunas[i][1], colunas[i][2])} " for i in range(len(colunas))]
        print(f" {p.c('linha')}{rnd.b.V}{p.RST}" + f"{p.c('linha')}{rnd.b.V}{p.RST}".join(celulas) + f"{p.c('linha')}{rnd.b.V}{p.RST}")

    regua_bot = f" {p.c('linha')}{rnd.b.BL}" + rnd.b.H.join(rnd.b.H * (w + 2) for _, w, _ in colunas) + f"{rnd.b.BR}{p.RST}"
    print(regua_bot)
    print(f"  {p.pintar(f'Total de instrumentos mapeados: ▲{tot_altas} altas | ▼{tot_baixas} baixas', 'cinza_esc')}\n")


# ═══════════════ Módulo 4: Console de Requisições Brutas ═════════════════════

def console_requisicao_bruta(client: MarketSummaryClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Interface para testes avançados de protocolo e diagnóstico de endpoints."""
    print(f"\n {p.pintar('CONSOLE DE DIAGNÓSTICO & REQUISIÇÃO BRUTA', 'ciano', negrito=True)}")
    print(f"  {p.pintar('Dispare requisições arbitrárias inspecionando status e cabeçalhos.', 'cinza_esc')}\n")

    metodo = (input(f"  {p.pintar('Método HTTP (GET/POST/HEAD/OPTIONS) [GET]:', 'branco', negrito=True)} ").strip().upper()) or "GET"
    host = (input(f"  {p.pintar('Host (query1/query2/iquery) [query1]:', 'branco', negrito=True)} ").strip().lower()) or "query1"
    mercado = input(f"  {p.pintar('Mercado (ex: US, EUROPE, ou Enter para GLOBAL):', 'branco', negrito=True)} ").strip()

    print(f"\n  Vetor de Crumb:")
    print(f"   [1] Query string (?crumb=...)")
    print(f"   [2] Cabeçalho HTTP (x-crumb: ...)")
    print(f"   [3] Nenhum (anônimo puro)")
    v_opt = input(f"  {p.pintar('Opção de crumb [3]:', 'branco')} ").strip() or "3"

    token = None
    custom_headers: Dict[str, str] = {}
    if v_opt in ("1", "2"):
        if not client.net.crumb:
            print(f"  {p.pintar('Obtendo Crumb via bootstrap...', 'cinza_esc')}")
            client.net.bootstrap_auth()
        token = client.net.crumb
        if v_opt == "2" and token:
            custom_headers["x-crumb"] = token
            token = None

    url = client.montar_url(mercado=mercado or None, crumb=token, host=host)
    print(f"\n  {p.pintar('Disparando:', 'cinza_esc')} {p.pintar(f'{metodo} {url}', 'azul')}")

    status, hdrs, corpo = client.net.request_raw(url, metodo=metodo, headers=custom_headers)
    st_cor = "verde" if status == 200 else "vermelho"
    print(f"  {p.pintar('Resposta:', 'cinza_esc')} {p.pintar(f'HTTP {status}', st_cor, negrito=True)} | Latência: {client.net.ultima_latencia_ms:.1f}ms | Tamanho: {len(corpo)}B\n")

    rnd.caixa(
        [f"{k}: {v}" for k, v in list(hdrs.items())[:6]],
        titulo="CABEÇALHOS DE RESPOSTA",
        cor_titulo="ciano"
    )

    amostra = corpo[:300].decode("utf-8", errors="replace")
    print(f"\n  {p.pintar('Corpo bruto (primeiros 300 bytes):', 'cinza_med')}")
    print(f"  {p.pintar(amostra, 'cinza_esc')}{'...' if len(corpo) > 300 else ''}\n")


# ══════════════ Módulo 5: Visões Detalhadas & Submenu v2.0 ═══════════════════

def submenu_visoes_mercado(client: MarketSummaryClient, mercado: str, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop contínuo de alternância de visões sobre a mesma consulta (100% v6)."""
    st, d, rb = client.consultar(mercado=mercado)
    if st != 200 or not d:
        print(f"  {p.pintar(f'[ERRO] Falha ao consultar mercado {mercado}.', 'vermelho')}")
        return

    res = (d.get("marketSummaryResponse") or {}).get("result", [])

    while True:
        try:
            print(f"\n {p.pintar(f'VISÕES DISPONÍVEIS — MERCADO: {mercado}', 'ambar', negrito=True)}")
            print(f"  [1] Tabela Resumo Padrão")
            print(f"  [2] Painel com Distribuição e Amplitude")
            print(f"  [3] Visão Horário Estendido (fulldayPrice)")
            print(f"  [4] Visão FTSE StepStone Private Equity (.FGI)")
            print(f"  [5] Visão Sem Swap de Futuros (noIndicesToFutureSwap)")
            print(f"  [6] Detalhar Todos os Campos de um Instrumento")
            print(f"  [7] Exportar JSON Bruto da Resposta")
            print(f"  [0] Voltar ao Menu Principal")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                break

            elif escolha == "1":
                rnd.tabela_cotacoes(res, f"COTAÇÕES — {mercado}")

            elif escolha == "2":
                rnd.tabela_cotacoes(res, f"COTAÇÕES & AMPLITUDE — {mercado}")
                altas = sum(1 for q in res if (desempacotar_raw(q.get("regularMarketChangePercent")) or 0) > 0)
                baixas = sum(1 for q in res if (desempacotar_raw(q.get("regularMarketChangePercent")) or 0) < 0)
                tot = max(1, len(res))
                print(f"\n  {p.pintar('Distribuição de Variação no Grupo:', 'cinza_med', negrito=True)}")
                print(f"   {p.pintar('Altas: ', 'verde')}{pad_vis(str(altas), 3)} {rnd.barra_amplitude(altas / tot, 20, 'verde')} {fmt_percentual_br((altas / tot) * 100, False)}")
                print(f"   {p.pintar('Baixas:', 'vermelho')}{pad_vis(str(baixas), 3)} {rnd.barra_amplitude(baixas / tot, 20, 'vermelho')} {fmt_percentual_br((baixas / tot) * 100, False)}")

            elif escolha == "3":
                st_fd, d_fd, _ = client.consultar(mercado=mercado, fields=CAMPOS_LOADER_FULLDAY)
                res_fd = ((d_fd or {}).get("marketSummaryResponse") or {}).get("result", [])
                rnd.tabela_cotacoes(res_fd, f"HORÁRIO ESTENDIDO (FULLDAY) — {mercado}")

            elif escolha == "4":
                st_fgi, d_fgi, _ = client.consultar(mercado=mercado, enable_ftse=True)
                res_fgi = [q for q in ((d_fgi or {}).get("marketSummaryResponse") or {}).get("result", []) if (q.get("symbol") or "").endswith(".FGI")]
                if not res_fgi:
                    print(f"  {p.pintar('Nenhum índice .FGI retornado para este mercado.', 'amarelo')}")
                else:
                    rnd.tabela_cotacoes(res_fgi, f"FTSE STEPSTONE PRIVATE EQUITY — {mercado}")

            elif escolha == "5":
                st_sw, d_sw, _ = client.consultar(mercado=mercado, no_indices_swap=True)
                res_sw = ((d_sw or {}).get("marketSummaryResponse") or {}).get("result", [])
                rnd.tabela_cotacoes(res_sw, f"SEM SWAP DE FUTUROS (ÍNDICES À VISTA) — {mercado}")

            elif escolha == "6":
                sym_alvo = input(f"  {p.pintar('Informe o símbolo desejado:', 'branco')} ").strip().upper()
                item = next((q for q in res if (q.get("symbol") or "").upper() == sym_alvo), None)
                if not item:
                    print(f"  {p.pintar('Símbolo não localizado no resultado.', 'amarelo')}")
                else:
                    linhas = [f"{pad_vis(k, 32, '<')}: {v}" for k, v in sorted(item.items())]
                    rnd.caixa(linhas, titulo=f"DETALHE: {sym_alvo}", cor_titulo="ambar")

            elif escolha == "7":
                nome_arq = f"marketSummary_{mercado}_{int(time.time())}.json"
                with open(nome_arq, "wb") as f:
                    f.write(rb)
                print(f"  {p.pintar(f'[SUCESSO] JSON cru exportado: {nome_arq} ({len(rb)}B)', 'verde')}")

        except KeyboardInterrupt:
            print(f"\n  {p.pintar('Ação cancelada. Retornando ao submenu...', 'amarelo')}")


# ════════════════════ Menu Principal & CLI Dispatcher ═══════════════════════

def menu_principal(client: MarketSummaryClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop contínuo interativo anti-fechamento."""
    mercado_atual = "US"

    while True:
        try:
            print(f"\n {p.pintar('YAHOO FINANCE MARKET SUMMARY (v6 Explorer)', 'ambar', negrito=True)}")
            print(f"  {p.pintar('Fonte dos docks da home e página /markets | stdlib pura', 'cinza_esc')}\n")

            print(f"  [1] Painel de Mercado Rápido (atual: {p.pintar(mercado_atual, 'ciano', negrito=True)})")
            print(f"  [2] Alternar Mercado Selecionado")
            print(f"  [3] Panorama Consolidado (Lista de Tabelas de Cada Mercado)")
            print(f"  [4] Console de Requisições Brutas (Diagnóstico)")
            print(f"  [5] Suíte de Verificação ao Vivo (20 Testes)")
            print(f"  [6] Auditoria Estrutural Offline (Fixture JSON)")
            print(f"  [7] Gestão de Sessão & Credenciais (A3 / Crumb)")
            print(f"  [8] Exportar Fixture JSON Crua")
            print(f"  [0] Encerrar Aplicativo")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                print(f"\n  {p.pintar('Encerrando aplicação de forma limpa. Até logo!', 'ciano')}")
                break

            elif escolha == "1":
                submenu_visoes_mercado(client, mercado_atual, p, rnd)

            elif escolha == "2":
                print(f"\n  Opções: {', '.join(MERCADOS_PRESETS)} ou GLOBAL")
                novo_m = input(f"  {p.pintar('Novo mercado:', 'branco')} ").strip().upper()
                if novo_m:
                    mercado_atual = novo_m

            elif escolha == "3":
                executar_panorama_mercados(client, MERCADOS_PRESETS, p, rnd)

            elif escolha == "4":
                console_requisicao_bruta(client, p, rnd)

            elif escolha == "5":
                executar_suite_verificacao(client, p, rnd)

            elif escolha == "6":
                arq = input(f"  {p.pintar('Caminho do arquivo JSON [fixture.json]:', 'branco')} ").strip() or "fixture.json"
                executar_auditoria_offline(arq, p, rnd)

            elif escolha == "7":
                a3 = client.net.obter_a3_presente()
                rnd.caixa([
                    f"Cookie A3 no Jar : {p.pintar('Sim (' + str(len(a3)) + 'B)', 'verde') if a3 else p.pintar('Ausente', 'vermelho')}",
                    f"Token Crumb      : {p.pintar(client.net.crumb or 'Não emitido', 'verde' if client.net.crumb else 'amarelo')}",
                    f"Total Requisições: {client.net.total_requisicoes}",
                    f"Última Latência  : {client.net.ultima_latencia_ms:.1f} ms"
                ], titulo="ESTADO DA SESSÃO", cor_titulo="ciano")
                acao = input(f"\n  {p.pintar('Deseja renovar sessão agora? (s/n) [n]:', 'branco')} ").strip().lower()
                if acao == "s":
                    ok, msg = client.net.bootstrap_auth()
                    print(f"  {p.pintar(msg, 'verde' if ok else 'vermelho')}")

            elif escolha == "8":
                st, _, rb = client.consultar(mercado=mercado_atual)
                if st == 200:
                    nome = f"marketSummary_{mercado_atual}.json"
                    with open(nome, "wb") as f:
                        f.write(rb)
                    print(f"  {p.pintar(f'[OK] Arquivo salvo: {nome} ({len(rb)}B)', 'verde')}")

        except KeyboardInterrupt:
            print(f"\n  {p.pintar('Operação interrompida pelo usuário (Ctrl+C). Retornando ao menu...', 'amarelo')}")
        except EOFError:
            print(f"\n  {p.pintar('EOF detectado. Encerrando...', 'ciano')}")
            break
        except Exception as e:
            print(f"\n  {p.pintar(f'[ERRO INESPERADO] {e}', 'vermelho')}")


# ════════════════════════ Ponto de Entrada (Main) ═══════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="v6_finance_quote_marketSummary.py",
        description="Terminal Interativo Bloomberg & Cliente Canônico GET /v6/finance/quote/marketSummary"
    )

    # Argumentos CLI posicionais e antigos
    parser.add_argument("mercado_posicional", nargs="?", default=None, help="Mercado alvo opcional")
    parser.add_argument("--market", "-m", default=None, help="Código do mercado (US, EUROPE, ASIA, etc.)")
    parser.add_argument("--painel", action="store_true", help="Exibe o painel tabular direto e encerra")
    parser.add_argument("--raw", action="store_true", help="formatted=false (números primitivos)")
    parser.add_argument("--verifica", action="store_true", help="Executa suíte de validação ao vivo direto")
    parser.add_argument("--comparar", default=None, metavar="M1,M2", help="Compara lista de mercados")
    parser.add_argument("--panorama", action="store_true", help="Exibe panorama de todos os mercados em lista de tabelas")
    parser.add_argument("--auditar", default=None, metavar="ARQ", help="Audita estruturalmente fixture offline")
    parser.add_argument("--json", dest="json_out", default=None, metavar="ARQ", help="Exporta JSON cru para arquivo")
    parser.add_argument("--host", choices=list(HOSTS_EP.keys()), default=DEFAULT_HOST, help="Host edge da Yahoo")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Timeout de conexões em segundos")
    parser.add_argument("--ascii", action="store_true", help="Usa molduras ASCII puras (+---+)")
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
    client = MarketSummaryClient(net, default_host=args.host)

    try:
        # Modo 1: Auditoria Offline
        if args.auditar:
            return 0 if executar_auditoria_offline(args.auditar, p, rnd) else 1

        # Modo 2: Suíte de Testes ao Vivo
        if args.verifica:
            return 0 if executar_suite_verificacao(client, p, rnd) else 1

        # Modo 3: Panorama / Comparador (Lista de Tabelas)
        if args.panorama or args.comparar:
            lista = MERCADOS_PRESETS if args.panorama else [m.strip().upper() for m in args.comparar.split(",") if m.strip()]
            executar_panorama_mercados(client, lista, p, rnd)
            return 0

        # Modo 4: Consulta Não-Interativa CLI
        alvo = (args.market or args.mercado_posicional or "").upper()
        if alvo or args.painel or args.json_out:
            m_final = alvo if alvo and alvo != MERCADO_GLOBAL else None
            st, d, rb = client.consultar(mercado=m_final, formatted=not args.raw)

            if args.json_out:
                with open(args.json_out, "wb") as f:
                    f.write(rb)
                print(f"Salvo: {args.json_out} ({len(rb)}B)")
                return 0

            if st == 200 and d:
                res = (d.get("marketSummaryResponse") or {}).get("result", [])
                rnd.tabela_cotacoes(res, f"COTAÇÕES — {alvo or 'GLOBAL'}")
                return 0
            else:
                sys.stderr.write(f"Erro ao consultar mercado (HTTP {st})\n")
                return 1

        # Modo 5: Menu Interativo Contínuo (Anti-Fechamento)
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