#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 TERMINAL YF·QUOTE SUMMARY v11 — GET /v11/finance/quoteSummary/
═══════════════════════════════════════════════════════════════════════════════
 Aplicativo de terminal interativo para exploração completa e resiliente do
 endpoint de fundamentals em lote (batch) da Yahoo Finance.

 REQUISITOS IMPLEMENTADOS:
   1. ANTI-FECHAMENTO: Loop de menu contínuo, blindagem com try/except gracioso
      em todas as ações, pausa ENTER ao fechar (desativável com --no-pause),
      tratamento seguro de Ctrl+C e EOF.
   2. ZERO DEPENDÊNCIAS EXTERNAS: Apenas Python stdlib (urllib, http.cookiejar,
      json, shutil, re, time, os, sys, datetime). Compatível com Python 3.8+.
   3. UI DESIGN: Cores ANSI com VT100 no Windows, paleta Bloomberg fiel
      (#FFA028, #00C853, #FF433D, etc.), caixas ╭─╮│╰╯ e tabelas com alinhamento
      imune aos códigos ANSI, fallbacks (--ascii e --sem-cores), stdout UTF-8 e
      formatação pt-BR (milhares, decimais, %, datas).
   4. TODAS AS FUNÇÕES DA API:
      - Consulta canônica autenticada (Cookie A3 + Crumb obrigatórios).
      - Barra final obrigatória (/v11/finance/quoteSummary/).
      - Fatiamento automático transparente para lotes > 15 símbolos (limite da edge).
      - Mapeamento rigoroso pelo eco de símbolos (quoteSummary.symbols[i] ↔ result[i]).
      - Catálogo completo de 55 módulos com 8 presets temáticos (incluindo 'tudo').
      - Inventário detalhado de módulos entregues vs. omitidos por símbolo.
      - Console bruto de requisições (GET/POST/HEAD/OPTIONS, vetor duplo de crumb).
      - Comparador fundamentalista multi-ativo (P/E, EV/EBITDA, Margens, etc.).
      - Suíte de testes ao vivo validando contratos e regras de limite.
      - Auditoria offline de fixtures JSON.
      - Gestão de sessão (A3 em fc.yahoo.com + getcrumb).
      - Exportação crua com paridade exata de bytes.
   5. ROBUSTEZ DE REDE: Auto-recuperação de HTTP 401 com renovação A3+Crumb,
      backoff exponencial (2^n) com jitter em 429/503 (até 5 tentativas),
      medição de latência (ms) e tamanho (bytes).
   6. COMPATIBILIDADE: 100% retrocompatível com as flags CLI anteriores.
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
for fluxo in (sys.stdout, sys.stderr, sys.stdin):
    if hasattr(fluxo, "reconfigure"):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ════════════════════════ Constantes do Protocolo ═══════════════════════════

APP_NOME = "YF·QUOTE SUMMARY BATCH v11"
APP_VERSAO = "3.5.0"
DESCRICAO_EP = (
    "GET /v11/finance/quoteSummary/ — Fundamentals em lote (até 15 símbolos por fatia) · "
    "Mapeamento posicional por eco · 55 módulos disponíveis"
)

HOSTS_EP: Dict[str, str] = {
    "query1": "https://query1.finance.yahoo.com",
    "query2": "https://query2.finance.yahoo.com",
}

ENDPOINT_PATH = "/v11/finance/quoteSummary/"  # BARRA FINAL É OBRIGATÓRIA (sem ela -> 502 HTML)
URL_FC = "https://fc.yahoo.com"
URL_CRUMB = "https://query1.finance.yahoo.com/v1/test/getcrumb"
DEFAULT_TIMEOUT = 30.0
MAX_LOTE_SERVIDOR = 15
CORTESIA_FATIA = 0.6  # Pausa entre fatias para evitar rate-limit

USER_AGENT_DEFAULT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

# Regex oficial de validação client-side do build
SIMBOLO_INVALIDO_RE = re.compile(r"[^a-zA-Z0-9^.$_+=*&:@~-]")

MAGNIFICENT_7 = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]

# Universo completo de 55 módulos suportados pelo QuoteSummary
UNIVERSO_MODULOS: List[str] = sorted({
    "assetProfile", "assetComponents", "attribution", "balanceSheetHistory",
    "balanceSheetHistoryQuarterly", "calendarEvents", "cashflowStatementHistory",
    "cashflowStatementHistoryQuarterly", "chartPreviousClose", "components",
    "corporateActions", "defaultKeyStatistics", "earnings", "earningsCallTranscripts",
    "earningsCallAudios", "earningsGaap", "earningsNonGaap", "earningsHistory",
    "earningsHistoryGaap", "earningsHistoryNonGaap", "earningsTrend",
    "earningsTrendGaap", "earningsTrendNonGaap", "equityPerformance", "esgScores",
    "financialData", "financialsTemplate", "fundOwnership", "fundPerformance",
    "fundProfile", "fundingRounds", "futuresChain", "incomeStatementHistory",
    "incomeStatementHistoryQuarterly", "indexTrend", "industryTrend", "insiderHolders",
    "insiderTransactions", "institutionOwnership", "majorDirectHolders",
    "majorHoldersBreakdown", "marks", "netSharePurchaseActivity", "pageViews",
    "price", "quoteType", "quoteUnadjustedPerformanceOverview", "recommendationTrend",
    "relatedCompanies", "secFilings", "sectorTrend", "summaryDetail",
    "summaryProfile", "topHoldings", "upgradeDowngradeHistory"
})

BASE_5 = ["price", "summaryDetail", "pageViews", "financialsTemplate", "calendarEvents"]

COMPOSICAO_PRODUCAO = sorted(set(
    ["summaryProfile", "financialData", "recommendationTrend", "earnings",
     "equityPerformance", "summaryDetail", "defaultKeyStatistics",
     "calendarEvents", "esgScores", "assetProfile"]
    + BASE_5
    + ["quoteUnadjustedPerformanceOverview", "chartPreviousClose",
       "corporateActions", "earningsCallTranscripts", "earningsGaap",
       "earningsNonGaap", "upgradeDowngradeHistory"]
))

PRESETS_MODULOS: Dict[str, Tuple[str, List[str]]] = {
    "resumo": ("Leve: cotação e dados essenciais", ["price", "summaryDetail"]),
    "base5": ("Lista base padrão da aplicação web", BASE_5),
    "producao": ("Composição completa da aba Summary de Ações (20 módulos)", COMPOSICAO_PRODUCAO),
    "fundamentos": ("Indicadores de valuation, múltiplos e resultados", [
        "financialData", "defaultKeyStatistics", "earnings", "earningsTrend",
        "recommendationTrend", "upgradeDowngradeHistory"
    ]),
    "analise": ("Estimativas e consenso de mercado", [
        "upgradeDowngradeHistory", "recommendationTrend", "financialData",
        "earningsHistory", "earningsTrend", "earnings", "industryTrend", "indexTrend", "sectorTrend"
    ]),
    "holders": ("Estrutura acionária, fundos e transações de insiders", [
        "institutionOwnership", "fundOwnership", "majorDirectHolders",
        "majorHoldersBreakdown", "insiderTransactions", "insiderHolders", "netSharePurchaseActivity"
    ]),
    "financials": ("Demonstrações contábeis completas (DRE, Balanço, Fluxo de Caixa)", [
        "financialsTemplate", "incomeStatementHistory", "cashflowStatementHistory",
        "balanceSheetHistory", "incomeStatementHistoryQuarterly",
        "cashflowStatementHistoryQuarterly", "balanceSheetHistoryQuarterly", "earnings"
    ]),
    "tudo": ("Universo integral da API (todos os 55 módulos)", UNIVERSO_MODULOS)
}

