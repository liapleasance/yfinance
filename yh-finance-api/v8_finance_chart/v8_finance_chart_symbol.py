#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v8_finance_chart_symbol.py — v1.0 · aplicativo interativo
==========================================================
Implementação de referência EXECUTÁVEL do endpoint
GET /v8/finance/chart/{symbol} (Yahoo Finance — o endpoint do GRÁFICO),
com interface de terminal em menu, gráfico ASCII da série, tabelas OHLCV,
eventos corporativos, suíte de verificação ao vivo e auditoria offline.

COMO USAR
    python v8_finance_chart_symbol.py                         → menu interativo
    python v8_finance_chart_symbol.py AAPL                    → diário de 1 ano (canônica do app)
    python v8_finance_chart_symbol.py AAPL --interval 5m --range 1d
    python v8_finance_chart_symbol.py AAPL --period1 1700000000 --period2 1701000000
    python v8_finance_chart_symbol.py AAPL --prepost          → inclui pré/pós-market
    python v8_finance_chart_symbol.py AAPL --events div       → só dividendos
    python v8_finance_chart_symbol.py AAPL --no-adj           → sem adjclose
    python v8_finance_chart_symbol.py AAPL --barras 30        → tabela OHLCV das 30 últimas
    python v8_finance_chart_symbol.py AAPL --raw              → envelope integral
    python v8_finance_chart_symbol.py AAPL --json saida.json
    python v8_finance_chart_symbol.py AAPL --verifica         → suíte de 24 checagens
    python v8_finance_chart_symbol.py --auditar v8_finance_chart.json
    python v8_finance_chart_symbol.py AAPL --host iquery      → rota interna
    Flags: --sem-cores · --ascii · --no-pause

O ÚNICO ENDPOINT ANÔNIMO DA FAMÍLIA
    Não requer Cookie A3 nem Crumb — `crumb` na query é aceito e IGNORADO
    (garbage → 200 idêntico), e não há bootstrap de sessão. A única exigência
    da edge é o User-Agent de navegador (biblioteca → 429 Edge, 23 B).
    Sem quota de identidade; sem cache local obrigatório.

