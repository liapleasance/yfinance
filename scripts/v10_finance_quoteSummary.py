#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 YAHOO FINANCE QUOTE SUMMARY v10 — APLICATIVO INTERATIVO & CLIENTE CANÔNICO
 Endpoint: GET https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}
═══════════════════════════════════════════════════════════════════════════════
 REQUISITOS IMPLEMENTADOS:
   1. ANTI-FECHAMENTO: Loop de menu contínuo sem argumentos, proteção contra
      exceções não tratadas, pausa ao sair (anti-duplo clique) e Ctrl+C gracioso.
   2. ZERO DEPENDÊNCIAS EXTERNAS: Estritamente Python stdlib (urllib, http.cookiejar,
      json, shutil, ssl, etc.). Compatível com Python 3.8+.
   3. UI DESIGN BLOOMBERG: Paleta de cores ANSI profissional, caixas e tabelas com
      cálculo de largura visível imune a ANSI, formatação pt-BR localizada.
   4. FUNÇÕES EXPOSTAS:
      - Roteamento no PATH ({symbol} percent-encoded).
      - Catálogo completo de 55 módulos e presets por aba/classe de ativo.
      - Desembrulho recursivo de objetos {raw, fmt, longFmt}.
      - Tratamento de frações percentuais (diferença crítica em relação ao v7).
      - Console de requisições brutas, suíte de testes ao vivo e auditoria offline.
      - Gestão de credenciais (Cookie A3 + Crumb) com auto-recuperação de 401.
   5. ROBUSTEZ DE REDE: Auto-retry com backoff em 429/503 e telemetria de latência.
   6. COMPATIBILIDADE: Suporta flags de linha de comando para automação/scripts.
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
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union

__version__ = "3.5.0"

# Ativação de Virtual Terminal no Windows
if os.name == "nt":
    os.system("")

# Forçar codificação UTF-8 no terminal
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ════════════════════════ Constantes do Protocolo ═══════════════════════════

HOST_QUERY1 = "query1.finance.yahoo.com"
HOST_QUERY2 = "query2.finance.yahoo.com"
PATH_V10 = "/v10/finance/quoteSummary"
URL_FC = "https://fc.yahoo.com"
URL_GETCRUMB = "https://query1.finance.yahoo.com/v1/test/getcrumb"
DEFAULT_TIMEOUT = 15.0
CORTESIA_SEGUNDOS = 0.8

USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

# Regex de validação de símbolo do transporte oficial (proíbe caracteres ilegais)
REGEX_SIMBOLO_PROIBIDO = re.compile(r"[^a-zA-Z0-9^.$_+=*&:@~-]")

# Símbolos canônicos padrão
MAGNIFICENT_7 = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
BRAZIL_BLUE_CHIPS = ["PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBDC4.SA", "BBAS3.SA"]

# ════════════════ Catálogo Canônico de Módulos (55 Módulos) ═════════════════

BASE_5 = ["price", "summaryDetail", "pageViews", "financialsTemplate", "calendarEvents"]

PRESETS: Dict[str, Tuple[str, List[str]]] = {
    "resumo": (
        "Leve: Preço e Resumo Operacional",
        ["price", "summaryDetail"]
    ),
    "base5": (
        "Base do Carregador (5 Módulos)",
        BASE_5
    ),
    "producao": (
        "Composição Completa de Produção (Ações - 20 Módulos)",
        sorted(list(set(
            BASE_5 + [
                "summaryProfile", "financialData", "recommendationTrend", "earnings",
                "equityPerformance", "defaultKeyStatistics", "esgScores", "assetProfile",
                "quoteUnadjustedPerformanceOverview", "chartPreviousClose", "corporateActions",
                "earningsCallTranscripts", "earningsGaap", "earningsNonGaap", "upgradeDowngradeHistory"
            ]
        )))
    ),
    "fundamentos": (
        "Análise Fundamentalista e DRE",
        [
            "financialData", "defaultKeyStatistics", "earnings", "earningsTrend",
            "incomeStatementHistory", "balanceSheetHistory", "cashflowStatementHistory"
        ]
    ),
    "analise": (
        "Aba Analysis: Consenso e Projeções de Analistas",
        [
            "upgradeDowngradeHistory", "recommendationTrend", "financialData",
            "earningsHistory", "earningsTrend", "industryTrend", "indexTrend", "sectorTrend"
        ]
    ),
    "holders": (
        "Aba Holders: Detentores Institucionais e Insiders",
        [
            "institutionOwnership", "fundOwnership", "majorDirectHolders",
            "majorHoldersBreakdown", "insiderTransactions", "insiderHolders", "netSharePurchaseActivity"
        ]
    ),
    "summary-etf": (
        "ETF / Fundos de Índice",
        sorted(list(set(
            BASE_5 + [
                "summaryDetail", "defaultKeyStatistics", "assetProfile",
                "topHoldings", "fundPerformance", "fundProfile", "esgScores"
            ]
        )))
    ),
    "summary-crypto": (
        "Criptoativos",
        sorted(list(set(
            BASE_5 + [
                "summaryProfile", "financialData", "recommendationTrend", "earnings",
                "defaultKeyStatistics", "assetProfile", "attribution"
            ]
        )))
    ),
}