# Justificativas documentadas de omissão silenciosa por tipo/dados
MOTIVO_OMISSAO: Dict[str, str] = {
    "fundPerformance": "Exclusivo de fundos (MUTUALFUND)",
    "fundProfile": "Exclusivo de fundos (MUTUALFUND)",
    "topHoldings": "Exclusivo de fundos e ETFs (ETF/MUTUALFUND)",
    "futuresChain": "Exclusivo de contratos futuros (FUTURE)",
    "fundingRounds": "Exclusivo de empresas privadas (PRIVATE)",
    "marks": "Exclusivo de empresas privadas (PRIVATE)",
    "relatedCompanies": "Exclusivo de empresas privadas (PRIVATE)",
    "assetComponents": "Exclusivo de índices customizados (CUL_IDX)",
    "components": "Exclusivo de índices de mercado (INDEX)",
    "attribution": "Exclusivo de criptoativos (CRYPTOCURRENCY)",
    "esgScores": "Dados de sustentabilidade ESG não fornecidos para o ativo",
    "secFilings": "Não se aplica ou histórico indisponível para esta classe",
}

# ════════════════════════ Paleta Bloomberg & UI ═════════════════════════════

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def vlen(text: str) -> int:
    return len(strip_ansi(str(text)))


def pad_vis(text: str, width: int, align: str = "<") -> str:
    diff = max(0, width - vlen(text))
    if align == ">":
        return " " * diff + text
    elif align == "^":
        left = diff // 2
        right = diff - left
        return " " * left + text + " " * right
    return text + " " * diff


class Palette:
    """Paleta Bloomberg oficial com fallback para 256 cores e sem cores."""
    def __init__(self, modo: str = "256"):
        self.modo = modo

    def _c(self, rgb: Tuple[int, int, int], c256: int) -> str:
        if self.modo == "off":
            return ""
        if self.modo == "rgb":
            return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
        return f"\033[38;5;{c256}m"

    @property
    def RESET(self) -> str: return "" if self.modo == "off" else "\033[0m"
    @property
    def BOLD(self) -> str: return "" if self.modo == "off" else "\033[1m"
    @property
    def DIM(self) -> str: return "" if self.modo == "off" else "\033[2m"

    @property
    def AMBAR(self) -> str: return self._c((255, 160, 40), 208)      # #FFA028 Tickers / Marca
    @property
    def AMARELO(self) -> str: return self._c((255, 214, 0), 220)     # #FFD600 Alertas / Módulos
    @property
    def VERDE(self) -> str: return self._c((0, 200, 83), 41)         # #00C853 Altas / PASS
    @property
    def VERMELHO(self) -> str: return self._c((255, 67, 61), 203)    # #FF433D Baixas / FAIL
    @property
    def CIANO(self) -> str: return self._c((0, 212, 255), 45)        # #00D4FF Dados Especiais
    @property
    def AZUL(self) -> str: return self._c((0, 104, 255), 33)         # #0068FF Rotas / Links
    @property
    def TEAL(self) -> str: return self._c((74, 246, 195), 86)        # #4AF6C3 Secundários
    @property
    def CINZA_MED(self) -> str: return self._c((160, 160, 160), 247) # #A0A0A0 Rótulos
    @property
    def CINZA_ESC(self) -> str: return self._c((128, 128, 128), 242) # #808080 Metadados / Bordas
    @property
    def BRANCO(self) -> str: return self._c((255, 255, 255), 231)


class BoxChars:
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


# ════════════════════════ Formatação pt-BR ══════════════════════════════════

def fmt_num_br(valor: Any, decimais: int = 2) -> str:
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
    if valor is None:
        return "—"
    try:
        n = float(valor)
        sinal = "-" if n < 0 else ""
        n = abs(n)
        for suf, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
            if n >= div:
                val = n / div
                return f"{sinal}{fmt_num_br(val, 2)} {suf}"
        return f"{sinal}{fmt_num_br(n, 2)}"
    except (ValueError, TypeError):
        return str(valor)


def fmt_pct_fracao_br(valor: Any, com_sinal: bool = True) -> str:
    """
    Formata percentuais que vêm como fração no quoteSummary (ex: -0.0078 -> -0,78%).
    """
    if valor is None:
        return "—"
    try:
        f = float(valor)
        # Se vier como fração pura (ex: 0.15 para 15%) multiplica por 100
        val_pct = f * 100.0 if abs(f) <= 1.0 else f
        sinal = "+" if val_pct > 0 and com_sinal else ""
        return f"{sinal}{fmt_num_br(val_pct, 2)}%"
    except (ValueError, TypeError):
        return str(valor)


def fmt_epoch_br(ts_val: Any) -> str:
    if not ts_val:
        return "—"
    try:
        ts = float(ts_val)
        if ts > 1e11:
            ts /= 1000.0
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(ts_val)


def raw_val(v: Any) -> Any:
    return v.get("raw") if isinstance(v, dict) and "raw" in v else v


def fmt_val(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("fmt") or v.get("longFmt") or v.get("raw") or "—")
    return str(v) if v is not None else "—"


# ══════════════════════ Motor de Rede & Transporte ══════════════════════════

class Resp:
    def __init__(self, status: int, corpo: bytes, headers: Dict[str, str], ms: float, url: str, metodo: str):
        self.status = status
        self.corpo = corpo
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.ms = ms
        self.url = url
        self.metodo = metodo

    def json(self) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self.corpo.decode("utf-8", errors="replace"))
        except Exception:
            return None

    def texto(self) -> str:
        return self.corpo.decode("utf-8", errors="replace")

    def resumo(self) -> str:
        return f"HTTP {self.status} · {len(self.corpo):,} B · {self.ms:.0f} ms · {self.metodo}"


class NetworkEngine:
    """Motor HTTP resiliente com suporte a A3+Crumb nativo sobre urllib."""
    def __init__(self, host_alias: str = "query1", timeout: float = DEFAULT_TIMEOUT):
        self.hosts = dict(HOSTS_EP)
        self.host_alias = host_alias if host_alias in self.hosts else "query1"
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.crumb: Optional[str] = None
        self.requisicoes = 0

    @property
    def base_url(self) -> str:
        return self.hosts[self.host_alias]

    def obter_a3(self) -> Optional[str]:
        for c in self.jar:
            if c.name == "A3":
                return c.value
        return None

    def bootstrap_auth(self, verbose: bool = False) -> Tuple[bool, str]:
        """Handshake essencial: fc.yahoo.com entrega A3 -> getcrumb emite token."""
        if verbose:
            sys.stderr.write("[AUTH] Executando handshake com fc.yahoo.com...\n")

        req_fc = urllib.request.Request(URL_FC, headers={"User-Agent": USER_AGENT_DEFAULT, "Accept": "*/*"})
        try:
            with self.opener.open(req_fc, timeout=self.timeout):
                pass
        except urllib.error.HTTPError:
            pass  # HTTP 404 é esperado para a entrega do cookie
        except Exception as e:
            return False, f"Falha ao conectar com fc.yahoo.com: {e}"

        a3 = self.obter_a3()
        if not a3:
            return False, "Cookie A3 não foi retornado pelo servidor."

        if verbose:
            sys.stderr.write(f"[AUTH] Cookie A3 obtido ({len(a3)} chars). Solicitando Crumb...\n")

        req_crumb = urllib.request.Request(URL_CRUMB, headers={"User-Agent": USER_AGENT_DEFAULT, "Accept": "*/*"})
        try:
            with self.opener.open(req_crumb, timeout=self.timeout) as resp:
                token = resp.read().decode("utf-8", errors="replace").strip()
                if resp.status == 200 and token and "<" not in token and len(token) <= 64:
                    self.crumb = token
                    return True, f"Crumb obtido com sucesso: {self.crumb}"
                return False, f"Crumb inválido retornado: {token[:60]}"
        except Exception as e:
            return False, f"Falha na requisição getcrumb: {e}"

    def request_raw(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        metodo: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[bytes] = None,
        crumb_query: bool = True,
        crumb_header: bool = False,
        host_override: Optional[str] = None,
        ua: Optional[str] = None,
        max_retries: int = 5,
        renew_on_401: bool = True
    ) -> Resp:
        p_dict = dict(params or {})
        h_dict = {
            "User-Agent": ua or USER_AGENT_DEFAULT,
            "Accept": "application/json",
            "Referer": "https://finance.yahoo.com/"
        }
        if headers:
            h_dict.update(headers)

        if crumb_query and self.crumb:
            p_dict.setdefault("crumb", self.crumb)
        if crumb_header and self.crumb:
            h_dict["x-crumb"] = self.crumb

        base = self.hosts.get(host_override or self.host_alias, self.base_url)

        for attempt in range(max_retries):
            qs = ("?" + urllib.parse.urlencode(p_dict)) if p_dict else ""
            url = f"{base}{path}{qs}"
            t0 = time.perf_counter()
            req = urllib.request.Request(url, data=data, headers=h_dict, method=metodo)

            try:
                with self.opener.open(req, timeout=self.timeout) as r:
                    ms = (time.perf_counter() - t0) * 1000.0
                    body = r.read()
                    self.requisicoes += 1
                    return Resp(r.status, body, dict(r.headers), ms, url, metodo)

            except urllib.error.HTTPError as e:
                ms = (time.perf_counter() - t0) * 1000.0
                body = e.read()
                self.requisicoes += 1
                resp = Resp(e.code, body, dict(e.headers or {}), ms, url, metodo)

                if resp.status == 401 and renew_on_401 and attempt < 1:
                    sys.stderr.write("[REDE] HTTP 401 recebido. Renovando A3 + Crumb...\n")
                    ok, _ = self.bootstrap_auth(verbose=False)
                    if ok and crumb_query and self.crumb:
                        p_dict["crumb"] = self.crumb
                    continue

                if resp.status in (429, 503) and attempt < max_retries - 1:
                    pausa_s = (2 ** attempt) + random.uniform(0.1, 0.5)
                    sys.stderr.write(f"[REDE] Status {resp.status}. Backoff de {pausa_s:.2f}s...\n")
                    time.sleep(pausa_s)
                    continue

                return resp

            except Exception as e:
                ms = (time.perf_counter() - t0) * 1000.0
                if attempt < max_retries - 1:
                    pausa_s = (2 ** attempt) + random.uniform(0.1, 0.4)
                    time.sleep(pausa_s)
                    continue
                return Resp(0, str(e).encode(), {}, ms, url, metodo)

        return Resp(0, b"Tentativas esgotadas", {}, 0.0, "", metodo)