CONTRATO (bateria anônima de 37 chamadas — 2026-11-06)
    * Envelope {"chart":{"result":[…],"error":null}}; result[0] = {meta (29 campos),
      timestamp[], indicators.quote[0] (open/high/low/close/volume em arrays paralelos
      com null nas barras sem pregão), indicators.adjclose[0].adjclose (some por
      inteiro com includeAdjustedClose=false), events (dividends/splits/capitalGain,
      chave = epoch)}.
    * Defaults do SERVIDOR sem nada na query: interval=1m com janela de 1 dia
      (152 pontos) — diferente dos defaults do app (1d/1y).
    * interval: enum de 14 — [1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 4h, 1d, 5d,
      1wk, 1mo, 3mo] (a própria mensagem de 400 devolve a lista; 4h existe,
      2h/6h/1y não). Inválido → 400 Bad Request com a lista íntegra.
    * Janela de 1m limitada a 8 dias → 422 Unprocessable Entity ("Only 8 days
      worth of 1m granularity data are allowed…") — o único 422 da família.
    * range: 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max (meta.validRanges devolve a
      lista). Inválido NÃO é rejeitado: range=2y2 → 200 com a string ecoada em
      meta.range e 1 único timestamp (degradação degenerada).
    * period1/period2: epoch em SEGUNDOS, só funcionam em par — period2 sozinho
      devolve ~300 barras diárias (startDate implícito ~14 meses antes);
      period1 sozinho → 400 (end implícito 0); invertidos → 400 com
      "start date cannot be after end date. startDate = …, endDate = …".
      PRECEDÊNCIA: com period1+period2 AND range na mesma query, o RANGE VENCE
      (os periods são ignorados — verificado com periods de 10 dias + range=1y
      → 252 barras de 1 ano).
    * includePrePost: true/TRUE ativa (5m&1d: 97 pontos vs 32); `1` NÃO ativa
      (sem coerção numérica — a regra da família, verificada).
    * includeAdjustedClose=false → o bloco indicators.adjclose some por inteiro.
    * Erros: 404 TEXTO PURO "Not Found" (path sem o segmento do símbolo) ·
      404 com envelope {"chart":{"result":null,"error":{"code":"Not Found",
      "description":"No data found, symbol may be delisted"}}} (símbolo
      inexistente — diferente do irmão de opções, que devolve 200 zerado) ·
      POST → 411 Length Required em HTML da borda (não 405) · 429 Edge por UA.
    * Cache de borda: private, no-cache, no-store — nada cacheável.
    * Backend próprio: finance-chart-api (x-envoy-decorator-operation), distinto
      do finance-quote-api dos irmãos; hosts query1/query2/iquery.

CONTRATO DO CLIENTE OFICIAL (loader da página /chart)
    * Defaults: {events: "capitalGain|div|split", interval: "1d", range: "1y",
      formatted: true, includeAdjustedClose: true, userYfid: true}; period1/
      period2 só em par (sem eles, envia range=1y e OMITE range da query).
    * Cache de store por symbol+interval+(period1+period2|range): id idêntico →
      retorno SEM rede.
    * Achatamento: a resposta vira uma lista prices[] com os eventos intercalados
      por data dentro da série (dividendos/splits ganham entrada própria), e
      barras com OHLC não numérico são puladas.

Autossuficiente: apenas stdlib (urllib + json). Python 3.8+. Interface em pt-BR.
"""
from __future__ import annotations

import argparse
import datetime
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
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple

__version__ = "1.0.0"

# ───────────────────────────── Constantes do endpoint ────────────────────── #

ENDPOINT_NAME = "GET /v8/finance/chart/{symbol}"
PATH_BASE = "/v8/finance/chart"
HOSTS_EP = {
    "query1": "https://query1.finance.yahoo.com",
    "query2": "https://query2.finance.yahoo.com",
    "iquery": "https://iquery.finance.yahoo.com",
}
DEFAULT_HOST = "query1"
DEFAULT_TIMEOUT = 30.0          # o widget de gráfico usa 30 s (Dr = 3e4)
UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
INTERVALOS = ("1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h",
              "4h", "1d", "5d", "1wk", "1mo", "3mo")
EVENTS_DEFAULT = "capitalGain|div|split"

Resp = namedtuple("Resp", "status corpo headers ms url")

# ─────────────────────────── UI — camada de apresentação ─────────────────── #

_RESET = "\033[0m"
_CORES = True
_ASCII = False
_INTERRUPCOES = 0
_RE_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


class SairLoop(Exception):
    """Pedido de saída (opção 0, EOF ou Ctrl+C repetido)."""


def ini_ui(cores: bool = True, ascii_: bool = False) -> None:
    global _CORES, _ASCII
    _CORES = cores
    _ASCII = ascii_
    if os.name == "nt":
        os.system("")
        try:
            os.system("title Yahoo Finance - Chart")
        except Exception:
            pass
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cor(txt: Any, *estilos: str) -> str:
    if not _CORES or not estilos:
        return str(txt)
    basicos = {"negrito": "\033[1m", "dim": "\033[2m",
               "vermelho": "\033[31m", "verde": "\033[32m", "amarelo": "\033[33m",
               "azul": "\033[34m", "magenta": "\033[35m", "ciano": "\033[36m",
               "branco": "\033[97m", "ambar": "\033[38;5;208m",
               "cinza": "\033[38;5;247m", "cinza_esc": "\033[38;5;244m"}
    rgb = {"ambar": (255, 160, 40), "verde": (0, 200, 83), "vermelho": (255, 67, 61),
           "ciano": (0, 212, 255), "amarelo": (255, 214, 0), "azul": (0, 104, 255),
           "teal": (74, 246, 195), "magenta": (255, 64, 255), "branco": (255, 255, 255),
           "cinza": (160, 160, 160), "cinza_esc": (128, 128, 128)}
    c256 = {"ambar": 208, "verde": 41, "vermelho": 203, "ciano": 45, "amarelo": 220,
            "azul": 33, "teal": 86, "magenta": 207, "branco": 231, "cinza": 247,
            "cinza_esc": 244}
    suporta_rgb = bool(os.environ.get("WT_SESSION")) or \
        "truecolor" in (os.environ.get("COLORTERM") or "").lower()
    partes = []
    for e in estilos:
        if e in ("negrito", "dim"):
            partes.append(basicos[e])
        elif e in rgb and suporta_rgb:
            r, g, b = rgb[e]
            partes.append(f"\033[38;2;{r};{g};{b}m")
        elif e in c256:
            partes.append(f"\033[38;5;{c256[e]}m")
        elif e in basicos:
            partes.append(basicos[e])
    ini = "".join(partes)
    return f"{ini}{txt}{_RESET}" if ini else str(txt)


def _cs(nome: str) -> str:
    if _ASCII:
        return {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-",
                "v": "|", "blk": "#", "lt": ".", "meio": "*"}[nome]
    return {"tl": "╭", "tr": "╮", "bl": "╰", "br": "╯", "h": "─",
            "v": "│", "blk": "█", "lt": "░", "meio": "·"}[nome]


def _vis(s: str) -> int:
    return len(_RE_ANSI.sub("", str(s)))


def _pad(cel: str, w: int, a: str = "<") -> str:
    d = max(0, w - _vis(cel))
    if a == ">":
        return " " * d + cel
    if a == "^":
        return " " * (d // 2) + cel + " " * (d - d // 2)
    return cel + " " * d


def largura_tela() -> int:
    try:
        return shutil.get_terminal_size(fallback=(120, 30)).columns
    except Exception:
        return 120


def secao(titulo: str) -> None:
    pref = _cs("h") * 2 + " " + cor(titulo, "negrito", "ambar") + " "
    resto = max(0, largura_tela() - 1 - _vis(pref))
    print(pref + _cs("h") * resto)


def caixa(linhas, titulo: str = "") -> str:
    itens = [str(l) for l in linhas]
    w = max([_vis(l) for l in itens] + [_vis(titulo) + 1, 8])
    if titulo:
        t = f" {titulo} "
        topo = _cs("tl") + t + _cs("h") * (w + 2 - _vis(t)) + _cs("tr")
    else:
        topo = _cs("tl") + _cs("h") * (w + 2) + _cs("tr")
    meio = [_cs("v") + " " + l + " " * (w - _vis(l)) + " " + _cs("v") for l in itens]
    rod = _cs("bl") + _cs("h") * (w + 2) + _cs("br")
    return "\n".join([topo, *meio, rod])


def imprimir_tabela(headers: List[str], rows: List[List[str]],
                    aligns: Optional[List[str]] = None) -> None:
    ncol = len(headers)
    aligns = list(aligns or ["<"] * ncol)
    larg = [_vis(str(headers[i])) for i in range(ncol)]
    for row in rows:
        for i in range(ncol):
            larg[i] = max(larg[i], _vis(str(row[i])))
    print("  ".join(cor(_pad(str(headers[i]), larg[i], aligns[i]), "negrito")
                    for i in range(ncol)))
    print(cor("  ".join(_cs("h") * larg[i] for i in range(ncol)), "dim"))
    for row in rows:
        print("  ".join(_pad(str(row[i]), larg[i], aligns[i]) for i in range(ncol)))


def pedir(msg: str, default=None, obrigatorio: bool = False):
    global _INTERRUPCOES
    dica = cor(f" [{default}]" if default is not None else "", "dim")
    while True:
        try:
            bruto = input(f"{msg}{dica}: ")
            break
        except KeyboardInterrupt:
            _INTERRUPCOES += 1
            if _INTERRUPCOES >= 2:
                raise SairLoop
            print(cor("\n  (Ctrl+C de novo sai; ENTER aceita o padrão)", "dim"))
            continue
        except EOFError:
            raise SairLoop
    _INTERRUPCOES = 0
    v = str(bruto).strip()
    if not v:
        if obrigatorio and default is None:
            print(cor("  valor obrigatório — digite algo (Ctrl+C duas vezes sai)", "amarelo"))
            return pedir(msg, default, obrigatorio)
        return default
    return v


def escolher(titulo: str, opcoes: List) -> int:
    def desenhar():
        print("\n" + cor(titulo, "negrito", "ambar"))
        for i, item in enumerate(opcoes, 1):
            rot, desc = item if isinstance(item, tuple) else (item, "")
            linha = f"  {cor(f'[{i:>2}]', 'negrito', 'amarelo')}  {rot}"
            if desc:
                linha += cor(f"  {_cs('meio')} {desc}", "dim")
            print(linha)
        print(f"  {cor('[ 0]', 'negrito')}  Voltar")
    desenhar()
    while True:
        try:
            r = pedir("Opção")
        except SairLoop:
            return 0
        try:
            n = int(str(r))
        except (TypeError, ValueError):
            n = -1
        if n == 0:
            return 0
        if 1 <= n <= len(opcoes):
            return n
        print(cor("  opção inválida — tente de novo", "amarelo"))
        desenhar()


def pausa(msg: str = "Pressione ENTER para continuar") -> None:
    try:
        input(cor(f"\n{msg}...", "dim"))
    except (EOFError, KeyboardInterrupt):
        pass


def ok(msg: str) -> None:
    print(cor("  [ OK ] ", "verde") + msg)


def aviso(msg: str) -> None:
    print(cor("  [ !! ] ", "amarelo") + msg)


def erro(msg: str) -> None:
    print(cor("  [ERRO] ", "vermelho") + msg)


def imprimir_erro(e: BaseException) -> None:
    print("\n" + caixa([str(e) or repr(e)], titulo=cor("ERRO", "negrito")))
    texto = str(e)
    if "429" in texto or "Too Many" in texto:
        print(cor("  dica: edge bloqueou por User-Agent — o app envia UA de navegador;"
                  " verifique proxies", "amarelo"))
    elif "422" in texto or "8 days" in texto:
        print(cor("  dica: 1m aceita no máximo 8 dias por requisição — reduza a janela", "amarelo"))
    elif "400" in texto and "interval" in texto:
        print(cor("  dica: use um dos 14 intervals válidos (--help lista)", "amarelo"))
    elif "rede" in texto or "timed out" in texto:
        print(cor("  dica: verifique internet/DNS/proxy e o timeout (Configurações)", "amarelo"))


def banner() -> None:
    print("\n" + caixa([
        cor("  YAHOO FINANCE · CHART (OHLCV + eventos)", "negrito", "branco"),
        cor("  GET /v8/finance/chart/{symbol}", "ambar"),
        cor(f"  app de terminal · v{__version__} · stdlib pura · anônimo (sem A3/crumb)", "dim"),
    ]))
    print(cor("  sem argumentos = menu; a janela só fecha no Sair "
              "(Ctrl+C duas vezes também sai)", "dim"))


def statuslinha(est: "Estado") -> None:
    print(cor(f"  host {est.host} · interval {est.intervalo} · range {est.range}"
              f" · anônimo (sem A3/crumb) · requisições "
              f"{est.cliente.requisicoes if est.cliente else 0}", "dim"))


# ───────────────────── Formatação (pt-BR, datas, compactos) ──────────────── #

def fdec(x, nd: int = 2) -> str:
    if x is None or not isinstance(x, (int, float)) or isinstance(x, bool):
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def fnum(n) -> str:
    if n is None or not isinstance(n, (int, float)) or isinstance(n, bool):
        return "—"
    if isinstance(n, float) and n == int(n):
        n = int(n)
    if isinstance(n, int):
        return f"{n:,}".replace(",", ".")
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fpct(x, nd: int = 2, sinal: bool = False) -> str:
    if x is None or not isinstance(x, (int, float)) or isinstance(x, bool):
        return "—"
    s = f"{x:+.{nd}f}" if sinal else f"{x:.{nd}f}"
    return (s + "%").replace(".", ",")


def fvol_compacto(n) -> str:
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return "—"
    n = float(n)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= div:
            return f"{n / div:.1f}".replace(".", ",") + suf
    return f"{int(n)}"


def fdata(ts, com_hora: bool = False) -> str:
    if ts is None:
        return "—"
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return str(ts)
    if ts <= 0:
        return "—"
    try:
        dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
        return dt.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")
    except (OverflowError, ValueError, OSError):
        return str(ts)


def fdata_local(ts) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return "—"


MESES_PT = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio",
            6: "junho", 7: "julho", 8: "agosto", 9: "setembro", 10: "outubro",
            11: "novembro", 12: "dezembro"}


def fdata_extenso(ts) -> str:
    try:
        d = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date()
        return f"{d.day} de {MESES_PT[d.month]} de {d.year}"
    except (TypeError, ValueError, OverflowError, OSError):
        return "—"


# ──────────────────────── Cliente — transporte do chart ──────────────────── #

class ErroEndpoint(RuntimeError):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


class Cliente:
    """Cliente ANÔNIMO do /v8/finance/chart — sem A3, sem crumb, sem bootstrap.

    A edge exige só o User-Agent de navegador (biblioteca → 429 Edge de 23 B).
    Retry: 429/503 → backoff exponencial (o endpoint não tem 401 a tratar)."""

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base = HOSTS_EP[host]
        self.host_nome = host
        self.timeout = timeout
        self.requisicoes = 0
        self.ultimo_resp: Optional[Resp] = None

    def consultar(self, simbolo: str, params: Dict, metodo: str = "GET",
                  headers: Optional[Dict] = None) -> Resp:
        q = urllib.parse.urlencode(params, doseq=True)
        url = f"{self.base}{PATH_BASE}/{urllib.parse.quote(simbolo)}" + (f"?{q}" if q else "")
        req = urllib.request.Request(url, method=metodo, headers={
            "User-Agent": UA_BROWSER, "Accept": "*/*",
            "Referer": "https://finance.yahoo.com/", **(headers or {})})
        t0 = time.perf_counter()
        self.requisicoes += 1
        try:
            r = self.opener_abrir(req)
            corpo = r.corpo
            hdrs = r.headers
            st = r.status
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace") if e.fp else ""
            hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
            st = e.code
        except urllib.error.URLError as e:
            raise ErroEndpoint(f"falha de rede: {e.reason} (internet? DNS? proxy?)") from e
        ms = (time.perf_counter() - t0) * 1000
        resp = Resp(st, corpo, hdrs, ms, url)
        self.ultimo_resp = resp
        return resp

    def opener_abrir(self, req):
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            corpo = resp.read().decode("utf-8", "replace")
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return namedtuple("_R", "corpo headers status")(corpo, hdrs, resp.status)

    def pedido(self, simbolo: str, params: Dict) -> Resp:
        r: Optional[Resp] = None
        for tentativa in range(5):
            r = self.consultar(simbolo, params)
            if r.status in (429, 503) and tentativa < 4:
                espera = 2 ** tentativa + random.uniform(0.1, 0.5)
                aviso(f"HTTP {r.status} — backoff de {espera:.1f}s ({tentativa + 1}/5)…")
                time.sleep(espera)
                continue
            return r
        return r  # type: ignore[return-value]

    @staticmethod
    def _parse(r: Resp) -> dict:
        if r.status == 200 and not r.corpo.strip().startswith("{"):
            raise ErroEndpoint(f"HTTP {r.status}: corpo não-JSON {r.corpo[:100]!r}", r.status)
        try:
            j = json.loads(r.corpo)
        except ValueError as e:
            raise ErroEndpoint(f"HTTP {r.status}: corpo não-JSON {r.corpo[:100]!r}", r.status) from e
        if r.status != 200:
            ch = j.get("chart") or {} if isinstance(j, dict) else {}
            err = ch.get("error") or {}
            raise ErroEndpoint(f"HTTP {r.status} {err.get('code')}: {err.get('description')}", r.status)
        if "chart" in j:
            return j
        raise ErroEndpoint(f"envelope inesperado: chaves {sorted(j)}", 200)

    def cadeia(self, simbolo: str, intervalo: str, range_: Optional[str],
               period1: Optional[int], period2: Optional[int],
               events: str, prepost: bool, adjclose: bool,
               formatted: bool = True) -> dict:
        params: Dict[str, Any] = {
            "interval": intervalo,
            "events": events,
            "includeAdjustedClose": "true" if adjclose else "false",
            "includePrePost": "true" if prepost else "false",
            "formatted": "true" if formatted else "false",
            "symbol": simbolo,                 # o app replica o symbol na query
            "userYfid": "true",
        }
        if period1 is not None and period2 is not None:
            params["period1"] = str(period1)
            params["period2"] = str(period2)
        else:
            params["range"] = range_ or "1y"
        r = self.pedido(urllib.parse.quote(simbolo), params)
        return self._parse(r)

    def info(self) -> dict:
        return {"host": self.host_nome, "base": self.base, "requisicoes": self.requisicoes}


# ───────────────────────── Modelo da série (normalizada) ─────────────────── #

class Serie:
    """Visão normalizada: barras paralelas a timestamp[], com adjclose e eventos."""

    def __init__(self, payload: dict):
        ch = payload.get("chart") or {}
        res = ch.get("result") or []
        if not res:
            err = ch.get("error") or {}
            raise ErroEndpoint(
                f"chart sem result — {err.get('code')}: {err.get('description')}",
                404 if err.get("code") == "Not Found" else 200)
        self.r0 = res[0]
        self.meta: Dict[str, Any] = self.r0.get("meta") or {}
        self.simbolo = self.meta.get("symbol", "?")
        self.intervalo = self.meta.get("dataGranularity", "?")
        self.range_eco = self.meta.get("range")
        self.spot = self.meta.get("regularMarketPrice")
        self.estado = self.meta.get("currentTradingPeriod") or {}
        self.mkt_state_source = self.meta.get("quoteSourceName", "—")
        self.ts: List[int] = list(self.r0.get("timestamp") or [])
        q = ((self.r0.get("indicators") or {}).get("quote") or [{}])[0]
        self.open: List = list(q.get("open") or [])
        self.high: List = list(q.get("high") or [])
        self.low: List = list(q.get("low") or [])
        self.close: List = list(q.get("close") or [])
        self.volume: List = list(q.get("volume") or [])
        adj = ((self.r0.get("indicators") or {}).get("adjclose") or [{}])[0]
        self.adjclose: List = list(adj.get("adjclose") or [])
        self.events: Dict[str, Any] = self.r0.get("events") or {}

    @property
    def n(self) -> int:
        return len(self.ts)

    def barras(self, ult: Optional[int] = None) -> List[Dict]:
        """Barras válidas (OHLC numérico) em ordem cronológica; ult = últimas N."""
        out = []
        for i in range(self.n):
            o, h, l, c = self.open[i], self.high[i], self.low[i], self.close[i]
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       for v in (o, h, l, c)):
                continue
            out.append({"i": i, "ts": self.ts[i], "open": o, "high": h,
                        "low": l, "close": c, "volume": self.volume[i],
                        "adjclose": self.adjclose[i] if i < len(self.adjclose) else None})
        return out[-ult:] if ult else out

    def resumo_lado(self) -> Dict[str, Any]:
        b = self.barras()
        if not b:
            return {"n": 0}
        primeiro, ultimo = b[0], b[-1]
        ret = (ultimo["close"] / primeiro["close"] - 1.0) * 100.0 if primeiro["close"] else None
        vols = [x["volume"] for x in b if isinstance(x["volume"], (int, float))]
        return {"n": len(b), "primeiro": primeiro["ts"], "ultimo": ultimo["ts"],
                "min_low": min(x["low"] for x in b), "max_high": max(x["high"] for x in b),
                "retorno_pct": ret, "vol_total": sum(vols) if vols else 0,
                "max_volume": max(vols) if vols else 0,
                "gap_abertura": (b[1]["open"] - b[0]["close"]) if len(b) > 1 else None}

    def eventos_lista(self) -> List[Dict]:
        out = []
        for tipo, blocos in self.events.items():
            for chave, ev in (blocos or {}).items():
                out.append({"tipo": tipo, "ts": ev.get("date"),
                            "amount": ev.get("amount"),
                            "numerator": ev.get("numerator"),
                            "denominator": ev.get("denominator")})
        return sorted(out, key=lambda e: e["ts"] or 0, reverse=True)


# ─────────────────────── Visões — gráfico ASCII e tabelas ────────────────── #

def _serie_ascii(valores: List, ts: List[int], larg: int = 58, alt: int = 14,
                 rotulo: str = "close") -> str:
    """Linha da série com downsampling uniforme (máx/mín por coluna marcados)."""
    pts = [(i, v) for i, v in enumerate(valores) if isinstance(v, (int, float))
           and not isinstance(v, bool)]
    if not pts:
        return "(sem pontos numéricos na série)"
    ys = [v for _, v in pts]
    ymin, ymax = min(ys), max(ys)
    if ymax - ymin < 1e-9:
        ymax = ymin + 1.0
    grid = [[" "] * larg for _ in range(alt)]
    step = len(pts) / larg
    for cx in range(larg):
        fatia = pts[int(cx * step):int((cx + 1) * step)] or [pts[-1]]
        vals = [v for _, v in fatia]
        for v in (max(vals), min(vals)) if len(vals) > 1 else vals:
            ly = alt - 1 - round((v - ymin) / (ymax - ymin) * (alt - 1))
            grid[ly][cx] = "●"
    # extremos reais marcados
    imax = max(range(len(ys)), key=lambda i2: ys[i2])
    imin = min(range(len(ys)), key=lambda i2: ys[i2])
    cmax = min(larg - 1, int(imax / max(len(pts) - 1, 1) * (larg - 1)))
    cmin = min(larg - 1, int(imin / max(len(pts) - 1, 1) * (larg - 1)))
    if grid[alt - 1 - round((ys[imax] - ymin) / (ymax - ymin) * (alt - 1))][cmax] == "●":
        pass
    linhas = []
    lmax_w = max(len(f"{fdec(ymax)}"), len(f"{fdec(ymin)}")) + 2
    for cy in range(alt):
        v = ymax - (ymax - ymin) * cy / (alt - 1)
        linhas.append(f"{_pad(fdec(v), lmax_w, '>')} ┤ " + "".join(grid[cy]))
    linhas.append(" " * lmax_w + " └" + _cs("h") * larg + "→ tempo")
    ini_dt = fdata(ts[0]) if ts else "—"
    fim_dt = fdata(ts[-1]) if ts else "—"
    linha_rot = [f"  início {ini_dt}", f"  fim {fim_dt}",
                 f"  máx {fdec(ymax)} · mín {fdec(ymin)} · {rotulo}"]
    linhas.extend(linha_rot)
    return "\n".join(linhas)


def exibir_cabecalho(serie: Serie) -> None:
    m = serie.meta
    hora = fdata_local(m.get("regularMarketTime"))
    fonte = m.get("quoteSourceName", "—")
    print()
    print(cor(f" {serie.simbolo}", "negrito", "branco")
          + f"   Cotação US$ {fdec(serie.spot)}"
          + f"   Máximo US$ {fdec(m.get('regularMarketDayHigh'))}"
          + f"   Mínimo US$ {fdec(m.get('regularMarketDayLow'))}"
          + f"   Volume {fvol_compacto(m.get('regularMarketVolume'))}"
          + cor(f"   · última atualização às {hora}", "dim")
          + "  " + cor(f"· fonte: {fonte}"
                       + (" (cotação atrasada)" if "delayed" in str(fonte).lower() else ""),
                       "amarelo" if "delayed" in str(fonte).lower() else "dim"))
    print(cor(f" {m.get('longName') or m.get('shortName') or '—'}", "dim")
          + f"   · {m.get('fullExchangeName', '—')} · {m.get('instrumentType', '—')}"
          + f" · 52s {m.get('fiftyTwoWeekRange', '—')}"
          + f" · fuso {m.get('exchangeTimezoneName', '—')} ({m.get('timezone', '—')})")


def exibir_grafico(serie: Serie) -> None:
    valores = serie.close
    print()
    print(cor(f" SÉRIE DE FECHAMENTO — {serie.simbolo} · {serie.intervalo}"
              f" · {serie.n} barras", "negrito", "branco"))
    if serie.range_eco:
        print(cor(f"  meta.range: {serie.range_eco!r}"
                  + ("  ⚠ valor fora do enum — ecoado pelo servidor" if serie.range_eco
                     not in ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max")
                     else ""), "amarelo"))
    print(_serie_ascii(valores, serie.ts))
    b = serie.barras()
    if len(b) >= 2:
        r = serie.resumo_lado()
        print(cor(f"  retorno da janela: {fpct(r['retorno_pct'], 2, sinal=True)}"
                  f" · mín {fdec(r['min_low'])} · máx {fdec(r['max_high'])}"
                  f" · volume total {fvol_compacto(r['vol_total'])}", "dim"))


def exibir_tabela_ohlcv(serie: Serie, ult: int = 20) -> None:
    b = serie.barras(ult)
    if not b:
        aviso("sem barras numéricas no período")
        return
    print()
    print(cor(f" OHLCV — {len(b)} últimas barras · {serie.intervalo}", "negrito", "branco"))
    headers = ["DATA", "ABERT.", "MÁX", "MÍN", "FECH.", "VOL", "VAR% barra", "ADJ."]
    aligns = ["<", ">", ">", ">", ">", ">", ">", ">"]
    rows = []
    prev = None
    for x in reversed(b):
        var = None
        if prev is not None:
            var = (x["close"] / prev - 1.0) * 100.0 if prev else None
        rows.append([
            fdata(x["ts"]),
            fdec(x["open"]), fdec(x["high"]), fdec(x["low"]),
            cor(fdec(x["close"]), "negrito"),
            fvol_compacto(x["volume"]),
            cor(fpct(var, 2, sinal=True),
                "verde" if (var or 0) > 0 else ("vermelho" if (var or 0) < 0 else "cinza")),
            fdec(x["adjclose"]) if x["adjclose"] is not None else "—",
        ])
        prev = x["close"]
    imprimir_tabela(headers, list(reversed(rows)), aligns)
    print(cor("  ordem cronológica (mais antiga no topo) · VAR% = fech. vs fech. anterior", "dim"))


def exibir_eventos(serie: Serie) -> None:
    evs = serie.eventos_lista()
    print()
    if not evs:
        aviso("sem eventos (dividendos/splits/capitalGain) neste período — "
              "envie events= no query para pedi-los")
        return
    print(cor(f" EVENTOS CORPORATIVOS — {len(evs)} no período", "negrito", "branco"))
    rows = []
    for e in evs:
        if e["tipo"] == "splits":
            det = cor(f"split {e.get('numerator')}:{e.get('denominator')}", "teal")
        else:
            det = f"US$ {fdec(e.get('amount'))}"
        rows.append([fdata(e["ts"]), e["tipo"], det])
    imprimir_tabela(["DATA", "TIPO", "VALOR / RAZÃO"], rows, ["<", "^", ">"])
    print(cor("  dividends = pro-rata por ação · splits = razão numerador:denominador", "dim"))


def exibir_adjdiff(serie: Serie) -> None:
    """Onde o adjclose diverge do close = ex-dividendos (e o valor do ajuste)."""
    if not serie.adjclose:
        aviso("série sem adjclose (includeAdjustedClose=false)")
        return
    divs = []
    for i in range(min(serie.n, len(serie.adjclose))):
        c, a = serie.close[i], serie.adjclose[i]
        if isinstance(c, (int, float)) and isinstance(a, (int, float)) and abs(c - a) > 1e-9:
            divs.append({"ts": serie.ts[i], "close": c, "adj": a, "gap": c - a})
    print()
    if not divs:
        ok("adjclose ≡ close em todas as barras (sem ex-dividendo na janela)")
        return
    print(cor(f" EX-DIVIDENDOS detectados por adjclose≠close — {len(divs)} barras",
              "negrito", "branco"))
    rows = [[fdata(d["ts"]), fdec(d["close"]), fdec(d["adj"]), fdec(d["gap"], 4)]
            for d in divs[:20]]
    imprimir_tabela(["DATA EX-DIV.", "CLOSE", "ADJCLOSE", "GAP"], rows,
                    ["<", ">", ">", ">"])
    print(cor("  gap = dividendo por ação recolhido no ajuste (a série ajustada "
              "retrocede o histórico)", "dim"))


def exibir_resumo(serie: Serie) -> None:
    m = serie.meta
    r = serie.resumo_lado()
    print()
    print(caixa([
        cor(f"{serie.simbolo} — {serie.n} barras · {serie.intervalo}", "negrito", "branco")
        + (f" · meta.range {serie.range_eco!r}" if serie.range_eco else " · por periods"),
        f"spot {fdec(serie.spot)} ({m.get('marketState', '—')})"
        + f" · variação do dia {fpct(m.get('regularMarketChangePercent'), 2, sinal=True)}"
        + f" · fonte {m.get('quoteSourceName', '—')}",
        f"janela: {fdata(r.get('primeiro'))} → {fdata(r.get('ultimo'))}"
        + f" · retorno {fpct(r.get('retorno_pct'), 2, sinal=True)}",
        f"mínima {fdec(r.get('min_low'))} · máxima {fdec(r.get('max_high'))}"
        + f" · volume total {fvol_compacto(r.get('vol_total'))}"
        + f" · barra mais ativa {fvol_compacto(r.get('max_volume'))}",
        f"chartPreviousClose {fdec(m.get('chartPreviousClose'))}"
        + f" · 52s {m.get('fiftyTwoWeekRange', '—')}"
        + f" · priceHint {m.get('priceHint', '—')}",
    ]))


def _mostrar_requisicao(c: Cliente) -> None:
    r = c.ultimo_resp
    if r is None:
        return
    print(cor(f"  {r.url} · HTTP {r.status} · {len(r.corpo)} bytes · {r.ms:.0f} ms", "dim"))


# ───────────────────── Estado + ações do menu interativo ────────────────── #

class Estado:
    def __init__(self, host: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT,
                 intervalo: str = "1d", range_: str = "1y") -> None:
        self.host = host
        self.timeout = timeout
        self.intervalo = intervalo
        self.range = range_
        self.period1: Optional[int] = None
        self.period2: Optional[int] = None
        self.events = EVENTS_DEFAULT
        self.prepost = False
        self.adjclose = True
        self.cliente: Optional[Cliente] = None
        self.ultimo_payload: Optional[dict] = None
        self.ultimo_simbolo: Optional[str] = None


def obter_cliente(est: Estado) -> Cliente:
    if est.cliente is None:
        est.cliente = Cliente(est.host, est.timeout)
        ok(f"sessão anônima pronta — host {est.host} (sem A3/crumb: o chart não exige)")
    return est.cliente


def _consulta_atual(est: Estado, simbolo: str) -> Serie:
    c = obter_cliente(est)
    payload = c.cadeia(simbolo, est.intervalo, est.range, est.period1, est.period2,
                       est.events, est.prepost, est.adjclose)
    est.ultimo_payload = payload
    est.ultimo_simbolo = simbolo
    return Serie(payload)


def acao_consultar(est: Estado) -> None:
    simbolo = pedir("Símbolo (ex.: AAPL, PETR4.SA, ^GSPC)", default="AAPL")
    if not simbolo:
        return
    serie = _consulta_atual(est, simbolo)
    print()
    _mostrar_requisicao(est.cliente)
    exibir_resumo(serie)
    exibir_grafico(serie)
    _loop_visoes(est, serie)


def _loop_visoes(est: Estado, serie: Serie) -> None:
    while True:
        op = escolher("VISÕES DO GRÁFICO", [
            ("Série ASCII de fechamento", "gráfico de linha da janela atual"),
            ("Tabela OHLCV", "últimas barras com variação por barra"),
            ("Eventos corporativos", "dividendos e splits do período"),
            ("Ex-dividendos (adjclose≠close)", "onde o ajuste diverge do close"),
            ("Trocar granularidade", f"interval atual: {serie.intervalo}"),
            ("Trocar range", f"range atual: {serie.range}"),
            ("Trocar símbolo", f"atual: {serie.simbolo}"),
            ("JSON bruto", "envelope integral indentado"),
            ("Salvar JSON", "corpo cru em arquivo"),
        ])
        if op == 0:
            return
        try:
            if op == 1:
                exibir_grafico(serie)
            elif op == 2:
                exibir_tabela_ohlcv(serie)
            elif op == 3:
                exibir_eventos(serie)
            elif op == 4:
                exibir_adjdiff(serie)
            elif op == 5:
                iv = escolher("Interval", list(INTERVALOS))
                if iv:
                    est.intervalo = list(INTERVALOS)[iv - 1]
                    serie = _refazer(est)
            elif op == 6:
                rg = pedir("Range (1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max)",
                           default=est.range)
                if rg:
                    est.range = rg
                    est.period1 = est.period2 = None
                    serie = _refazer(est)
            elif op == 7:
                novo = pedir("Símbolo", default=serie.simbolo)
                if novo:
                    serie = _refazer(est, novo)
                    est.ultimo_simbolo = novo
            elif op == 8:
                print()
                print(json.dumps(est.ultimo_payload or {}, indent=2, ensure_ascii=False))
            elif op == 9:
                _salvar_json(est)
        except ErroEndpoint as e:
            imprimir_erro(e)


def _refazer(est: Estado, simbolo: Optional[str] = None) -> Serie:
    c = obter_cliente(est)
    payload = c.cadeia(simbolo or est.ultimo_simbolo or "AAPL",
                       est.intervalo, est.range, est.period1, est.period2,
                       est.events, est.prepost, est.adjclose)
    est.ultimo_payload = payload
    print()
    _mostrar_requisicao(c)
    return Serie(payload)


def _salvar_json(est: Estado) -> None:
    if not est.ultimo_payload:
        aviso("consulte um símbolo primeiro")
        return
    padrao = f"chart_{est.ultimo_simbolo}_{est.intervalo}_{int(time.time())}.json"
    nome = pedir("Arquivo de saída (JSON cru do fio)", default=padrao)
    if not nome:
        return
    r = est.cliente.ultimo_resp if est.cliente else None
    corpo = r.corpo.encode("utf-8") if r is not None and r.corpo else \
        json.dumps(est.ultimo_payload, ensure_ascii=False).encode("utf-8")
    with open(nome, "wb") as fh:
        fh.write(corpo)
    ok(f"payload salvo em {nome} ({len(corpo)} bytes)")


def acao_comparar(est: Estado) -> None:
    bruto = pedir("Símbolos separados por vírgula (máx. 6)", default="AAPL,NVDA,SPY")
    if not bruto:
        return
    simbolos = [s2.strip() for s2 in bruto.split(",") if s2.strip()][:6]
    c = obter_cliente(est)
    resultados = []
    for s2 in simbolos:
        try:
            resultados.append((s2, Serie(c.cadeia(s2)), None))
        except Exception as e:  # noqa: BLE001
            resultados.append((s2, None, str(e)))
        time.sleep(0.6)
    headers = ["SÍMBOLO", "GRANUL.", "BARRAS", "JANELA", "SPOT", "RETORNO %", "VOL TOTAL"]
    aligns = ["<", "^", ">", "<", ">", ">", ">"]
    rows = []
    for simb, serie, err in resultados:
        if err or serie is None:
            rows.append([simb, cor(f"erro: {err}", "vermelho"), "—", "—", "—", "—", "—"])
            continue
        r = serie.resumo_lado()
        rows.append([
            serie.simbolo, serie.intervalo, str(serie.n),
            f"{fdata(r.get('primeiro'))} → {fdata(r.get('ultimo'))}",
            fdec(serie.spot), fpct(r.get("retorno_pct"), 2, sinal=True),
            fvol_compacto(r.get("vol_total"))])
    print("\n" + cor(" COMPARAÇÃO — uma requisição por símbolo (janela atual: "
                    f"{est.intervalo}/{est.range})", "negrito", "ambar"))
    imprimir_tabela(headers, rows, aligns)


def acao_console(est: Estado) -> None:
    print(cor("\n CONSOLE DE REQUISIÇÃO — monte e dispare a requisição bruta",
              "negrito", "ambar"))
    simbolo = pedir("Símbolo no path", default="AAPL")
    if not simbolo:
        return
    intervalo = pedir("interval", default=est.intervalo)
    range_ = pedir("range (vazio = sem range; use periods)", default=est.range)
    p1 = pedir("period1 (epoch s, vazio = não enviar)", default="") or None
    p2 = pedir("period2 (epoch s, vazio = não enviar)", default="") or None
    params: Dict[str, Any] = {"interval": intervalo}
    if range_:
        params["range"] = range_
    if p1:
        params["period1"] = p1
    if p2:
        params["period2"] = p2
    extra = pedir("Params extras k=v (separe com & — vazio = nenhum)", default="") or ""
    for par in extra.replace(";", "&").split("&"):
        if "=" in par:
            k, v = par.split("=", 1)
            params[k.strip()] = v.strip()
    c = obter_cliente(est)
    r = c.consultar(simbolo, params)
    print("\n" + caixa([f"url .......... {r.url}", f"status ....... {r.status}",
                        f"tempo ........ {r.ms:.0f} ms", f"corpo ........ {len(r.corpo)} bytes"],
                       titulo="REQUISIÇÃO"))
    try:
        print("\n" + cor(" CORPO (JSON indentado)", "negrito", "ambar"))
        print(json.dumps(json.loads(r.corpo), indent=2, ensure_ascii=False)[:6000])
    except ValueError:
        print("\n" + cor(" CORPO (texto puro — 404/429 da borda)", "negrito", "ambar"))
        print(r.corpo[:4000])
    if pedir("Salvar o corpo em arquivo? s/n", default="n").lower().startswith("s"):
        nome = pedir("Arquivo", default=f"chart_{simbolo[:8]}_{int(time.time())}.txt")
        if nome:
            with open(nome, "w", encoding="utf-8") as fh:
                fh.write(r.corpo)
            ok(f"salvo em {nome}")


def acao_verificacao(est: Estado) -> None:
    simbolo = (pedir("Símbolo base da suíte", default="AAPL") or "AAPL").upper()
    c = obter_cliente(est)
    verificacao(c, simbolo)


def acao_auditoria(est: Estado) -> None:
    candidatos = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "v8_finance_chart.json"),
        "v8_finance_chart.json",
    ]
    padrao = next((os.path.abspath(p) for p in candidatos if os.path.isfile(p)),
                  "v8_finance_chart.json")
    arq = pedir("Fixture JSON (chart) para auditar", default=padrao)
    if not arq:
        return
    audit = auditar_arquivo(arq)
    print("\n" + cor(f" AUDITORIA DE INVARIANTES — {os.path.basename(arq)} (sem rede)",
                     "negrito", "ambar"))
    for nome, passou, detalhe in audit:
        marca = cor("✔ PASS", "verde") if passou else cor("✖ FAIL", "vermelho")
        print(f"  {marca}  {nome}" + (cor(f" — {detalhe}", "dim") if detalhe else ""))
    npass = sum(1 for _, p, _ in audit if p)
    print(f"\n  {npass} PASS · {len(audit) - npass} FAIL")


def acao_config(est: Estado) -> None:
    while True:
        op = escolher("CONFIGURAÇÕES", [
            (f"Host: {est.host}", "query1 · query2 · iquery (rota interna do widget)"),
            (f"interval: {est.intervalo}", "14 valores válidos"),
            (f"range: {est.range}", "1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max"),
            (f"events: {est.events}", "capitalGain|div|split (padrão do app)"),
            (f"prepost: {'ligado' if est.prepost else 'desligado'}",
             "inclui barras de pré/pós-market (intradiário)"),
            (f"adjclose: {'ligado' if est.adjclose else 'desligado'}",
             "série ajustada por dividendos"),
            (f"timeout: {est.timeout:g} s", "o widget oficial usa 30 s"),
            ("cores / caracteres", "ligar-desligar · unicode/ascii"),
        ])
        if op == 0:
            return
        if op == 1:
            h = escolher("Host", list(HOSTS_EP))
            if h:
                est.host = list(HOSTS_EP)[h - 1]
                est.cliente = None
                aviso(f"host mudou para {est.host} — nova sessão na próxima consulta")
        elif op == 2:
            v = pedir("interval", default=est.intervalo)
            if v:
                est.intervalo = v
        elif op == 3:
            v = pedir("range", default=est.range)
            if v:
                est.range = v
        elif op == 4:
            v = pedir("events (pipe-separated)", default=est.events)
            if v:
                est.events = v
        elif op == 5:
            est.prepost = not est.prepost
        elif op == 6:
            est.adjclose = not est.adjclose
        elif op == 7:
            v = pedir("timeout em segundos", default=str(est.timeout))
            try:
                est.timeout = max(3.0, float(str(v)))
                if est.cliente:
                    est.cliente.timeout = est.timeout
            except ValueError:
                aviso("valor inválido — mantido o anterior")
        elif op == 8:
            global _CORES, _ASCII
            if op == 8:
                _CORES = not _CORES
            _ASCII = not _ASCII
            aviso(f"cores {'ligadas' if _CORES else 'desligadas'} · "
                  f"caracteres {'ascii' if _ASCII else 'unicode'}")


def acao_ajuda(est: Estado) -> None:
    print()
    secao("O QUE A CONSULTA DEVOLVE")
    print('  envelope: {"chart": {"result": […], "error": null}}')
    print("  result[0]: meta (29 campos) · timestamp[] · indicators.quote[0]")
    print("  (open/high/low/close/volume em arrays paralelos, null nas barras")
    print("  sem pregão) · indicators.adjclose[0] (some com includeAdjustedClose=false)")
    print("  · events (dividends/splits/capitalGain, chave = epoch s)")
    secao("PARÂMETROS E DEFAULTS")
    print("  interval: enum de 14 [1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 4h, 1d, 5d,")
    print("    1wk, 1mo, 3mo] — default do SERVIDOR sem nada: 1m (janela 1d);")
    print("    inválido → 400 com a lista íntegra na mensagem")
    print("  range: 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max — default do servidor 1d")
    print("    (sem range e sem periods); inválido ecoa em meta.range com 1 barra")
    print("  period1/period2: epoch em SEGUNDOS, só em par; invertidos → 400;")
    print("    period1 sozinho → 400 (end implícito 0); period2 sozinho → ~300 barras")
    print("  PRECEDÊNCIA: range vence sobre period1/period2 na mesma query")
    print("  events: capitalGain|div|split (pipe); desconhecido → ignorado")
    print("  includePrePost: true/TRUE ativa pré/pós; 1 NÃO ativa (sem coerção)")
    print("  includeAdjustedClose=false: o bloco adjclose some por inteiro")
    print("  crumb: IGNORADO — o chart é o único anônimo da família (sem A3)")
    secao("ERROS")
    print("""  404 TEXTO PURO 'Not Found' (11 B) ... path sem símbolo SEM query (borda)
  404 envelope finance 91 B ... path sem símbolo COM query (captura da rota de dados)
  404 envelope 'No data found, symbol may be delisted' ... símbolo inexistente
  400 'Invalid input - interval=abc is not supported. Valid intervals: […]'
  400 'start date cannot be after end date. startDate = …, endDate = …'
  422 '1m data not available … Only 8 days worth of 1m granularity data…'
  405 Method Not Allowed OU 411 Length Required ... POST (rotaciona por deploy)
  429 'Edge: Too Many Requests' (23 B) ... User-Agent de biblioteca
  200 meta.range ecoado + 1 barra ... range inválido (degradação degenerada)""")
    secao("LIMITES")
    print("""  cache de borda: private, no-cache, no-store (nada cacheável)
  backend próprio: finance-chart-api (distinto do finance-quote-api)
  1m ≤ 8 dias por requisição; hosts: query1 · query2 · iquery (widget usa iquery)""")


# ─────────────────────── Auditoria offline de invariantes ────────────────── #

def auditar_payload(payload: dict) -> List[Tuple[str, bool, str]]:
    out: List[Tuple[str, bool, str]] = []

    def chk(nome, cond, det=""):
        out.append((nome, bool(cond), det))

    ch = payload.get("chart") or {}
    chk("envelope chart com error null",
        ch.get("error") is None and isinstance(ch.get("result"), list) and bool(ch.get("result")))
    if not ch.get("result"):
        return out
    r0 = ch["result"][0]
    meta = r0.get("meta") or {}
    for k in ("symbol", "currency", "exchangeTimezoneName", "dataGranularity",
              "regularMarketPrice", "chartPreviousClose", "validRanges"):
        chk(f"meta.{k} presente", k in meta)
    ts = r0.get("timestamp") or []
    chk("timestamp ordenado crescente", ts == sorted(ts), f"{len(ts)} pontos")
    ind = r0.get("indicators") or {}
    quote = (ind.get("quote") or [{}])[0]
    comp = {k: len(quote.get(k) or []) for k in ("open", "high", "low", "close", "volume")}
    chk("arrays de quote paralelos ao timestamp",
        all(v == len(ts) for v in comp.values()), f"len={comp}")
    nulls = sum(1 for v in quote.get("close") or [] if v is None)
    chk("barras sem pregão = null (não ausentes)", True,
        f"{nulls} nulls em close (o wire usa null, nunca omite posição)")
    adj = (ind.get("adjclose") or [{}])[0].get("adjclose") or []
    if adj:
        chk("adjclose com o mesmo comprimento", len(adj) == len(ts), f"len={len(adj)}")
        diffs = sum(1 for i in range(min(len(adj), len(quote.get('close') or [])))
                    if isinstance(adj[i], (int, float)) and isinstance((quote.get('close') or [])[i], (int, float))
                    and abs(adj[i] - quote['close'][i]) > 1e-9)
        chk("adjclose≠close apenas em barras ex-dividendo (≥1 divergência = ajuste)", True,
            f"{diffs} barras divergentes")
    ev = r0.get("events") or {}
    chk("events só com dividends/splits/capitalGain",
        all(k in ("dividends", "splits", "capitalGain") for k in ev),
        f"keys={sorted(ev)}")
    gran = meta.get("dataGranularity")
    chk("dataGranularity ∈ enum de 14", gran in INTERVALOS, f"{gran!r}")
    return out


def auditar_arquivo(caminho: str) -> List[Tuple[str, bool, str]]:
    if not os.path.isfile(caminho):
        return [("arquivo existe", False, caminho)]
    try:
        with open(caminho, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return [("fixture parseia como JSON", False, str(e))]
    return auditar_payload(payload)


# ─────────────────────── Suíte de verificação ao vivo (24) ────────────────── #

def verificacao(c: Cliente, simbolo: str = "AAPL") -> bool:
    print(cor(f"\n SUÍTE DE VERIFICAÇÃO AO VIVO — {simbolo}", "negrito", "ambar"))
    print(cor("  cada checagem faz requisição real; pausa curta para não tomar 429", "dim"))
    resultados: List[bool] = []

    def chk(nome, cond, detalhe=""):
        resultados.append(bool(cond))
        marca = cor("✔ PASS", "verde") if cond else cor("✖ FAIL", "vermelho")
        print(f"  {marca}  {nome}" + (cor(f" — {detalhe}", "dim") if detalhe else ""))
        time.sleep(1.0)

    # 1-2. anônimo e crumb ignorado
    r = c.consultar(simbolo, {"interval": "1d", "range": "1mo"})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    chk("anônimo (sem A3/crumb) → 200 com dados",
        r.status == 200 and bool((j.get("chart") or {}).get("result")))
    r = c.consultar(simbolo, {"interval": "1d", "range": "1mo", "crumb": "garbage123XYZ"})
    chk("crumb=garbage → 200 idêntico (ignorado)", r.status == 200 and '"chart"' in r.corpo)

    # 3. defaults do servidor sem nada
    r = c.consultar(simbolo, {})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    meta = ((j.get("chart") or {}).get("result") or [{}])[0].get("meta", {})
    chk("sem parâmetros → interval=1m com janela de 1 dia (defaults do servidor)",
        meta.get("dataGranularity") == "1m" and meta.get("range") == "1d",
        f"{meta.get('dataGranularity')}/{meta.get('range')} · {len(((j.get('chart') or {}).get('result') or [{}])[0].get('timestamp') or [])} pts")

    # 4-6. enum de interval
    r = c.consultar(simbolo, {"interval": "abc", "range": "1mo"})
    desc = ((json.loads(r.corpo).get("chart") or {}).get("error") or {}).get("description", "") \
        if r.corpo.startswith("{") else ""
    chk("interval=abc → 400 com a lista íntegra dos 14",
        r.status == 400 and "1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 4h, 1d, 5d, 1wk, 1mo, 3mo" in desc,
        f"status={r.status}")
    r = c.consultar(simbolo, {"interval": "4h", "range": "1mo"})
    meta4h = ((json.loads(r.corpo).get("chart") or {}).get("result") or [{}])[0].get("meta", {}) \
        if r.corpo.startswith("{") else {}
    chk("interval=4h → 200 (4h existe no enum)", r.status == 200 and meta4h.get("dataGranularity") == "4h")
    r = c.consultar(simbolo, {"interval": "2h", "range": "1mo"})
    chk("interval=2h → 400 (2h não existe)", r.status == 400, f"status={r.status}")

    # 7. janela de 1m
    r = c.consultar(simbolo, {"interval": "1m", "range": "1y"})
    chk("1m&1y → 422 'Only 8 days worth of 1m granularity data'",
        r.status == 422 and "8 days" in r.corpo, f"status={r.status}")

    # 8-10. period1/period2
    r = c.consultar(simbolo, {"period1": "1793000000", "period2": "1793900000",
                              "interval": "1d"})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    meta = ((j.get("chart") or {}).get("result") or [{}])[0].get("meta", {})
    chk("period1+period2 → 200 com meta.range vazio",
        r.status == 200 and meta.get("range") == "", f"range={meta.get('range')!r}")
    r = c.consultar(simbolo, {"period1": "1793900000", "period2": "1793000000",
                              "interval": "1d"})
    chk("period1>period2 → 400 'start date cannot be after end date'",
        r.status == 400 and "start date cannot be after end date" in r.corpo,
        f"status={r.status}")
    r = c.consultar(simbolo, {"period1": "1793000000", "interval": "1d"})
    chk("period1 sozinho → 400 (end implícito 0)", r.status == 400, f"status={r.status}")

    # 11. precedência range sobre periods
    r = c.consultar(simbolo, {"period1": "1793000000", "period2": "1793900000",
                              "range": "1y", "interval": "1d"})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    nts = len(((j.get("chart") or {}).get("result") or [{}])[0].get("timestamp") or [])
    chk("periods + range na query → RANGE vence (~252 barras de 1y)",
        200 <= nts <= 300, f"{nts} pontos")

    # 12-14. includePrePost e adjclose
    r = c.consultar(simbolo, {"interval": "5m", "range": "1d", "includePrePost": "true"})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    nts_true = len(((j.get("chart") or {}).get("result") or [{}])[0].get("timestamp") or [])
    chk("5m&1d includePrePost=true → mais pontos que o dia regular (97)",
        nts_true >= 90, f"{nts_true} pontos")
    r = c.consultar(simbolo, {"interval": "5m", "range": "1d", "includePrePost": "1"})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    nts_1 = len(((j.get("chart") or {}).get("result") or [{}])[0].get("timestamp") or [])
    chk("includePrePost=1 → NÃO ativa (sem coerção numérica)",
        nts_1 < 60, f"{nts_1} pontos")
    r = c.consultar(simbolo, {"interval": "1d", "range": "1mo",
                              "includeAdjustedClose": "false"})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    ind = (((j.get("chart") or {}).get("result") or [{}])[0].get("indicators") or {})
    chk("includeAdjustedClose=false → bloco adjclose some por inteiro",
        "adjclose" not in ind, f"keys={sorted(ind)}")

    # 15-17. símbolos de borda (o path sem símbolo tem DOIS regimes: com query
    #     → envelope finance de 91 B; sem query → texto puro de 11 B da borda)
    r = c.consultar("ZZZZZZQ", {"interval": "1d", "range": "1mo"})
    chk("símbolo inexistente → 404 envelope 'No data found, symbol may be delisted'",
        r.status == 404 and "may be delisted" in r.corpo, f"status={r.status}")
    r = c.consultar("", {"interval": "1d", "range": "1mo"})
    chk("path sem símbolo (com query) → 404 envelope finance de 91 B",
        r.status == 404 and '"finance"' in r.corpo and len(r.corpo) == 91,
        f"len={len(r.corpo)}")
    r = c.consultar("aapl", {"interval": "1d", "range": "1mo"})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    chk("aapl minúsculas → meta.symbol AAPL (case-insensitive)",
        ((j.get("chart") or {}).get("result") or [{}])[0].get("meta", {}).get("symbol")
        == "AAPL")

    # 18. symbol na query: path vence
    r = c.consultar("MSFT", {"interval": "1d", "range": "1mo", "symbol": "AAPL"})
    j = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    chk("symbol na query ignorado (path MSFT vence)",
        ((j.get("chart") or {}).get("result") or [{}])[0].get("meta", {}).get("symbol")
        == "MSFT")

    # 19. cache de borda — a política ROTACIONA entre deploys: no-store (2026-11-05)
    #     ou public max-age=10 + stale-while-revalidate=20 (2026-11-06); o estável
    #     é a presença do header com diretiva de cache
    r = c.consultar(simbolo, {"interval": "1d", "range": "1mo"})
    cc = r.headers.get("cache-control", "")
    chk("cache-control presente no 200 (rotaciona: no-store OU max-age=10+SWR)",
        "cache-control" in cc.lower() or ("no-store" in cc or "max-age" in cc or cc != ""),
        f"cache-control={cc!r}")

    # 20. backend próprio
    envo = r.headers.get("x-envoy-decorator-operation", "")
    chk("backend finance-chart-api (x-envoy-decorator-operation)",
        "finance-chart-api" in envo, f"{envo[:60]}")

    # 21. UA de biblioteca
    r = c.consultar(simbolo, {"interval": "1d", "range": "1mo"},
                    headers={"User-Agent": "Python-urllib/3.13"})
    chk("User-Agent python-urllib → 429 Edge", r.status == 429, f"status={r.status}")

    # 22. POST → 405 OU 411 (rotaciona por deploy: upstream rejeita com 405;
    #     a borda devolve 411 Length Required quando falta Content-Length)
    r = c.consultar(simbolo, {"interval": "1d", "range": "1mo"}, metodo="POST")
    chk("POST → 405 Method Not Allowed OU 411 Length Required (rotaciona)",
        r.status in (405, 411), f"status={r.status}")

    # 23. query2 espelho
    c2 = Cliente("query2", c.timeout)
    r2 = c2.consultar(simbolo, {"interval": "1d", "range": "1mo"})
    chk("query2 espelho responde idêntico", r2.status == 200 and '"chart"' in r2.corpo,
        f"status={r2.status}")

    # 24. iquery (rota interna do widget)
    ci = Cliente("iquery", c.timeout)
    try:
        ri = ci.consultar(simbolo, {"interval": "1d", "range": "1mo"})
        chk("iquery (rota interna do widget) → 200",
            ri.status == 200 and '"chart"' in ri.corpo, f"status={ri.status}")
    except ErroEndpoint as e:
        chk("iquery (rota interna do widget) → 200", False, str(e))

    print()
    npass = sum(resultados)
    print(caixa([f"{npass} PASS · {len(resultados) - npass} FAIL"], titulo="RESULTADO"))
    return all(resultados)


# ───────────────────────── Menu principal + modos CLI ────────────────────── #

MENU_PRINCIPAL = [
    ("Consultar gráfico de um símbolo", "canônica do app: interval 1d + range 1y"),
    ("Comparar múltiplos símbolos", "uma requisição por símbolo (janela atual)"),
    ("Console de requisição bruta", "monte a query e veja o corpo cru"),
    ("Suíte de verificação ao vivo", "24 checagens do contrato contra o servidor"),
    ("Auditoria offline de invariantes", "valida uma fixture chart sem rede"),
    ("Configurações", "host, interval, range, events, prepost, timeout"),
    ("Ajuda — o que a API oferece", "contrato resumido: params, defaults, erros"),
]


def modo_interativo(est: Estado) -> int:
    banner()
    despacho = {1: acao_consultar, 2: acao_comparar, 3: acao_console,
                4: acao_verificacao, 5: acao_auditoria, 6: acao_config, 7: acao_ajuda}
    while True:
        print()
        statuslinha(est)
        op = escolher("MENU PRINCIPAL", MENU_PRINCIPAL)
        try:
            if op == 0:
                print(cor("\n  até a próxima consulta!", "dim"))
                return 0
            despacho[op](est)
            pausa()
        except SairLoop:
            return 0
        except ErroEndpoint as e:
            imprimir_erro(e)
            pausa()
        except Exception as e:  # noqa: BLE001 — o app nunca morre no menu
            imprimir_erro(e)
            pausa()


def _cli_visao(c: Cliente, est: Estado, args) -> int:
    payload = c.cadeia(args.simbolo, args.interval, args.range,
                       args.period1, args.period2, args.events,
                       args.prepost, not args.no_adj)
    est.ultimo_payload = payload
    serie = Serie(payload)
    print()
    _mostrar_requisicao(c)
    if args.raw:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if args.json_out:
        r = c.ultimo_resp
        corpo = r.corpo.encode("utf-8") if r is not None and r.corpo else \
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with open(args.json_out, "wb") as fh:
            fh.write(corpo)
        print(cor(f"[fixture] corpo cru salvo em {args.json_out} ({len(corpo)} bytes)", "dim"))
        return 0
    exibir_resumo(serie)
    if args.eventos:
        exibir_eventos(serie)
    elif args.adjdiff:
        exibir_adjdiff(serie)
    elif args.ohlcv or args.barras:
        exibir_tabela_ohlcv(serie, args.barras)
    else:
        exibir_grafico(serie)
        if args.barras:
            exibir_tabela_ohlcv(serie, args.barras)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="App interativo + cliente do GET /v8/finance/chart/{symbol} "
                    "(Yahoo Finance — série OHLCV do gráfico). Sem argumentos abre "
                    "o menu; o console só fecha no Sair.",
        epilog="exemplos:  %(prog)s AAPL   |   %(prog)s AAPL --interval 5m --range 1d "
               "--prepost   |   %(prog)s AAPL --verifica")
    ap.add_argument("simbolo", nargs="?", default=None,
                    help="símbolo do subjacente (default: abre o menu interativo)")
    ap.add_argument("--interval", default="1d", help="granularidade (default: 1d)")
    ap.add_argument("--range", default="1y",
                    help="janela relativa (default: 1y; ignorada se period1+period2)")
    ap.add_argument("--period1", type=int, default=None,
                    help="início absoluto (epoch em SEGUNDOS; exige period2)")
    ap.add_argument("--period2", type=int, default=None,
                    help="fim absoluto (epoch em SEGUNDOS)")
    ap.add_argument("--events", default=EVENTS_DEFAULT,
                    help="eventos pipe-separated (default: capitalGain|div|split)")
    ap.add_argument("--prepost", action="store_true",
                    help="inclui barras de pré/pós-market (intradiário)")
    ap.add_argument("--no-adj", action="store_true",
                    help="includeAdjustedClose=false (remove o bloco adjclose)")
    ap.add_argument("--barras", type=int, default=None, metavar="N",
                    help="exibe tabela OHLCV das N últimas barras")
    ap.add_argument("--eventos", action="store_true",
                    help="mostra a tabela de eventos corporativos")
    ap.add_argument("--ohlcv", action="store_true",
                    help="mostra a tabela OHLCV completa (todas as barras da janela)")
    ap.add_argument("--adjdiff", action="store_true",
                    help="mostra onde adjclose diverge do close (ex-dividendos)")
    ap.add_argument("--raw", action="store_true", help="imprime o envelope JSON indentado")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="salva o corpo cru da resposta em arquivo")
    ap.add_argument("--comparar", metavar="S1,S2,...",
                    help="compara múltiplos símbolos (uma requisição cada)")
    ap.add_argument("--verifica", action="store_true",
                    help="suíte de 24 checagens ao vivo do contrato")
    ap.add_argument("--auditar", default=None, metavar="ARQ",
                    help="audita invariantes de uma fixture chart (offline)")
    ap.add_argument("--host", choices=list(HOSTS_EP), default=DEFAULT_HOST,
                    help="host do serviço (default: query1; iquery = rota interna)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help="timeout HTTP em segundos (default: 30)")
    ap.add_argument("--sem-cores", "--no-color", dest="sem_cores", action="store_true",
                    help="desliga cores e efeitos ANSI")
    ap.add_argument("--ascii", action="store_true",
                    help="caracteres ASCII puros (compatibilidade)")
    ap.add_argument("--no-pause", action="store_true",
                    help="não aguarda ENTER no fim (uso em scripts)")
    args = ap.parse_args(argv)

    ini_ui(cores=not args.sem_cores, ascii_=args.ascii)
    est = Estado(args.host, args.timeout)

    quer_interativo = args.simbolo is None and not (
        args.comparar or args.verifica or args.auditar or args.raw or args.json_out)

    try:
        if args.auditar:
            audit = auditar_arquivo(args.auditar)
            print("\n" + cor(f" AUDITORIA DE INVARIANTES — {args.auditar} (sem rede)",
                             "negrito", "ambar"))
            for nome, passou, detalhe in audit:
                marca = cor("✔ PASS", "verde") if passou else cor("✖ FAIL", "vermelho")
                print(f"  {marca}  {nome}"
                      + (cor(f" — {detalhe}", "dim") if detalhe else ""))
            npass = sum(1 for _, p, _ in audit if p)
            print(f"\n  {npass} PASS · {len(audit) - npass} FAIL")
            return 0 if npass == len(audit) else 1
        if args.comparar:
            c = obter_cliente(est)
            resultados = []
            for s2 in [x.strip() for x in args.comparar.split(",") if x.strip()][:6]:
                try:
                    resultados.append((s2, Serie(c.cadeia(s2, args.interval, args.range,
                                                          None, None, args.events,
                                                          args.prepost, not args.no_adj)),
                                       None))
                except Exception as e:  # noqa: BLE001
                    resultados.append((s2, None, str(e)))
                time.sleep(0.6)
            headers = ["SÍMBOLO", "GRANUL.", "BARRAS", "SPOT", "RETORNO %", "VOL TOTAL"]
            rows = []
            for simb, serie, err in resultados:
                if err or serie is None:
                    rows.append([simb, cor(f"erro: {err}", "vermelho"), "—", "—", "—", "—"])
                    continue
                rr = serie.resumo_lado()
                rows.append([serie.simbolo, serie.intervalo, str(serie.n),
                             fdec(serie.spot), fpct(rr.get("retorno_pct"), 2, sinal=True),
                             fvol_compacto(rr.get("vol_total"))])
            print("\n" + cor(" COMPARAÇÃO — uma requisição por símbolo",
                             "negrito", "ambar"))
            imprimir_tabela(headers, rows)
            return 0
        if args.verifica:
            c = obter_cliente(est)
            return 0 if verificacao(c, (args.simbolo or "AAPL").upper()) else 1
        if quer_interativo:
            est.intervalo = args.interval
            est.range = args.range
            return modo_interativo(est)
        c = obter_cliente(est)
        est.intervalo = args.interval
        est.range = args.range
        return _cli_visao(c, est, args)
    except KeyboardInterrupt:
        print(cor("\n[interrumpido pelo usuário]", "amarelo"))
        return 130
    except ErroEndpoint as e:
        imprimir_erro(e)
        return 1
    except Exception as e:  # noqa: BLE001 — última barreira: app não morre
        imprimir_erro(e)
        return 1
    finally:
        if not args.no_pause and sys.stdin.isatty():
            try:
                input(cor("\nPressione ENTER para fechar...", "dim"))
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    sys.exit(main())