# ═══════════════════════ Paleta Bloomberg & UI ANSI ═════════════════════════

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def vlen(text: str) -> int:
    return len(strip_ansi(str(text)))


def pad_vis(text: str, width: int, align: str = "<") -> str:
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
    """Paleta Bloomberg oficial baseada em códigos TrueColor e 256 cores."""
    _CORES = {
        "ambar":     ((255, 160, 40),  208),  # #FFA028 Tickers / Destaque
        "amarelo":   ((255, 214, 0),   220),  # #FFD600 Alertas
        "verde":     ((0, 200, 83),    41),   # #00C853 Altas / Sucesso
        "vermelho":  ((255, 67, 61),   203),  # #FF433D Baixas / Falha
        "ciano":     ((0, 212, 255),   45),   # #00D4FF Dados secundários
        "azul":      ((0, 104, 255),   33),   # #0068FF Links
        "teal":      ((74, 246, 195),  86),   # #4AF6C3 Acentos
        "cinza_med": ((160, 160, 160), 247),  # #A0A0A0 Rótulos
        "cinza_esc": ((128, 128, 128), 244),  # #808080 Metadados
        "linha":     ((60, 60, 60),    238),  # Bordas
        "branco":    ((255, 255, 255), 231),
    }

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        ct = (os.environ.get("COLORTERM") or "").lower()
        self.suporta_rgb = "truecolor" in ct or "24bit" in ct or bool(os.environ.get("WT_SESSION"))

    def c(self, nome: str, negrito: bool = False, fundo: Optional[str] = None) -> str:
        if not self.enabled:
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
        return "\x1b[0m" if self.enabled else ""

    def pintar(self, texto: Any, cor: str = "branco", negrito: bool = False) -> str:
        return f"{self.c(cor, negrito)}{texto}{self.RST}"


class BoxChars:
    """Caracteres de moldura para tabelas e caixas."""
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
    if valor is None or valor == {}:
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
    if valor is None or valor == {}:
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


def fmt_percentual_fracao_br(valor: Any, com_sinal: bool = True) -> str:
    """
    Formata percentual no v10.
    ATENÇÃO: No endpoint v10, o campo 'raw' é uma FRAÇÃO DECIMAL (ex: 0.025 = 2.50%).
    É obrigatório multiplicar por 100!
    """
    if valor is None or valor == {}:
        return "—"
    try:
        f = float(valor) * 100.0
        sinal = "+" if f > 0 and com_sinal else ""
        return f"{sinal}{fmt_numero_br(f, 2)}%"
    except (ValueError, TypeError):
        return str(valor)


def fmt_epoch_local(epoch_val: Any) -> str:
    if not epoch_val or epoch_val == {}:
        return "—"
    try:
        ts = float(epoch_val)
        if ts > 1e11:
            ts /= 1000.0
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(epoch_val)