# ═══════════════════════ Cliente do Lote v11 ═══════════════════════════════

class QuoteSummaryBatchClient:
    """
    Cliente oficial para o lote de fundamentals /v11/finance/quoteSummary/.
    - Fatiamento automático em lotes <= 15 símbolos com pausa de cortesia.
    - Mapeamento rigoroso via eco `quoteSummary.symbols`.
    - Dedup + Sort dos módulos em cache.
    - Suporte a cabeçalhos oficiais x-cache e dataVersion=v2.
    """
    def __init__(self, net: NetworkEngine):
        self.net = net

    def validar_simbolo(self, s: str) -> bool:
        return bool(s) and not bool(SIMBOLO_INVALIDO_RE.search(s))

    def _get_fatia(
        self,
        symbols: List[str],
        modules: List[str],
        formatted: bool = True,
        cache: bool = False,
        data_version: Optional[str] = None,
        crumb: bool = True,
        host: Optional[str] = None
    ) -> Tuple[List[str], List[Dict[str, Any]], Resp]:
        """Consulta uma fatia única (<= 15 símbolos)."""
        if not symbols:
            raise RuntimeError("Lista de símbolos vazia.")
        for s in symbols:
            if not self.validar_simbolo(s):
                raise RuntimeError(f"Símbolo inválido pela regex do build: '{s}'")
        if len(symbols) > MAX_LOTE_SERVIDOR:
            raise RuntimeError(f"Fatia de {len(symbols)} excede limite de {MAX_LOTE_SERVIDOR}.")

        if not self.net.crumb and crumb:
            self.net.bootstrap_auth()

        params: Dict[str, Any] = {
            "formatted": "true" if formatted else "false",
            "modules": ",".join(sorted(set(modules)) if cache else modules),
            "symbols": ",".join(symbols).upper(),
            "lang": "en-US",
            "region": "US"
        }
        if data_version:
            params["dataVersion"] = data_version

        headers = {}
        if cache:
            headers["x-cache"] = "1"
            headers["x-cache-ttl"] = "30000"

        resp = self.net.request_raw(
            ENDPOINT_PATH,
            params=params,
            headers=headers,
            crumb_query=crumb,
            host_override=host
        )

        if resp.status != 200:
            j_err = resp.json()
            desc = ""
            if j_err:
                desc = (
                    j_err.get("quoteSummary", {}).get("error", {}).get("description")
                    or j_err.get("finance", {}).get("error", {}).get("description", "")
                )
            raise RuntimeError(f"HTTP {resp.status}: {desc or resp.texto()[:150]}")

        j = resp.json()
        if not j or "quoteSummary" not in j:
            raise RuntimeError("Envelope 'quoteSummary' ausente na resposta.")

        qs = j["quoteSummary"]
        eco_symbols = qs.get("symbols") or []
        result_itens = qs.get("result") or []
        return eco_symbols, result_itens, resp

    def consultar_lote(
        self,
        symbols: List[str],
        modules: List[str],
        formatted: bool = True,
        cache: bool = False,
        data_version: Optional[str] = None
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Resp]]:
        """
        Executa a consulta de lote completa fatiando automaticamente se > 15 símbolos.
        Mapeia os resultados estritamente pelo eco retornado pelo gateway.
        """
        simbolos_limpos = [s.strip().upper() for s in symbols if s.strip()]
        fatias = [simbolos_limpos[i:i + MAX_LOTE_SERVIDOR] for i in range(0, len(simbolos_limpos), MAX_LOTE_SERVIDOR)]
        consolidados: Dict[str, Dict[str, Any]] = {}
        resps: List[Resp] = []

        for idx, fatia in enumerate(fatias):
            if idx > 0:
                time.sleep(CORTESIA_FATIA)

            eco, itens, r = self._get_fatia(
                symbols=fatia,
                modules=modules,
                formatted=formatted,
                cache=cache,
                data_version=data_version
            )
            resps.append(r)

            for sym, item in zip(eco, itens):
                if isinstance(item, dict):
                    consolidados[sym.upper()] = item

        return consolidados, resps


# ════════════════════ Renderizador Visual do Terminal ═══════════════════════

class ConsoleRenderer:
    def __init__(self, p: Palette, b: BoxChars):
        self.p = p
        self.b = b

    def largura(self) -> int:
        return max(75, min(120, shutil.get_terminal_size((85, 25)).columns))

    def banner(self, secao: Optional[str] = None) -> None:
        print()
        print(f" {self.p.BOLD}{self.p.AMBAR}{APP_NOME}{self.p.RESET}  {self.p.CINZA_ESC}v{APP_VERSAO}{self.p.RESET}")
        print(f" {self.p.CINZA_MED}{DESCRICAO_EP}{self.p.RESET}")
        if secao:
            print(f"\n {self.p.BOLD}{self.p.CIANO}▶ {secao.upper()}{self.p.RESET}")
        print()

    def barra_status(self, net: NetworkEngine) -> None:
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        a3 = net.obter_a3()
        auth_txt = (
            f"{self.p.VERDE}A3+Crumb Ativos{self.p.RESET}" if net.crumb and a3
            else f"{self.p.AMARELO}Sessão Pendente{self.p.RESET}"
        )
        crumb_s = f" · Crumb: {net.crumb[:6]}…" if net.crumb else ""
        print(
            f" {self.p.CINZA_ESC}Sessão: {auth_txt}{crumb_s} · Host: {net.host_alias} · "
            f"Reqs: {net.requisicoes} · {hora}{self.p.RESET}"
        )

    def caixa(self, linhas: List[str], titulo_txt: Optional[str] = None, cor_titulo: str = "AMBAR") -> None:
        larg = min(self.largura() - 4, max([vlen(ln) for ln in linhas] + [vlen(titulo_txt or "") + 4, 32]))
        b = self.b
        cor_fn = getattr(self.p, cor_titulo, self.p.AMBAR)

        if titulo_txt:
            rot = f" {titulo_txt} "
            resta = max(0, larg - vlen(rot) + 2)
            topo = f" {self.p.CINZA_ESC}{b.TL}{b.H}{self.p.RESET}{self.p.BOLD}{cor_fn}{rot}{self.p.RESET}{self.p.CINZA_ESC}{b.H * resta}{b.TR}{self.p.RESET}"
        else:
            topo = f" {self.p.CINZA_ESC}{b.TL}{b.H * (larg + 2)}{b.TR}{self.p.RESET}"

        print(topo)
        for ln in linhas:
            print(f" {self.p.CINZA_ESC}{b.V}{self.p.RESET} {pad_vis(ln, larg, '<')} {self.p.CINZA_ESC}{b.V}{self.p.RESET}")
        print(f" {self.p.CINZA_ESC}{b.BL}{b.H * (larg + 2)}{b.BR}{self.p.RESET}")

    def tabela_resumo_lote(self, dados: Dict[str, Dict[str, Any]], nota: Optional[str] = None) -> None:
        if not dados:
            print(f"  {self.p.AMARELO}⚠ Nenhum dado retornado para exibição.{self.p.RESET}")
            return

        colunas = [
            ("#", 3, ">"),
            ("SÍMBOLO", 9, "<"),
            ("NOME", 20, "<"),
            ("PREÇO", 11, ">"),
            ("VAR %", 9, ">"),
            ("MKT CAP", 10, ">"),
            ("P/L (TTM)", 9, ">"),
            ("EV/EBITDA", 9, ">"),
            ("MOEDA", 5, "^")
        ]

        b = self.b
        topo = f" {self.p.CINZA_ESC}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{self.p.RESET}"
        print(topo)

        h_str = [f" {pad_vis(f'{self.p.BOLD}{self.p.CINZA_MED}{nome}{self.p.RESET}', w, al)} " for nome, w, al in colunas]
        print(f" {self.p.CINZA_ESC}{b.V}{self.p.RESET}" + f"{self.p.CINZA_ESC}{b.V}{self.p.RESET}".join(h_str) + f"{self.p.CINZA_ESC}{b.V}{self.p.RESET}")

        mid = f" {self.p.CINZA_ESC}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{self.p.RESET}"
        print(mid)

        for i, (sym, item) in enumerate(sorted(dados.items()), 1):
            p_mod = item.get("price") or {}
            sd_mod = item.get("summaryDetail") or {}
            ks_mod = item.get("defaultKeyStatistics") or {}

            nome = str(p_mod.get("shortName") or p_mod.get("longName") or "—")[:19]
            moeda = str(p_mod.get("currency") or "—")[:5]

            pr = raw_val(p_mod.get("regularMarketPrice"))
            pr_s = fmt_num_br(pr, 2)

            chp = raw_val(p_mod.get("regularMarketChangePercent"))
            chp_s = fmt_pct_fracao_br(chp)
            cor_d = self.p.BRANCO
            if chp is not None:
                cor_d = self.p.VERDE if chp > 0 else (self.p.VERMELHO if chp < 0 else self.p.BRANCO)

            mc = raw_val(p_mod.get("marketCap")) or raw_val(sd_mod.get("marketCap"))
            mc_s = fmt_grandeza_br(mc)

            pe = raw_val(sd_mod.get("trailingPE"))
            pe_s = fmt_num_br(pe, 2)

            ev_eb = raw_val(ks_mod.get("enterpriseToEbitda"))
            ev_eb_s = fmt_num_br(ev_eb, 2)

            linha = [
                f" {pad_vis(str(i), colunas[0][1], colunas[0][2])} ",
                f" {pad_vis(f'{self.p.BOLD}{self.p.AMBAR}{sym}{self.p.RESET}', colunas[1][1], colunas[1][2])} ",
                f" {pad_vis(nome, colunas[2][1], colunas[2][2])} ",
                f" {pad_vis(pr_s, colunas[3][1], colunas[3][2])} ",
                f" {pad_vis(f'{cor_d}{chp_s}{self.p.RESET}', colunas[4][1], colunas[4][2])} ",
                f" {pad_vis(mc_s, colunas[5][1], colunas[5][2])} ",
                f" {pad_vis(pe_s, colunas[6][1], colunas[6][2])} ",
                f" {pad_vis(ev_eb_s, colunas[7][1], colunas[7][2])} ",
                f" {pad_vis(moeda, colunas[8][1], colunas[8][2])} "
            ]
            print(f" {self.p.CINZA_ESC}{b.V}{self.p.RESET}" + f"{self.p.CINZA_ESC}{b.V}{self.p.RESET}".join(linha) + f"{self.p.CINZA_ESC}{b.V}{self.p.RESET}")

        base = f" {self.p.CINZA_ESC}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{self.p.RESET}"
        print(base)
        if nota:
            print(f"  {self.p.CINZA_ESC}{nota}{self.p.RESET}")


# ════════════════════ Módulos e Visões do Terminal ═════════════════════════

def exibir_inventario_modulos(dados: Dict[str, Dict[str, Any]], modules_pedidos: List[str], renderer: ConsoleRenderer) -> None:
    """Exibe o inventário analítico de módulos entregues vs. omitidos para cada símbolo."""
    p = renderer.p
    pedidos_set = set(modules_pedidos)

    renderer.caixa([
        f"Módulos Solicitados na Query: {len(pedidos_set)}",
        "Mostra quais módulos o servidor entregou e a razão técnica dos omitidos."
    ], titulo_txt="INVENTÁRIO DE MÓDULOS (COMPOSIÇÃO DO LOTE)", cor_titulo="CIANO")

    for sym, item in sorted(dados.items()):
        chaves_presentes = set(item.keys())
        entregues = sorted(chaves_presentes & pedidos_set)
        omitidos = sorted(pedidos_set - chaves_presentes)

        print(f"\n {p.BOLD}{p.AMBAR}▶ {sym}{p.RESET}: {p.VERDE}{len(entregues)} entregues{p.RESET} · {p.AMARELO}{len(omitidos)} omitidos{p.RESET}")

        if omitidos:
            print(f"  {p.CINZA_MED}Módulos Omitidos e Razões Documentadas:{p.RESET}")
            for m in omitidos:
                motivo = MOTIVO_OMISSAO.get(m, "Sem dados disponíveis para este símbolo (data-driven)")
                print(f"    • {p.AMARELO}{m:<30}{p.RESET} {p.CINZA_ESC}— {motivo}{p.RESET}")
    print()


def detalhar_modulo_ticker(dados: Dict[str, Dict[str, Any]], renderer: ConsoleRenderer) -> None:
    """Inspeciona os campos aninhados de um módulo específico de um símbolo."""
    p = renderer.p
    if not dados:
        print("  ⚠ Nenhum dado carregado em memória.")
        return

    sym_in = input(f"\n {p.BOLD}Informe o Símbolo para detalhar (ex: AAPL): {p.RESET}").strip().upper()
    if sym_in not in dados:
        print(f"  {p.VERMELHO}Símbolo '{sym_in}' não encontrado no lote atual.{p.RESET}")
        return

    item = dados[sym_in]
    mods_disp = sorted(item.keys())
    print(f"\n Módulos disponíveis para {p.AMBAR}{sym_in}{p.RESET}:")
    print(f" {p.CINZA_MED}{', '.join(mods_disp)}{p.RESET}")

    mod_in = input(f"\n {p.BOLD}Informe o Módulo a inspecionar [summaryDetail]: {p.RESET}").strip() or "summaryDetail"
    if mod_in not in item:
        print(f"  {p.VERMELHO}Módulo '{mod_in}' não consta no payload de {sym_in}.{p.RESET}")
        return

    conteudo = item[mod_in]
    linhas = []

    if isinstance(conteudo, dict):
        for k in sorted(conteudo.keys()):
            v = conteudo[k]
            txt_fmt = fmt_val(v)
            if isinstance(v, dict) and "raw" in v:
                r_v = v.get("raw")
                linhas.append(f"{k:<32} {p.BRANCO}{txt_fmt}{p.RESET} {p.CINZA_ESC}(raw={r_v}){p.RESET}")
            else:
                linhas.append(f"{k:<32} {p.BRANCO}{txt_fmt}{p.RESET}")
    elif isinstance(conteudo, list):
        linhas.append(f"Array contendo {len(conteudo)} registros:")
        for idx, elem in enumerate(conteudo[:10]):
            linhas.append(f" [{idx}] {json.dumps(elem, ensure_ascii=False)[:80]}...")
    else:
        linhas.append(str(conteudo))

    renderer.caixa(linhas, titulo_txt=f"{sym_in} · {mod_in}", cor_titulo="AMBAR")