def desempacotar_recursivo(valor: Any) -> Any:
    """Desembrulha recursivamente qualquer objeto {raw, fmt, longFmt} no JSON."""
    if isinstance(valor, dict):
        if "raw" in valor:
            return valor["raw"]
        return {k: desempacotar_recursivo(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [desempacotar_recursivo(v) for v in valor]
    return valor


# ══════════════════════ Motor de Rede & Sessão HTTP ═════════════════════════

class QuoteSummaryError(Exception):
    def __init__(self, code: str, description: str = "", status: Optional[int] = None):
        self.code = code
        self.description = description
        self.status = status
        super().__init__(f"[{status or '-'}] {code}: {description}".rstrip(": "))


class NetworkEngine:
    """
    Motor HTTP resiliente com suporte a CookieJar e captura automática de A3 + Crumb.
    Totalmente baseado na biblioteca padrão urllib.
    """
    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        
        # Contexto SSL tolerante
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ctx),
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
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
        """Executa handshake: fc.yahoo.com (Cookie A3) -> getcrumb."""
        try:
            req_fc = urllib.request.Request(
                URL_FC,
                headers={"User-Agent": USER_AGENT_BROWSER, "Accept": "*/*"}
            )
            try:
                with self.opener.open(req_fc, timeout=self.timeout):
                    pass
            except urllib.error.HTTPError:
                pass  # 404 é normal e assenta o Cookie A3
            self.total_requisicoes += 1

            self.a3_cookie = self.obter_a3_presente()
            if not self.a3_cookie:
                return False, "Handshake em fc.yahoo.com não produziu o Cookie A3."

            req_crumb = urllib.request.Request(
                URL_GETCRUMB,
                headers={"User-Agent": USER_AGENT_BROWSER, "Accept": "text/plain,*/*"}
            )
            with self.opener.open(req_crumb, timeout=self.timeout) as resp:
                corpo = resp.read().decode("utf-8", errors="replace").strip()
                self.total_requisicoes += 1
                if resp.status == 200 and corpo and "<" not in corpo and len(corpo) <= 64:
                    self.crumb = corpo
                    return True, f"Sessão autenticada. Crumb: {self.crumb}"
                return False, f"Resposta inválida de Crumb: {corpo[:60]}"
        except Exception as e:
            return False, f"Falha no bootstrap de autenticação: {e}"

    def request_raw(
        self,
        url: str,
        metodo: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        dados: Optional[bytes] = None,
        max_retries: int = 4,
        renovar_401: bool = True
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Executa requisição HTTP com renovação de 401 e backoff em 429/503."""
        hdrs = {
            "User-Agent": USER_AGENT_BROWSER,
            "Accept": "application/json",
            "Referer": "https://finance.yahoo.com/"
        }
        if headers:
            hdrs.update(headers)

        req = urllib.request.Request(url, data=dados, headers=hdrs, method=metodo)

        for tentativa in range(max_retries):
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

                if e.code == 401 and renovar_401 and tentativa < 1:
                    ok, _ = self.bootstrap_auth()
                    if ok and self.crumb and "crumb=" in url:
                        parsed = urllib.parse.urlparse(url)
                        qs = urllib.parse.parse_qs(parsed.query)
                        qs["crumb"] = [self.crumb]
                        nova_query = urllib.parse.urlencode(qs, doseq=True)
                        url = urllib.parse.urlunparse(parsed._replace(query=nova_query))
                        req = urllib.request.Request(url, data=dados, headers=hdrs, method=metodo)
                    continue

                if e.code in (429, 503) and tentativa < max_retries - 1:
                    espera = (2 ** tentativa) + random.uniform(0.1, 0.5)
                    time.sleep(espera)
                    continue

                return e.code, resp_headers, corpo

            except Exception as e:
                self.ultima_latencia_ms = (time.perf_counter() - t0) * 1000.0
                if tentativa < max_retries - 1:
                    time.sleep((2 ** tentativa) + random.uniform(0.1, 0.4))
                    continue
                raise e

        return self.ultimo_status, {}, b""


# ═══════════════════════ Cliente do Endpoint /v10 ═══════════════════════════

class QuoteSummaryClient:
    """Cliente oficial para o endpoint GET /v10/finance/quoteSummary/{symbol}."""
    def __init__(self, net: NetworkEngine, default_host: str = HOST_QUERY1):
        self.net = net
        self.host = default_host

    def validar_simbolo(self, symbol: str) -> str:
        s = str(symbol).strip().upper()
        if not s or REGEX_SIMBOLO_PROIBIDO.search(s):
            raise QuoteSummaryError("Bad request for loadQuoteSummary", f"Símbolo inválido: {symbol!r}")
        return s

    def montar_url(
        self,
        symbol: str,
        modules: List[str],
        formatted: bool = True,
        lang: str = "en-US",
        region: str = "US",
        flags_query: Optional[Dict[str, str]] = None,
        host: Optional[str] = None
    ) -> str:
        h = host or self.host
        sym = self.validar_simbolo(symbol)
        sym_encoded = urllib.parse.quote(sym, safe="")

        modulos_ordenados = sorted(list(set(modules)))
        params: Dict[str, str] = {
            "modules": ",".join(modulos_ordenados),
            "formatted": "true" if formatted else "false",
            "lang": lang,
            "region": region,
        }
        if self.net.crumb:
            params["crumb"] = self.net.crumb

        if flags_query:
            params.update(flags_query)

        qs = urllib.parse.urlencode(params)
        return f"https://{h}{PATH_V10}/{sym_encoded}?{qs}"

    def summary_raw(
        self,
        symbol: str,
        modules: List[str],
        formatted: bool = True,
        flags_query: Optional[Dict[str, str]] = None,
        host: Optional[str] = None
    ) -> Tuple[int, Optional[Dict[str, Any]], bytes]:
        if not self.net.crumb:
            self.net.bootstrap_auth()

        url = self.montar_url(symbol, modules, formatted=formatted, flags_query=flags_query, host=host)
        status, _, raw_bytes = self.net.request_raw(url)

        if status == 200:
            try:
                dados = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                return status, dados, raw_bytes
            except json.JSONDecodeError:
                return status, None, raw_bytes
        return status, None, raw_bytes

    def summary(
        self,
        symbol: str,
        modules: List[str],
        formatted: bool = True,
        unwrap: bool = True,
        flags_query: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Retorna o dicionário de módulos do ativo, com tratamento de erros de duplo envelope."""
        status, dados, raw_bytes = self.summary_raw(symbol, modules, formatted=formatted, flags_query=flags_query)

        if status == 401:
            err = (dados or {}).get("finance", {}).get("error", {})
            raise QuoteSummaryError(err.get("code", "Unauthorized"), err.get("description", "Acesso não autorizado"), 401)

        if status == 404:
            err = (dados or {}).get("quoteSummary", {}).get("error", {})
            if not err:
                err = (dados or {}).get("finance", {}).get("error", {})
            raise QuoteSummaryError(err.get("code", "Not Found"), err.get("description", f"Ativo não encontrado: {symbol}"), 404)

        if status != 200 or not dados:
            raise QuoteSummaryError("HTTPError", f"Falha na requisição com código {status}", status)

        qs = dados.get("quoteSummary", {})
        if qs.get("error"):
            err = qs["error"]
            raise QuoteSummaryError(err.get("code", "Unknown"), err.get("description", ""), 404)

        resultado = qs.get("result") or []
        if not resultado:
            raise QuoteSummaryError("EmptyResponse", f"Nenhum módulo retornado para {symbol}", 200)

        obj = resultado[0]
        if unwrap:
            return desempacotar_recursivo(obj)
        return obj


# ════════════════════ Componentes Gráficos de Terminal ══════════════════════

class ConsoleRenderer:
    def __init__(self, p: Palette, b: BoxChars):
        self.p = p
        self.b = b

    def largura_term(self) -> int:
        return shutil.get_terminal_size((88, 24)).columns

    def caixa(self, linhas: List[str], titulo: Optional[str] = None, cor_titulo: str = "ambar", rodape: Optional[str] = None):
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

    def imprimir_tabela_resumo(self, simbolos_dados: Dict[str, Dict[str, Any]]):
        """Imprime tabela densa comparando os módulos price e summaryDetail de múltiplos ativos."""
        colunas = [
            ("SÍMBOLO", 9, "<"),
            ("NOME", 24, "<"),
            ("PREÇO", 11, ">"),
            ("VAR %", 9, ">"),
            ("VOLUME", 11, ">"),
            ("MKT CAP / AUM", 13, ">"),
            ("P/L (PE)", 9, ">"),
            ("ESTADO", 8, "^")
        ]
        p, b = self.p, self.b

        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for sym, modulos in simbolos_dados.items():
            if "__erro__" in modulos:
                err = modulos["__erro__"]
                msg_err = f"{p.pintar(sym, 'ambar', negrito=True)}: {p.pintar(err.get('code', 'ERRO'), 'vermelho')} ({err.get('description', '')[:40]})"
                print(f" {p.c('linha')}{b.V}{p.RST} {pad_vis(msg_err, sum(w + 2 for _, w, _ in colunas) + len(colunas) - 3, '<')} {p.c('linha')}{b.V}{p.RST}")
                continue

            pr_mod = modulos.get("price") or {}
            sd_mod = modulos.get("summaryDetail") or {}

            nome = pr_mod.get("longName") or pr_mod.get("shortName") or sd_mod.get("shortName") or "—"
            preco = pr_mod.get("regularMarketPrice") or sd_mod.get("regularMarketPrice")
            var_fracao = pr_mod.get("regularMarketChangePercent") or sd_mod.get("regularMarketChangePercent")
            vol = pr_mod.get("regularMarketVolume") or sd_mod.get("regularMarketVolume")
            mcap = pr_mod.get("marketCap") or sd_mod.get("marketCap") or sd_mod.get("totalAssets")
            pe = sd_mod.get("trailingPE") or sd_mod.get("forwardPE")
            estado = pr_mod.get("marketState") or "—"

            pr_str = fmt_numero_br(preco, 2)
            pct_str = fmt_percentual_fracao_br(var_fracao)
            vol_str = fmt_grandeza_br(vol)
            mcap_str = fmt_grandeza_br(mcap)
            pe_str = fmt_numero_br(pe, 2)

            cor_v = "branco"
            if var_fracao is not None and var_fracao != {}:
                try:
                    cor_v = "verde" if float(var_fracao) > 0 else ("vermelho" if float(var_fracao) < 0 else "branco")
                except Exception:
                    pass

            est_cor = "verde" if estado == "REGULAR" else "amarelo"

            linha_cel = [
                (p.pintar(sym[:8], "ambar", negrito=True), colunas[0][1], colunas[0][2]),
                (nome[:23], colunas[1][1], colunas[1][2]),
                (pr_str[:10], colunas[2][1], colunas[2][2]),
                (p.pintar(pct_str[:8], cor_v), colunas[3][1], colunas[3][2]),
                (vol_str[:10], colunas[4][1], colunas[4][2]),
                (mcap_str[:12], colunas[5][1], colunas[5][2]),
                (pe_str[:8], colunas[6][1], colunas[6][2]),
                (p.pintar(estado[:7], est_cor), colunas[7][1], colunas[7][2]),
            ]
            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)


# ═══════════════ Módulo 1: Suíte de Verificação ao Vivo ══════════════════════

def executar_suite_verificacao(client: QuoteSummaryClient, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Executa checagens empíricas contra a borda ativa do Yahoo Finance."""
    print(f"\n {p.pintar('SUÍTE DE VERIFICAÇÃO AO VIVO (/v10/finance/quoteSummary)', 'azul', negrito=True)}")
    print(f"  {p.pintar('Validando conformidade de rede, rotas no PATH, módulos e autenticação...', 'cinza_esc')}\n")

    testes_passados = 0
    total_testes = 8

    def relatar(num: int, rotulo: str, cond: bool, detalhe: str = "") -> None:
        nonlocal testes_passados
        st = p.pintar("PASS", "verde", negrito=True) if cond else p.pintar("FAIL", "vermelho", negrito=True)
        if cond:
            testes_passados += 1
        d_str = f" {p.pintar('· ' + detalhe, 'cinza_esc')}" if detalhe else ""
        print(f"  [{st}] {pad_vis(f'{num:02d}. {rotulo}', 58, '<')}{d_str}")
        time.sleep(0.1)

    # 1. Autenticação A3 + Crumb válida
    ok_auth, msg_auth = client.net.bootstrap_auth()
    relatar(1, "Handshake fc.yahoo.com + Emissão de Crumb", ok_auth, client.net.crumb or "")

    # 2. Requisição canônica PATH AAPL (price, summaryDetail)
    st, d, _ = client.summary_raw("AAPL", ["price", "summaryDetail"])
    res = (d or {}).get("quoteSummary", {}).get("result", [])
    relatar(2, "Canônica AAPL no PATH retorna HTTP 200", st == 200 and len(res) > 0, f"result[0] com {len(res[0]) if res else 0} módulos")

    # 3. Ausência de chave 'symbol' na raiz do objeto result[0]
    obj = res[0] if res else {}
    relatar(3, "Chave 'symbol' ausente na raiz de result[0] (contrato v10)", "symbol" not in obj, "símbolo implícito na URL")

    # 4. Percentual do v10 chega em FRAÇÃO decimal (ex: < 1.0 para variações normais)
    pr_mod = obj.get("price", {})
    var_raw = pr_mod.get("regularMarketChangePercent", {}).get("raw")
    relatar(4, "Percentual bruto 'raw' entregue em fração decimal", isinstance(var_raw, float) and abs(var_raw) < 1.0, f"raw={var_raw}")

    # 5. Rota errada via query string (?symbol=AAPL) deve falhar com 404 JSON
    url_errada = f"https://{client.host}{PATH_V10}?symbol=AAPL&modules=price&crumb={client.net.crumb or ''}"
    st_err, _, rb_err = client.net.request_raw(url_errada)
    relatar(5, "Tentativa de ?symbol= em query rejeitada com HTTP 404", st_err == 404, "exige símbolo no PATH")

    # 6. Símbolo inexistente retorna 404 com envelope quoteSummary.error
    st_inv, d_inv, _ = client.summary_raw("SIMBOLO_INEXISTENTE_XYZ", ["price"])
    err_app = (d_inv or {}).get("quoteSummary", {}).get("error")
    relatar(6, "Ativo inexistente tratado com 404 quoteSummary.error", st_inv == 404 and bool(err_app), err_app.get("code") if err_app else "")

    # 7. Omissão silenciosa de módulos corporativos para ETF (SPY)
    st_spy, d_spy, _ = client.summary_raw("SPY", ["price", "earningsGaap", "fundProfile"])
    res_spy = ((d_spy or {}).get("quoteSummary", {}).get("result", []) or [{}])[0]
    relatar(7, "Módulo 'earningsGaap' omitido silenciosamente para SPY (ETF)", "earningsGaap" not in res_spy and "fundProfile" in res_spy, "filtragem por classe")

    # 8. Módulo legado de servidor quoteType
    st_qt, d_qt, _ = client.summary_raw("AAPL", ["quoteType"])
    res_qt = ((d_qt or {}).get("quoteSummary", {}).get("result", []) or [{}])[0]
    relatar(8, "Módulo legado 'quoteType' aceito e povoado", "quoteType" in res_qt, res_qt.get("quoteType", {}).get("exchange", ""))

    taxa = (testes_passados / total_testes) * 100.0
    print(f"\n {p.pintar(f'Resultado da Suíte: {testes_passados}/{total_testes} aprovados ({taxa:.1f}% de conformidade)', 'verde' if taxa == 100 else 'amarelo', negrito=True)}\n")
    return testes_passados == total_testes


# ══════════════ Módulo 2: Auditoria de Invariantes Offline ═══════════════════

def executar_auditoria_offline(caminho_arquivo: str, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Valida estrutura de fixtures JSON salvas (ex: SPY.json ou INTC.json)."""
    print(f"\n {p.pintar('AUDITORIA DE INVARIANTES ESTRUTURAIS (OFFLINE)', 'ciano', negrito=True)}")
    print(f"  {p.pintar(f'Analisando fixture: {caminho_arquivo}', 'cinza_esc')}\n")

    if not os.path.isfile(caminho_arquivo):
        print(f"  {p.pintar('[ERRO] Arquivo não localizado.', 'vermelho')}")
        return False

    try:
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            j = json.load(f)
    except Exception as e:
        print(f"  {p.pintar(f'[ERRO] Falha ao ler JSON: {e}', 'vermelho')}")
        return False

    # Se for uma lista de requisições, pega o primeiro resultado
    if isinstance(j, list) and len(j) > 0 and "result" in j[0]:
        j = j[0]["result"]

    invariantes = []
    qs = j.get("quoteSummary")
    invariantes.append(("1. Envelope raiz 'quoteSummary' presente", isinstance(qs, dict)))

    if isinstance(qs, dict):
        res = qs.get("result")
        err = qs.get("error")
        invariantes.append(("2. Campo 'error' é estritamente nulo", err is None))
        invariantes.append(("3. Campo 'result' é uma lista com 1 elemento", isinstance(res, list) and len(res) == 1))

        if isinstance(res, list) and len(res) > 0:
            obj = res[0]
            invariantes.append(("4. Chave 'symbol' ausente no nível superior de result[0]", "symbol" not in obj))
            invariantes.append(("5. Módulos retornados como dicionários aninhados", all(isinstance(v, dict) for v in obj.values())))

            # Verificação de fração percentual
            pr = obj.get("price", {})
            raw_chg = pr.get("regularMarketChangePercent", {}).get("raw")
            if raw_chg is not None:
                invariantes.append(("6. Percentual 'regularMarketChangePercent' em fração (< 1.0)", abs(float(raw_chg)) < 1.0))

    for rotulo, cond in invariantes:
        st = p.pintar("CONFORME", "verde", negrito=True) if cond else p.pintar("VIOLAÇÃO", "vermelho", negrito=True)
        print(f"  [{st}] {rotulo}")

    aprovado = all(c for _, c in invariantes)
    print(f"\n  Status: {p.pintar('FIXTURE CERTIFICADA', 'verde') if aprovado else p.pintar('FIXTURE INVÁLIDA', 'vermelho')}\n")
    return aprovado


# ══════════════ Módulo 3: Explorador Interativo de Módulos ═══════════════════

def submenu_explorador_modulos(dados_ativo: Dict[str, Any], symbol: str, p: Palette, rnd: ConsoleRenderer):
    """Permite inspecionar em detalhes cada módulo retornado para o ativo."""
    modulos = sorted(list(dados_ativo.keys()))
    while True:
        try:
            print(f"\n {p.pintar(f'MÓDULOS DISPONÍVEIS PARA {symbol} ({len(modulos)} Módulos)', 'ambar', negrito=True)}")
            for idx, m in enumerate(modulos, 1):
                tamanho = len(dados_ativo[m]) if isinstance(dados_ativo[m], dict) else 1
                print(f"  [{idx:02d}] {pad_vis(m, 32, '<')} {p.pintar(f'({tamanho} campos/nós)', 'cinza_esc')}")
            print(f"  [00] Voltar")

            op = input(f"\n  {p.pintar('Escolha um módulo para visualizar:', 'branco', negrito=True)} ").strip()
            if op in ("0", "00", "v", "voltar"):
                break
            if op.isdigit() and 1 <= int(op) <= len(modulos):
                mod_escolhido = modulos[int(op) - 1]
                conteudo = dados_ativo[mod_escolhido]
                linhas = []
                for k, v in sorted(conteudo.items()) if isinstance(conteudo, dict) else [("valor", conteudo)]:
                    v_str = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                    linhas.append(f"{pad_vis(k, 30, '<')}: {v_str}")
                rnd.caixa(linhas, titulo=f"MÓDULO: {mod_escolhido} ({symbol})", cor_titulo="ciano")
            else:
                print(f"  {p.pintar('Opção inválida.', 'amarelo')}")
        except KeyboardInterrupt:
            break


# ══════════════ Módulo 4: Console de Requisições Brutas ═════════════════════

def console_requisicao_bruta(client: QuoteSummaryClient, p: Palette, rnd: ConsoleRenderer):
    print(f"\n {p.pintar('CONSOLE DE DIAGNÓSTICO & REQUISIÇÃO BRUTA (/v10)', 'ciano', negrito=True)}")
    print(f"  {p.pintar('Teste chamadas HTTP manuais, inspecione códigos e headers de resposta.', 'cinza_esc')}\n")

    symbol = (input(f"  {p.pintar('Símbolo [AAPL]:', 'branco', negrito=True)} ").strip().upper()) or "AAPL"
    modules_str = (input(f"  {p.pintar('Módulos CSV [price,summaryDetail]:', 'branco', negrito=True)} ").strip()) or "price,summaryDetail"
    host = (input(f"  {p.pintar('Host (query1/query2) [query1]:', 'branco', negrito=True)} ").strip().lower()) or HOST_QUERY1

    modules = [m.strip() for m in modules_str.split(",") if m.strip()]
    url = client.montar_url(symbol, modules, host=host)
    print(f"\n  {p.pintar('Disparando:', 'cinza_esc')} {p.pintar(url, 'azul')}")

    status, hdrs, corpo = client.net.request_raw(url)
    st_cor = "verde" if status == 200 else "vermelho"
    print(f"  {p.pintar('Resposta:', 'cinza_esc')} {p.pintar(f'HTTP {status}', st_cor, negrito=True)} | Latência: {client.net.ultima_latencia_ms:.1f}ms | Tamanho: {len(corpo)}B\n")

    rnd.caixa(
        [f"{k}: {v}" for k, v in list(hdrs.items())[:6]],
        titulo="CABEÇALHOS HTTP",
        cor_titulo="ciano"
    )

    amostra = corpo[:300].decode("utf-8", errors="replace")
    print(f"\n  {p.pintar('Corpo JSON Bruto (primeiros 300 bytes):', 'cinza_med')}")
    print(f"  {p.pintar(amostra, 'cinza_esc')}{'...' if len(corpo) > 300 else ''}\n")


# ════════════════════ Menu Principal & CLI Dispatcher ═══════════════════════

def menu_principal(client: QuoteSummaryClient, p: Palette, rnd: ConsoleRenderer):
    simbolo_atual = "AAPL"
    preset_atual = "producao"

    while True:
        try:
            print(f"\n {p.pintar('YAHOO FINANCE QUOTE SUMMARY v10 (Explorer)', 'ambar', negrito=True)}")
            print(f"  {p.pintar('Análise Fundamentalista & Estrutura Modular | Autenticado A3+Crumb', 'cinza_esc')}\n")

            print(f"  [1] Consultar Ativo Único (Atual: {p.pintar(simbolo_atual, 'ciano', negrito=True)} | Preset: {p.pintar(preset_atual, 'ambar')})")
            print(f"  [2] Alternar Ativo ou Preset")
            print(f"  [3] Tabela Resumo Comparativa (Magnificent 7)")
            print(f"  [4] Tabela Resumo Comparativa (Brasil B3 Blue Chips)")
            print(f"  [5] Console de Requisições Brutas (Diagnóstico)")
            print(f"  [6] Executar Suíte de Testes ao Vivo (8 Testes)")
            print(f"  [7] Auditoria Estrutural Offline (Fixture JSON)")
            print(f"  [8] Gestão de Sessão & Credenciais (A3 + Crumb)")
            print(f"  [9] Exportar Fixture JSON Crua do Ativo Atual")
            print(f"  [0] Encerrar Aplicativo")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                print(f"\n  {p.pintar('Sessão encerrada de forma limpa. Até logo!', 'ciano')}")
                break

            elif escolha == "1":
                modulos = PRESETS[preset_atual][1]
                print(f"  {p.pintar(f'Consultando {simbolo_atual} com {len(modulos)} módulos...', 'cinza_esc')}")
                try:
                    dados = client.summary(simbolo_atual, modulos, formatted=True, unwrap=True)
                    print(f"  {p.pintar(f'Sucesso! {len(dados)} módulos recebidos.', 'verde')}")
                    submenu_explorador_modulos(dados, simbolo_atual, p, rnd)
                except QuoteSummaryError as e:
                    print(f"  {p.pintar(f'[ERRO] {e}', 'vermelho')}")

            elif escolha == "2":
                s_inp = input(f"  {p.pintar(f'Novo símbolo [{simbolo_atual}]:', 'branco')} ").strip().upper()
                if s_inp:
                    try:
                        simbolo_atual = client.validar_simbolo(s_inp)
                    except QuoteSummaryError as e:
                        print(f"  {p.pintar(f'{e}', 'vermelho')}")

                print(f"\n  Presets Disponíveis:")
                presets_keys = list(PRESETS.keys())
                for i, k in enumerate(presets_keys, 1):
                    print(f"   [{i:02d}] {pad_vis(k, 16, '<')} - {PRESETS[k][0]}")
                pr_inp = input(f"  {p.pintar(f'Escolha o preset [atual: {preset_atual}]:', 'branco')} ").strip()
                if pr_inp.isdigit() and 1 <= int(pr_inp) <= len(presets_keys):
                    preset_atual = presets_keys[int(pr_inp) - 1]
                elif pr_inp in PRESETS:
                    preset_atual = pr_inp

            elif escolha == "3":
                print(f"\n  {p.pintar('Coletando dados do Magnificent 7 (1 req por ativo, cortesia 0.8s)...', 'cinza_esc')}")
                res = {}
                for s in MAGNIFICENT_7:
                    try:
                        res[s] = client.summary(s, ["price", "summaryDetail"])
                    except QuoteSummaryError as e:
                        res[s] = {"__erro__": {"code": e.code, "description": e.description}}
                    time.sleep(CORTESIA_SEGUNDOS)
                rnd.imprimir_tabela_resumo(res)

            elif escolha == "4":
                print(f"\n  {p.pintar('Coletando dados das Blue Chips B3 (1 req por ativo, cortesia 0.8s)...', 'cinza_esc')}")
                res = {}
                for s in BRAZIL_BLUE_CHIPS:
                    try:
                        res[s] = client.summary(s, ["price", "summaryDetail"])
                    except QuoteSummaryError as e:
                        res[s] = {"__erro__": {"code": e.code, "description": e.description}}
                    time.sleep(CORTESIA_SEGUNDOS)
                rnd.imprimir_tabela_resumo(res)

            elif escolha == "5":
                console_requisicao_bruta(client, p, rnd)

            elif escolha == "6":
                executar_suite_verificacao(client, p, rnd)

            elif escolha == "7":
                arq = input(f"  {p.pintar('Caminho do arquivo JSON [SPY.json]:', 'branco')} ").strip() or "SPY.json"
                executar_auditoria_offline(arq, p, rnd)

            elif escolha == "8":
                a3 = client.net.obter_a3_presente()
                rnd.caixa([
                    f"Cookie A3 no Jar : {p.pintar('Presente (' + str(len(a3)) + 'B)', 'verde') if a3 else p.pintar('Ausente', 'vermelho')}",
                    f"Token Crumb      : {p.pintar(client.net.crumb or 'Não emitido', 'verde' if client.net.crumb else 'amarelo')}",
                    f"Total Requisições: {client.net.total_requisicoes}",
                    f"Última Latência  : {client.net.ultima_latencia_ms:.1f} ms"
                ], titulo="ESTADO DA SESSÃO", cor_titulo="ciano")
                acao = input(f"\n  {p.pintar('Deseja renovar sessão agora? (s/n) [n]:', 'branco')} ").strip().lower()
                if acao == "s":
                    ok, msg = client.net.bootstrap_auth(verbose=True)
                    print(f"  {p.pintar(msg, 'verde' if ok else 'vermelho')}")

            elif escolha == "9":
                modulos = PRESETS[preset_atual][1]
                st, _, rb = client.summary_raw(simbolo_atual, modulos, formatted=True)
                if st == 200:
                    nome = f"quoteSummary_{simbolo_atual}_{int(time.time())}.json"
                    with open(nome, "wb") as f:
                        f.write(rb)
                    print(f"  {p.pintar(f'[OK] Arquivo salvo com paridade de bytes: {nome} ({len(rb)}B)', 'verde')}")
                else:
                    print(f"  {p.pintar(f'Falha ao exportar (HTTP {st})', 'vermelho')}")

        except KeyboardInterrupt:
            print(f"\n  {p.pintar('Operação cancelada.', 'amarelo')}")
        except EOFError:
            print(f"\n  {p.pintar('Saindo...', 'ciano')}")
            break
        except Exception as e:
            print(f"\n  {p.pintar(f'[ERRO] {e}', 'vermelho')}")


# ════════════════════════ Ponto de Entrada (Main) ═══════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="v10_finance_quoteSummary.py",
        description="Cliente de Terminal & Aplicativo Interativo do Endpoint /v10/finance/quoteSummary/{symbol}"
    )

    parser.add_argument("symbols", nargs="*", default=None, help="Símbolos alvo (ex: AAPL PETR4.SA)")
    parser.add_argument("--preset", choices=list(PRESETS.keys()), default="resumo", help="Preset de módulos")
    parser.add_argument("--modules", "-m", default=None, help="Módulos customizados separados por vírgula")
    parser.add_argument("--raw", action="store_true", help="formatted=false (números primitivos)")
    parser.add_argument("--wrap", action="store_true", help="Preserva invólucro {raw, fmt} na saída")
    parser.add_argument("--table", action="store_true", help="Exibe resumo tabular em vez de JSON")
    parser.add_argument("--json", action="store_true", help="Gera saída JSON pura (paridade de bytes)")
    parser.add_argument("--test-live", action="store_true", help="Executa suíte de testes ao vivo e sai")
    parser.add_argument("--audit", metavar="ARQ", default=None, help="Audita estruturalmente fixture offline")
    parser.add_argument("--host", choices=[HOST_QUERY1, HOST_QUERY2], default=HOST_QUERY1, help="Host edge")
    parser.add_argument("--ascii", action="store_true", help="Usa molduras ASCII simples (+---+)")
    parser.add_argument("--sem-cores", "--no-color", action="store_true", help="Desativa saída de cores ANSI")
    parser.add_argument("--no-pause", action="store_true", help="Não pausa com ENTER ao finalizar")

    args = parser.parse_args()

    # Inicialização visual
    usa_cores = not args.sem_cores and os.environ.get("NO_COLOR") is None
    p = Palette(enabled=usa_cores)
    b = BoxChars(ascii_mode=args.ascii)
    rnd = ConsoleRenderer(p, b)

    # Inicialização de rede
    net = NetworkEngine()
    client = QuoteSummaryClient(net, default_host=args.host)

    try:
        # Modo 1: Auditoria Offline
        if args.audit:
            return 0 if executar_auditoria_offline(args.audit, p, rnd) else 1

        # Modo 2: Suíte de Testes ao Vivo
        if args.test_live:
            return 0 if executar_suite_verificacao(client, p, rnd) else 1

        # Modo 3: Consulta CLI Direta
        if args.symbols:
            modules = [m.strip() for m in args.modules.split(",") if m.strip()] if args.modules else PRESETS[args.preset][1]
            formatted = not args.raw

            # Se for pedido JSON puro de 1 ativo
            if args.json and len(args.symbols) == 1:
                st, _, raw_bytes = client.summary_raw(args.symbols[0], modules, formatted=formatted)
                sys.stdout.buffer.write(raw_bytes)
                sys.stdout.buffer.write(b"\n")
                return 0

            resultados = {}
            for s in args.symbols:
                try:
                    resultados[s] = client.summary(s, modules, formatted=formatted, unwrap=not args.wrap)
                except QuoteSummaryError as e:
                    resultados[s] = {"__erro__": {"code": e.code, "description": e.description}}
                if len(args.symbols) > 1:
                    time.sleep(CORTESIA_SEGUNDOS)

            if args.table:
                rnd.imprimir_tabela_resumo(resultados)
            else:
                print(json.dumps(resultados, indent=2, ensure_ascii=False))
            return 0

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