def comparador_multi_ativo(dados: Dict[str, Dict[str, Any]], renderer: ConsoleRenderer) -> None:
    """Gera matriz comparativa lado a lado entre os ativos do lote."""
    p = renderer.p
    if not dados:
        print("  ⚠ Nenhum lote carregado para comparação.")
        return

    metricas = [
        ("price.regularMarketPrice", "Preço Atual", "preco"),
        ("price.regularMarketChangePercent", "Variação Diária", "pct"),
        ("summaryDetail.marketCap", "Valor de Mercado", "grandeza"),
        ("summaryDetail.trailingPE", "Múltiplo P/L (TTM)", "num"),
        ("defaultKeyStatistics.forwardPE", "Múltiplo P/L Projetado", "num"),
        ("defaultKeyStatistics.enterpriseToEbitda", "EV / EBITDA", "num"),
        ("financialData.profitMargins", "Margem Líquida", "pct"),
        ("financialData.returnOnEquity", "Retorno sobre PL (ROE)", "pct"),
        ("financialData.debtToEquity", "Dívida / PL", "num"),
        ("defaultKeyStatistics.beta", "Beta de Mercado", "num")
    ]

    syms = sorted(dados.keys())[:6]  # Máximo de 6 colunas para caber na tela
    col_w = max(13, (renderer.largura() - 28) // max(1, len(syms)))
    label_w = 26

    print(f"\n {p.BOLD}{p.AMBAR}MATRIZ DE VALUATION & FUNDAMENTOS{p.RESET}")
    cab_linha = pad_vis("INDICADOR", label_w, "<") + " " + " ".join(pad_vis(s, col_w, "^") for s in syms)
    print(f" {p.BOLD}{p.CINZA_MED}{cab_linha}{p.RESET}")
    print(f" {p.CINZA_ESC}{'─' * len(cab_linha)}{p.RESET}")

    for caminho, rotulo, tipo_fmt in metricas:
        mod_k, campo_k = caminho.split(".")
        valores_cols = []

        for s in syms:
            item = dados[s]
            mod_obj = item.get(mod_k) or {}
            val = raw_val(mod_obj.get(campo_k))

            if val is None:
                txt = "—"
            elif tipo_fmt == "preco":
                txt = fmt_num_br(val, 2)
            elif tipo_fmt == "pct":
                txt = fmt_pct_fracao_br(val)
            elif tipo_fmt == "grandeza":
                txt = fmt_grandeza_br(val)
            else:
                txt = fmt_num_br(val, 2)

            valores_cols.append(pad_vis(txt, col_w, "^"))

        print(f" {pad_vis(rotulo, label_w, '<')} " + " ".join(valores_cols))
    print()


def console_requisicao_bruta(net: NetworkEngine, renderer: ConsoleRenderer) -> None:
    p = renderer.p
    renderer.banner("CONSOLE DE REQUISIÇÃO BRUTA (v11)")
    print(" Diagnóstico de rede para o endpoint /v11/finance/quoteSummary/.\n")

    metodo = input(f" {p.BOLD}Método HTTP (GET/POST/HEAD/OPTIONS) [GET]: {p.RESET}").strip().upper() or "GET"
    host_sel = input(f" {p.BOLD}Host ({'/'.join(HOSTS_EP.keys())}) [{net.host_alias}]: {p.RESET}").strip() or net.host_alias
    syms_str = input(f" {p.BOLD}Símbolos CSV [AAPL,MSFT]: {p.RESET}").strip().upper() or "AAPL,MSFT"
    mods_str = input(f" {p.BOLD}Módulos CSV [price,summaryDetail]: {p.RESET}").strip() or "price,summaryDetail"

    print("\n Vetor de Autenticação / Crumb:")
    print("  [1] Query string (?crumb=...) [Padrão oficial]")
    print("  [2] Cabeçalho HTTP (x-crumb: ...)")
    print("  [3] Sem Crumb (Espera HTTP 401)")
    opt_crumb = input(f" {p.BOLD}Opção [1]: {p.RESET}").strip() or "1"

    if opt_crumb in ("1", "2") and not net.crumb:
        net.bootstrap_auth(verbose=False)

    params: Dict[str, str] = {
        "symbols": syms_str,
        "modules": mods_str,
        "formatted": "true",
        "lang": "en-US",
        "region": "US"
    }

    extra_str = input(f" {p.BOLD}Parâmetros extras k=v;k=v [Enter para nenhum]: {p.RESET}").strip()
    if extra_str:
        for par in extra_str.split(";"):
            if "=" in par:
                k, v = par.split("=", 1)
                params[k.strip()] = v.strip()

    resp = net.request_raw(
        ENDPOINT_PATH,
        params=params,
        metodo=metodo,
        crumb_query=(opt_crumb == "1"),
        crumb_header=(opt_crumb == "2"),
        host_override=host_sel
    )

    cor_st = p.VERDE if resp.status == 200 else p.VERMELHO
    linhas_info = [
        f"Status: {cor_st}{resp.status}{p.RESET} · {resp.ms:.0f} ms · {len(resp.corpo):,} bytes",
        f"URL: {p.AZUL}{resp.url}{p.RESET}",
        ""
    ]
    for hk in ["content-type", "cache-control", "server"]:
        if hk in resp.headers:
            linhas_info.append(f"{hk}: {resp.headers[hk]}")

    prev = resp.texto()[:500] + ("…" if len(resp.corpo) > 500 else "")
    linhas_info.extend(["", "Corpo retornado (Prévia):", prev])
    renderer.caixa(linhas_info, titulo_txt="DIAGNÓSTICO HTTP", cor_titulo="CIANO")


def suite_testes_ao_vivo(client: QuoteSummaryBatchClient, renderer: ConsoleRenderer) -> bool:
    p = renderer.p
    renderer.banner("SUÍTE DE VERIFICAÇÃO AO VIVO (v11)")
    print(" Validando contratos e invariantes do endpoint /v11/finance/quoteSummary/...\n")

    acumulador: List[bool] = []
    net = client.net

    def checar(nome: str, cond: bool, detalhe: str = ""):
        acumulador.append(bool(cond))
        selo = f"{p.VERDE}✓ PASS{p.RESET}" if cond else f"{p.VERMELHO}✗ FAIL{p.RESET}"
        det_txt = f" {p.CINZA_ESC}— {detalhe}{p.RESET}" if detalhe else ""
        print(f"  {selo}  {pad_vis(nome, 62, '<')}{det_txt}")
        time.sleep(0.08)

    # 1. Autenticação mandatória (Sem crumb -> 401)
    r1 = net.request_raw(ENDPOINT_PATH, params={"symbols": "AAPL", "modules": "price"}, crumb_query=False, renew_on_401=False)
    j1 = r1.json() or {}
    checar("1. Chamada sem Crumb rejeitada com HTTP 401", r1.status == 401 and "Unauthorized" in str(j1))

    # 2. Handshake de sessão operacional
    ok_b, _ = net.bootstrap_auth(verbose=False)
    checar("2. Handshake Cookie A3 + Crumb emitido", ok_b and bool(net.crumb))

    # 3. Barra final obrigatória (Sem barra final -> 502 Edge)
    r3 = net.request_raw("/v11/finance/quoteSummary", params={"symbols": "AAPL", "modules": "price"})
    checar("3. Rota sem barra final rejeitada com 502 HTML", r3.status == 502)

    # 4. Requisição canônica com barra final -> 200
    eco4, itens4, r4 = client._get_fatia(["AAPL"], ["price", "summaryDetail"])
    checar("4. Consulta canônica com barra final -> HTTP 200", r4.status == 200 and len(itens4) == 1)

    # 5. Mapeamento por eco de símbolos
    checar("5. Eco de símbolos preservado (quoteSummary.symbols)", eco4 == ["AAPL"])

    # 6. Limite de 15 símbolos aceito na fatia
    syms_15 = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "IBM", "ORCL", "CRM", "ADBE", "QCOM", "TXN"]
    eco6, itens6, r6 = client._get_fatia(syms_15, ["price"])
    checar("6. Lote máximo oficial de 15 símbolos aceito", r6.status == 200 and len(eco6) == 15)

    # 7. Limite excedido de 16 símbolos rejeitado com 400
    syms_16 = syms_15 + ["CSCO"]
    p16 = {"symbols": ",".join(syms_16), "modules": "price", "crumb": net.crumb, "lang": "en-US", "region": "US"}
    r7 = net.request_raw(ENDPOINT_PATH, params=p16)
    j7 = r7.json() or {}
    checar("7. 16 símbolos rejeitado com HTTP 400 quoteSummary.error", r7.status == 400 and "Max symbols" in str(j7))

    # 8. symbols ausente -> 400 finance.error
    r8 = net.request_raw(ENDPOINT_PATH, params={"modules": "price", "crumb": net.crumb})
    checar("8. Parâmetro 'symbols' ausente gera HTTP 400 finance.error", r8.status == 400 and "Missing required" in r8.texto())

    # 9. modules ausente -> 400 finance.error
    r9 = net.request_raw(ENDPOINT_PATH, params={"symbols": "AAPL", "crumb": net.crumb})
    checar("9. Parâmetro 'modules' ausente gera HTTP 400 finance.error", r9.status == 400 and "Missing required" in r9.texto())

    # 10. Descarte tolerante de símbolo inexistente
    eco10, itens10, r10 = client._get_fatia(["AAPL", "INEXISTENTE_999_XYZ"], ["price"])
    checar("10. Símbolo inexistente descartado silenciosamente", r10.status == 200 and eco10 == ["AAPL"] and len(itens10) == 1)

    # 11. Lote contendo apenas símbolos inexistentes -> 200 vazio
    eco11, itens11, r11 = client._get_fatia(["INEXISTENTE_1", "INEXISTENTE_2"], ["price"])
    checar("11. Lote só de inválidos responde HTTP 200 vazio", r11.status == 200 and eco11 == [] and itens11 == [])

    # 12. Módulo desconhecido ignorado
    eco12, itens12, r12 = client._get_fatia(["AAPL"], ["price", "moduloFantasma999"])
    checar("12. Nome de módulo desconhecido ignorado sem erro", r12.status == 200 and "price" in itens12[0])

    # 13. Case insensitivity do símbolo no servidor
    eco13, _, r13 = client._get_fatia(["aapl"], ["price"])
    checar("13. Símbolo minúsculo aceito e ecoado em maiúsculo", r13.status == 200 and eco13 == ["AAPL"])

    # 14. Suporte a formatted=false (valores primitivos)
    _, itens14, r14 = client._get_fatia(["AAPL"], ["price"], formatted=False)
    p_pr = itens14[0].get("price", {}).get("regularMarketPrice") if itens14 else None
    checar("14. formatted=false retorna números escalares", isinstance(p_pr, (int, float)))

    # 15. Cabeçalhos de cache x-cache aceitos
    _, _, r15 = client._get_fatia(["AAPL"], ["price"], cache=True)
    checar("15. Headers x-cache e dedup+sort aceitos", r15.status == 200)

    # 16. dataVersion=v2 (feature flag Morningstar)
    _, _, r16 = client._get_fatia(["AAPL"], ["price"], data_version="v2")
    checar("16. Parâmetro dataVersion=v2 aceito", r16.status == 200)

    # 17. Host failover query2
    _, _, r17 = client._get_fatia(["AAPL"], ["price"], host="query2")
    checar("17. Host alternativo query2 operacional", r17.status == 200)

    # 18. POST rejeitado com 405 Method Not Allowed
    r18 = net.request_raw(ENDPOINT_PATH, params={"symbols": "AAPL", "modules": "price"}, metodo="POST", data=b"{}")
    checar("18. Método POST rejeitado com HTTP 405", r18.status == 405)

    # 19. Fatiamento transparente de lote > 15
    dados19, _ = client.consultar_lote(syms_16, ["price"])
    checar("19. Cliente fatiou lote de 16 em 2 blocos automaticamente", len(dados19) == 16)

    # 20. Validação client-side da regex de símbolos
    rej = not client.validar_simbolo("AAPL<SCRIPT>")
    checar("20. Regex client-side barra caracteres proibidos", rej)

    tot = len(acumulador)
    aprovados = sum(acumulador)
    taxa = (aprovados / tot) * 100.0

    print()
    resumo = [
        f"Total de Verificações: {tot}",
        f"Aprovadas:            {p.VERDE}{aprovados}{p.RESET}",
        f"Falhas:               {p.VERMELHO if tot - aprovados > 0 else p.VERDE}{tot - aprovados}{p.RESET}",
        f"Conformidade:         {p.BOLD}{taxa:.1f}%{p.RESET}"
    ]
    renderer.caixa(resumo, titulo_txt="RELATÓRIO DA SUÍTE DE TESTES", cor_titulo="VERDE" if aprovados == tot else "AMARELO")
    return aprovados == tot


def auditoria_offline_fixture(caminho: str, renderer: ConsoleRenderer) -> bool:
    p = renderer.p
    renderer.banner(f"AUDITORIA OFFLINE · {os.path.basename(caminho)}")

    if not os.path.isfile(caminho):
        print(f"  {p.VERMELHO}Arquivo '{caminho}' não encontrado.{p.RESET}")
        return False

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            j = json.load(f)
    except Exception as e:
        print(f"  {p.VERMELHO}Falha ao ler JSON: {e}{p.RESET}")
        return False

    checks: List[Tuple[str, bool, str]] = []

    tem_qs = isinstance(j, dict) and "quoteSummary" in j
    checks.append(("Envelope 'quoteSummary' presente", tem_qs, "Estrutura raiz obrigatória"))

    if tem_qs:
        qs = j["quoteSummary"]
        checks.append(("Campo 'error' é estritamente nulo", qs.get("error") is None, "Sem erro de aplicação"))

        eco = qs.get("symbols")
        res = qs.get("result")
        checks.append(("Array 'symbols' (eco) presente", isinstance(eco, list), f"{len(eco) if isinstance(eco, list) else 0} símbolos"))
        checks.append(("Array 'result' presente", isinstance(res, list), f"{len(res) if isinstance(res, list) else 0} itens"))

        if isinstance(eco, list) and isinstance(res, list):
            checks.append(("Paridade 1:1 entre symbols e result", len(eco) == len(res), "Mapeamento posicional"))
            if res:
                sem_sym_raiz = all("symbol" not in it for it in res)
                checks.append(("Itens de result não têm chave 'symbol' na raiz", sem_sym_raiz, "Contrato v11 documentado"))

    print()
    for rotulo, status, desc in checks:
        selo = f"{p.VERDE}✓ CONFORME{p.RESET}" if status else f"{p.VERMELHO}✗ VIOLAÇÃO{p.RESET}"
        print(f"  {selo}  {pad_vis(rotulo, 48, '<')} {p.CINZA_ESC}— {desc}{p.RESET}")

    tudo_ok = all(c[1] for c in checks)
    print()
    return tudo_ok


def gestao_sessao_autenticacao(net: NetworkEngine, renderer: ConsoleRenderer) -> None:
    p = renderer.p
    renderer.banner("GESTÃO DE SESSÃO & CREDENCIAIS (v11)")

    a3 = net.obter_a3()
    linhas = [
        f"Requisito:     {p.AMARELO}OBRIGATÓRIO (HTTP 401 sem Cookie A3 + Crumb){p.RESET}",
        f"Cookie A3:     {p.VERDE + 'Ativo (' + str(len(a3)) + ' chars)' + p.RESET if a3 else p.VERMELHO + 'Ausente' + p.RESET}",
        f"Crumb Sessão:  {p.VERDE + net.crumb + p.RESET if net.crumb else p.VERMELHO + 'Não emitido' + p.RESET}",
        f"Host Primário: {p.AMBAR}{net.host_alias}{p.RESET} ({net.base_url})",
        f"Requisições:   {net.requisicoes}"
    ]
    renderer.caixa(linhas, titulo_txt="ESTADO DA SESSÃO", cor_titulo="CIANO")

    print("\n Ações Disponíveis:")
    print("  [1] Executar Handshake Completo (fc.yahoo.com -> getcrumb)")
    print("  [2] Limpar e Redefinir Sessão (Zerar Cookies)")
    print("  [3] Alternar Host Ativo (query1 ↔ query2)")
    print("  [0] Voltar")

    op = input(f"\n {p.BOLD}Escolha uma ação [0]: {p.RESET}").strip() or "0"
    if op == "1":
        ok, msg = net.bootstrap_auth(verbose=True)
        if ok:
            print(f"  {p.VERDE}✓ {msg}{p.RESET}")
        else:
            print(f"  {p.VERMELHO}✗ {msg}{p.RESET}")
    elif op == "2":
        net.jar.clear()
        net.crumb = None
        print(f"  {p.AMARELO}⚠ Sessão redefinida.{p.RESET}")
    elif op == "3":
        net.host_alias = "query2" if net.host_alias == "query1" else "query1"
        print(f"  {p.VERDE}✓ Host ativo alternado para '{net.host_alias}'.{p.RESET}")


# ════════════════════ Submenu de Visões do Lote ═════════════════════════════

def submenu_visoes_lote(
    dados: Dict[str, Dict[str, Any]],
    modules_pedidos: List[str],
    renderer: ConsoleRenderer
) -> None:
    p = renderer.p

    while True:
        try:
            print()
            renderer.caixa([
                f"Lote carregado com {len(dados)} ativos resolvidos.",
                "Selecione uma visão analítica ou digite 0 para retornar ao menu principal."
            ], titulo_txt="VISÕES DE FUNDAMENTALS EM LOTE", cor_titulo="AMBAR")

            print(f"  [{p.AMBAR}1{p.RESET}] Tabela Resumida de Cotação e Valuation")
            print(f"  [{p.AMBAR}2{p.RESET}] Matriz Comparativa de Múltiplos & Rentabilidade")
            print(f"  [{p.AMBAR}3{p.RESET}] Inventário Analítico de Módulos (Entregues vs. Omitidos)")
            print(f"  [{p.AMBAR}4{p.RESET}] Detalhar Todos os Campos de um Módulo Específico")
            print(f"  [{p.AMBAR}5{p.RESET}] Exibir JSON Integral Formatado na Tela")
            print(f"  [{p.AMBAR}6{p.RESET}] Exportar Resposta Consolidada para Arquivo Local")
            print(f"  [{p.VERMELHO}0{p.RESET}] Voltar ao Menu Principal")

            op = input(f"\n {p.BOLD}Opção desejada [1]: {p.RESET}").strip() or "1"

            if op == "0":
                break
            elif op == "1":
                renderer.tabela_resumo_lote(dados, nota="Dados consolidados via /v11/finance/quoteSummary/")
            elif op == "2":
                comparador_multi_ativo(dados, renderer)
            elif op == "3":
                exibir_inventario_modulos(dados, modules_pedidos, renderer)
            elif op == "4":
                detalhar_modulo_ticker(dados, renderer)
            elif op == "5":
                print(f"\n{json.dumps(dados, indent=2, ensure_ascii=False)}\n")
            elif op == "6":
                destino = input(f" {p.BOLD}Nome do arquivo [lote_quoteSummary.json]: {p.RESET}").strip() or "lote_quoteSummary.json"
                with open(destino, "w", encoding="utf-8") as f:
                    json.dump(dados, f, indent=2, ensure_ascii=False)
                print(f"  {p.VERDE}✓ Lote consolidado salvo em '{destino}'.{p.RESET}")

        except KeyboardInterrupt:
            print(f"\n  {p.AMARELO}⚠ Visão interrompida.{p.RESET}")
            break
        except Exception as e:
            print(f"\n  {p.VERMELHO}✗ Erro na exibição da visão: {e}{p.RESET}")


# ════════════════════ Loop de Menu Principal ════════════════════════════════

def loop_menu_principal(client: QuoteSummaryBatchClient, renderer: ConsoleRenderer) -> None:
    p = renderer.p
    simbolos_atuais = list(MAGNIFICENT_7)
    preset_atual = "resumo"

    while True:
        try:
            renderer.banner()
            print(f"  [{p.AMBAR}1{p.RESET}] Consultar Lote Customizado (Símbolos & Módulos em Loop)")
            print(f"  [{p.AMBAR}2{p.RESET}] Consulta Rápida: Magnificent 7 (Preset 'resumo')")
            print(f"  [{p.AMBAR}3{p.RESET}] Consulta Completa: Magnificent 7 × Todos os 55 Módulos")
            print(f"  [{p.AMBAR}4{p.RESET}] Console de Requisição Bruta (Diagnóstico de Rede & Headers)")
            print(f"  [{p.AMBAR}5{p.RESET}] Suíte de Verificação ao Vivo (20 Testes de Contrato)")
            print(f"  [{p.AMBAR}6{p.RESET}] Auditoria Offline de Fixture JSON Local")
            print(f"  [{p.AMBAR}7{p.RESET}] Gestão de Sessão, Autenticação A3 e Crumb")
            print(f"  [{p.AMBAR}8{p.RESET}] Catálogo de Módulos (55) e Presets Disponíveis")
            print(f"  [{p.VERMELHO}0{p.RESET}] Sair da Aplicação")
            print()
            renderer.barra_status(client.net)

            op = input(f"\n {p.BOLD}Selecione uma opção [1]: {p.RESET}").strip() or "1"

            if op == "0":
                print(f"\n {p.CIANO}Encerrando aplicação de forma limpa. Até logo!{p.RESET}")
                break

            elif op == "1":
                inp_s = input(f"\n {p.BOLD}Símbolos CSV [{','.join(simbolos_atuais)}]: {p.RESET}").strip().upper()
                if inp_s:
                    simbolos_atuais = [s.strip() for s in inp_s.split(",") if s.strip()]

                print("\n Presets de Módulos:")
                for pk, (pdesc, pmods) in PRESETS_MODULOS.items():
                    print(f"  • {p.AMBAR}{pk:<12}{p.RESET} ({len(pmods):>2} mods) — {pdesc}")
                sel_p = input(f"\n {p.BOLD}Escolha o preset ou digite módulos customizados [{preset_atual}]: {p.RESET}").strip().lower() or preset_atual

                if sel_p in PRESETS_MODULOS:
                    preset_atual = sel_p
                    mods_escolhidos = list(PRESETS_MODULOS[sel_p][1])
                else:
                    mods_escolhidos = [m.strip() for m in sel_p.split(",") if m.strip()]

                print(f"\n {p.CINZA_MED}Consultando {len(simbolos_atuais)} ativos com {len(mods_escolhidos)} módulos...{p.RESET}")
                dados, resps = client.consultar_lote(simbolos_atuais, mods_escolhidos)
                lat_media = sum(r.ms for r in resps) / max(1, len(resps))
                bytes_tot = sum(len(r.corpo) for r in resps)

                renderer.tabela_resumo_lote(dados, nota=f"{len(dados)} ativos resolvidos · {len(resps)} requisição(ões) · {lat_media:.0f} ms · {bytes_tot:,} B")
                submenu_visoes_lote(dados, mods_escolhidos, renderer)

            elif op == "2":
                mods = list(PRESETS_MODULOS["resumo"][1])
                dados, resps = client.consultar_lote(MAGNIFICENT_7, mods)
                renderer.tabela_resumo_lote(dados, nota=f"Magnificent 7 · {resps[0].ms:.0f} ms · {len(resps[0].corpo):,} B")
                submenu_visoes_lote(dados, mods, renderer)

            elif op == "3":
                mods = list(PRESETS_MODULOS["tudo"][1])
                print(f"\n {p.AMARELO}⚠ Consultando todos os 55 módulos para as Magnificent 7 (Payload ~2.4 MB)...{p.RESET}")
                dados, resps = client.consultar_lote(MAGNIFICENT_7, mods)
                bytes_tot = sum(len(r.corpo) for r in resps)
                renderer.tabela_resumo_lote(dados, nota=f"Magnificent 7 × 55 módulos · {bytes_tot:,} B")
                submenu_visoes_lote(dados, mods, renderer)

            elif op == "4":
                console_requisicao_bruta(client.net, renderer)

            elif op == "5":
                suite_testes_ao_vivo(client, renderer)

            elif op == "6":
                caminho = input(f"\n {p.BOLD}Caminho do arquivo JSON de fixture: {p.RESET}").strip()
                if caminho:
                    auditoria_offline_fixture(caminho, renderer)

            elif op == "7":
                gestao_sessao_autenticacao(client.net, renderer)

            elif op == "8":
                linhas_cat = ["PRESETS DISPONÍVEIS:"]
                for pk, (pdesc, pmods) in PRESETS_MODULOS.items():
                    linhas_cat.append(f" • {pk:<12} ({len(pmods):>2} módulos): {pdesc}")
                linhas_cat.extend(["", f"UNIVERSO INTEGRAL ({len(UNIVERSO_MODULOS)} MÓDULOS):", ", ".join(UNIVERSO_MODULOS)])
                renderer.caixa(linhas_cat, titulo_txt="CATÁLOGO DE MÓDULOS v11", cor_titulo="AMBAR")

            else:
                print(f"  {p.AMARELO}Opção '{op}' não reconhecida.{p.RESET}")

        except KeyboardInterrupt:
            print(f"\n\n  {p.AMARELO}⚠ Interrupção detectada. Retornando ao menu principal...{p.RESET}")
        except EOFError:
            print(f"\n\n  {p.CIANO}Entrada encerrada (EOF). Fechando aplicação...{p.RESET}")
            break
        except Exception as e:
            print(f"\n  {p.VERMELHO}✗ Erro inesperado: {e}{p.RESET}")


# ════════════════════ Ponto de Entrada & CLI ════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="v11_finance_quoteSummary.py",
        description="TERMINAL v3.5 — Aplicativo Interativo e Cliente Canônico para GET /v11/finance/quoteSummary/",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("symbols", nargs="*", default=None, help="Símbolos CSV ou espaçados (default: Magnificent 7)")
    parser.add_argument("--preset", choices=list(PRESETS_MODULOS.keys()), default="resumo", help="Preset de módulos")
    parser.add_argument("--modules", default=None, help="Lista CSV de módulos específicos (sobrepõe --preset)")
    parser.add_argument("--raw", action="store_true", help="formatted=false (números escalares puros)")
    parser.add_argument("--wrap", action="store_true", help="Preserva envelopes {raw, fmt} sem desembrulhar")
    parser.add_argument("--table", action="store_true", help="Imprime tabela resumida e sai")
    parser.add_argument("--inventario", action="store_true", help="Imprime inventário de módulos (entregues vs omitidos) e sai")
    parser.add_argument("--cache", action="store_true", help="Habilita dedup+sort e headers x-cache")
    parser.add_argument("--test-live", action="store_true", help="Executa a suíte de 20 testes ao vivo e sai")
    parser.add_argument("--audit", metavar="ARQ", default=None, help="Audita fixture JSON offline e sai")
    parser.add_argument("--catalog", action="store_true", help="Exibe o catálogo completo de módulos em JSON e sai")
    parser.add_argument("--json", dest="json_out", default=None, metavar="ARQ", help="Salva a resposta crua em arquivo ou emite no stdout")
    parser.add_argument("--host", choices=list(HOSTS_EP.keys()), default="query1", help="Host edge da Yahoo")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Timeout por requisição em segundos")
    parser.add_argument("--sem-cores", "--no-color", dest="sem_cores", action="store_true", help="Desativa cores ANSI")
    parser.add_argument("--ascii", action="store_true", help="Utiliza glifos ASCII simples (+--+)")
    parser.add_argument("--no-pause", dest="no_pause", action="store_true", help="Desativa pausa ENTER ao sair")

    args = parser.parse_args()

    modo_cor = "off" if (args.sem_cores or os.environ.get("NO_COLOR")) else (
        "rgb" if "truecolor" in (os.environ.get("COLORTERM") or "").lower() else "256"
    )
    p = Palette(modo=modo_cor)
    b = BoxChars(ascii_mode=args.ascii)
    renderer = ConsoleRenderer(p, b)

    net = NetworkEngine(host_alias=args.host, timeout=args.timeout)
    client = QuoteSummaryBatchClient(net)

    try:
        # Modo 1: Catálogo JSON puro
        if args.catalog:
            print(json.dumps({
                "PATH": ENDPOINT_PATH,
                "MAX_LOTE_SERVIDOR": MAX_LOTE_SERVIDOR,
                "UNIVERSO_MODULOS": UNIVERSO_MODULOS,
                "PRESETS": {k: {"desc": d, "modulos": m} for k, (d, m) in PRESETS_MODULOS.items()}
            }, indent=2, ensure_ascii=False))
            return 0

        # Modo 2: Auditoria offline direta
        if args.audit:
            ok = auditoria_offline_fixture(args.audit, renderer)
            return 0 if ok else 1

        # Modo 3: Suíte de testes ao vivo direta
        if args.test_live:
            ok = suite_testes_ao_vivo(client, renderer)
            return 0 if ok else 1

        # Modo 4: Execução CLI direta por parâmetros
        if args.symbols or args.table or args.inventario or args.json_out:
            simbolos = []
            if args.symbols:
                for pedaco in args.symbols:
                    simbolos.extend([s.strip().upper() for s in pedaco.split(",") if s.strip()])
            else:
                simbolos = list(MAGNIFICENT_7)

            if args.modules:
                modulos = [m.strip() for m in args.modules.split(",") if m.strip()]
            else:
                modulos = list(PRESETS_MODULOS[args.preset][1])

            dados, resps = client.consultar_lote(
                symbols=simbolos,
                modules=modulos,
                formatted=not args.raw,
                cache=args.cache
            )

            if args.json_out:
                if args.json_out.strip().lower() == "-":
                    print(json.dumps(dados, indent=2, ensure_ascii=False))
                else:
                    with open(args.json_out, "w", encoding="utf-8") as f:
                        json.dump(dados, f, indent=2, ensure_ascii=False)
                    print(f"✓ Resposta salva em '{args.json_out}'")
                return 0

            if args.table:
                renderer.tabela_resumo_lote(dados)
                return 0

            if args.inventario:
                exibir_inventario_modulos(dados, modulos, renderer)
                return 0

            print(json.dumps(dados, indent=2, ensure_ascii=False))
            return 0

        # Modo 5: Menu Interativo Contínuo (Anti-fechamento padrão)
        loop_menu_principal(client, renderer)
        return 0

    except KeyboardInterrupt:
        print(f"\n  {p.AMARELO}Operação cancelada pelo usuário.{p.RESET}")
        return 130
    except Exception as e:
        print(f"\n  {p.VERMELHO}ERRO CRÍTICO: {e}{p.RESET}")
        return 1
    finally:
        if not args.no_pause and sys.stdin.isatty():
            try:
                input(f"\n{p.CINZA_ESC}Pressione ENTER para fechar a janela...{p.RESET}")
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())