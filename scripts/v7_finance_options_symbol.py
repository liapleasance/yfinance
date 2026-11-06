#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v7_finance_options_symbol.py — v1.0 · aplicativo interativo
============================================================
Implementação de referência EXECUTÁVEL do endpoint
GET /v7/finance/options/{symbol} (Yahoo Finance — a CADEIA DE OPÇÕES),
com interface de terminal em menu, paleta Bloomberg TrueColor, tabelas
completas no padrão da página oficial, retry automático e TODOS os modos
de leitura do endpoint expostos.

COMO USAR
    python v7_finance_options_symbol.py                       → menu interativo
    python v7_finance_options_symbol.py AAPL                  → cadeia canônica (date=-1)
    python v7_finance_options_symbol.py AAPL --venc 1793923200
    python v7_finance_options_symbol.py AAPL --straddle
    python v7_finance_options_symbol.py AAPL --strike 160     → todos os vencimentos
    python v7_finance_options_symbol.py AAPL --puts
    python v7_finance_options_symbol.py AAPL --combinada      → call|strike|put lado a lado
    python v7_finance_options_symbol.py AAPL --raw            → JSON bruto
    python v7_finance_options_symbol.py AAPL --json saida.json
    python v7_finance_options_symbol.py AAPL --no-format      → formatted=false (cru)
    python v7_finance_options_symbol.py --comparar AAPL,NVDA,SPY
    python v7_finance_options_symbol.py AAPL --verifica       → suíte de 24 checagens
    python v7_finance_options_symbol.py --auditar arquivo.json → auditoria offline
    python v7_finance_options_symbol.py --host query2 AAPL
    Flags: --sem-cores · --ascii · --no-pause

MODOS DE LEITURA DO ENDPOINT (todos expostos)
    1. Cadeia canônica  date=-1  → a PRIMEIRA EXPIRAÇÃO FUTURA (forma que o app
       oficial envia; -1 vai LITERAL no fio)
    2. Vencimento específico  date=<epoch s>  (lista de expirationDates)
    3. Strike único  strikeMin=strikeMax=<k> & getAllData=true & SEM date
       → UMA ENTRADA POR VENCIMENTO (todas as expirações) e o header strikes
       EXPANDE para a união de todas (76 → 130 em AAPL, 2026-11-06)
    4. Straddle  straddle=true  → calls/puts TROCAM por straddles[{strike, call, put}]
    5. formatted=false → números crus (sem invólucro {raw, fmt, longFmt})
    6. Cadeia integral  getAllData=true sem strike (date ausente ou -1) → UMA
       entrada por vencimento (via console de requisição bruta; ~1,78 MB em AAPL)

AUTENTICAÇÃO (bootstrap em 2 passos, par atômico)
    1) GET https://fc.yahoo.com            → 404 SEM redirect; o Set-Cookie A3 é o payload
    2) GET .../v1/test/getcrumb (A3 + UA + Referer finance.yahoo.com) → crumb casado
    UA de navegador é OBRIGATÓRIO (UA de biblioteca → 429 "Edge: Too Many Requests").
    O par renova JUNTO; 401 → renova e repete 1x; 429/503 → backoff exponencial.

CONTRATO (verificado ao vivo em 2026-11-05/06 — doc canônico:
    yh-finance-api/v7_finance_options/v7_finance_options.md)
    * Envelope de topo próprio {"optionChain":{"result":[...],"error":null}} — a
      camada finance SÓ aparece nos erros (401/400) — como no currencies.
    * result[0]: underlyingSymbol, expirationDates (epoch s, ordenado), strikes,
      hasMiniOptions, quote (pacote v7 do subjacente EMBUTIDO; 83–90 campos em
      ações, 61 no ^GSPC) e options[] — UMA entrada por expiração pedida
      (date/-1) ou UMA POR VENCIMENTO no modo strike.
    * Contrato: 15 campos lidos por NOME (a ordem no wire varia entre símbolos);
      formatted=true empacota em {raw, fmt, longFmt} — longFmt (milhar) em
      volume/openInterest e data+hora em lastTradeDate/expiration; inTheMoney é
      bool cru; IV em DECIMAL anualizado (1.0 = 100%); volume é OMITIDO quando
      não há negociação no dia — lastTradeDate pode permanecer de um trade anterior.
    * Erros: 401 "Invalid Crumb" (89 B) · 400 {"code":"Bad Request",
      "description":"Parameter=date has an invalid type"} (109 B — date não-numérico)
      · 400 do mesmo formato para strikeMin/strikeMax não-numéricos (114 B)
      · POST 405 · barra final → 404 TEXTO PURO · /options/ sem symbol → 404
      envelope finance · 429 Edge por UA.
    * Degradação grácil (200, nunca 5xx): símbolo inexistente → result: [] (42 B);
      deslistado (TWTR) → quote NONE + options[0] = {} vazio; sem cadeia pública
      (PETR4.SA, ^GSPC) → arrays vazios + quote completo; date sem contratos →
      entrada vazia ecoando o date pedido.
    * Cache de borda: GET 200 → public, max-age=1 + stale-while-revalidate=9
      (janela de ~10 s); HEAD → private, no-cache, no-store; 401 → max-age=0, private.

DEMONSTRATIVO DAS TABELAS (espelham a página oficial /quote/{symbol}/options)
    Contract Name · Last Trade Date (EST) · Strike · Last Price · Bid · Ask ·
    Change · % Change · Volume · Open Interest · Implied Volatility
    + extras locais: ITM/moneyness %, DTE (dias até o vencimento).

Autossuficiente: apenas stdlib (urllib + http.cookiejar + json).
Compatível com Python 3.8+. Interface em pt-BR.
"""
from __future__ import annotations

import argparse
import datetime
import http.cookiejar
import json
import math
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

ENDPOINT_NAME = "GET /v7/finance/options/{symbol}"
PATH_BASE = "/v7/finance/options"
HOSTS_EP = {
    "query1": "https://query1.finance.yahoo.com",
    "query2": "https://query2.finance.yahoo.com",
    "iquery": "https://iquery.finance.yahoo.com",
}
DEFAULT_HOST = "query1"
DEFAULT_TIMEOUT = 15.0
UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 15 campos canônicos do contrato (lidos POR NOME — a ordem no wire varia entre símbolos)
CAMPOS_CONTRATO = (
    "contractSymbol", "strike", "currency", "lastPrice", "change",
    "percentChange", "volume", "openInterest", "bid", "ask", "contractSize",
    "expiration", "lastTradeDate", "impliedVolatility", "inTheMoney",
)
# campos que podem trazer longFmt: milhar em volume/OI; data+hora em lastTradeDate/expiration
CAMPOS_LONGFMT = {"volume", "openInterest", "lastTradeDate", "expiration"}

CHAVES_RAIZ = {"underlyingSymbol", "expirationDates", "strikes",
               "hasMiniOptions", "quote", "options"}

# regex OCC: SYMBOL + YYMMDD + C/P + strike×1000 em 8 dígitos
RE_OCC = re.compile(r"^(?P<sym>.{1,6}?)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"
                    r"(?P<cp>[CP])(?P<strike>\d{8})$")

PRESETS_SUBJACENTES = [
    ("Apple Inc.", "AAPL"), ("NVIDIA Corporation", "NVDA"),
    ("Tesla, Inc.", "TSLA"), ("SPDR S&P 500 ETF Trust", "SPY"),
    ("Invesco QQQ Trust", "QQQ"), ("Amazon.com, Inc.", "AMZN"),
    ("Microsoft Corporation", "MSFT"), ("Petrobras PN (sem cadeia B3)", "PETR4.SA"),
    ("S&P 500 Index (sem cadeia pública)", "%5EGSPC"),
    ("Deslistado (classe NONE)", "TWTR"),
]

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
    """Ativa ANSI no Windows, UTF-8 no stdout/stderr e escolhe o modo gráfico."""
    global _CORES, _ASCII
    _CORES = cores
    _ASCII = ascii_
    if os.name == "nt":
        os.system("")  # ativa sequências ANSI no console moderno do Windows
        try:
            os.system("title Yahoo Finance - Options Chain")
        except Exception:
            pass
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cor(txt: Any, *estilos: str) -> str:
    """Pinta o texto; aceita nomes simétricos + RGB Bloomberg (TrueColor c/ fallback 256)."""
    if not _CORES or not estilos:
        return str(txt)
    # nomes básicos (compat. ANSI clássica)
    basicos = {"negrito": "\033[1m", "dim": "\033[2m",
               "vermelho": "\033[31m", "verde": "\033[32m", "amarelo": "\033[33m",
               "azul": "\033[34m", "magenta": "\033[35m", "ciano": "\033[36m",
               "branco": "\033[97m", "ambar": "\033[38;5;208m",
               "cinza": "\033[38;5;247m", "cinza_esc": "\033[38;5;244m"}
    rgb = {"ambar": (255, 160, 40), "verde": (0, 200, 83),
           "vermelho": (255, 67, 61), "ciano": (0, 212, 255),
           "amarelo": (255, 214, 0), "azul": (0, 104, 255),
           "teal": (74, 246, 195), "magenta": (255, 64, 255),
           "branco": (255, 255, 255), "cinza": (160, 160, 160),
           "cinza_esc": (128, 128, 128)}
    c256 = {"ambar": 208, "verde": 41, "vermelho": 203, "ciano": 45,
            "amarelo": 220, "azul": 33, "teal": 86, "magenta": 207,
            "branco": 231, "cinza": 247, "cinza_esc": 244}
    partes = []
    suporta_rgb = bool(os.environ.get("WT_SESSION")) or \
        "truecolor" in (os.environ.get("COLORTERM") or "").lower()
    for e in estilos:
        if e == "negrito" or e == "dim":
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
    """Caractere gráfico com fallback ASCII (modo --ascii)."""
    if _ASCII:
        return {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-",
                "v": "|", "blk": "#", "lt": ".", "meio": "*"}[nome]
    return {"tl": "╭", "tr": "╮", "bl": "╰", "br": "╯", "h": "─",
            "v": "│", "blk": "█", "lt": "░", "meio": "·"}[nome]


def _vis(s: str) -> str:
    """Comprimento visível (sem os códigos ANSI)."""
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
    """Devolve o bloco pronto (string multi-linha) para impressão."""
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
    """Tabela alinhada com régua; células podem conter cores (padding ignora ANSI)."""
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
    """Prompt com padrão; EOF/Ctrl+C duas vezes levantam SairLoop."""
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


def pedir_int(msg: str, lo: int, hi: int, default: int) -> int:
    while True:
        v = pedir(msg, str(default))
        try:
            n = int(str(v))
        except (TypeError, ValueError):
            n = lo - 1
        if lo <= n <= hi:
            return n
        print(cor(f"  digite um número entre {lo} e {hi}", "amarelo"))


def escolher(titulo: str, opcoes: List) -> int:
    """Menu numerado; devolve 1..n (0 = voltar/sair)."""
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
    if "401" in texto or "Invalid Crumb" in texto:
        print(cor("  dica: par A3+crumb inválido/expirado — Autenticação → Renovar o par", "amarelo"))
    elif "429" in texto or "Too Many" in texto:
        print(cor("  dica: rate limit da edge por assinatura de UA — aguarde alguns segundos", "amarelo"))
    elif "rede" in texto or "timed out" in texto:
        print(cor("  dica: verifique internet/DNS/proxy e o timeout (Configurações)", "amarelo"))
    elif "invalid type" in texto:
        print(cor("  dica: date só aceita epoch em SEGUNDOS (número) ou -1", "amarelo"))


def mascarar(segredo: Optional[str]) -> str:
    if not segredo:
        return "—"
    return f"{segredo[:2]}…({len(segredo)} chars)"


def banner() -> None:
    print("\n" + caixa([
        cor("  YAHOO FINANCE · OPTIONS CHAIN EXPLORER", "negrito", "branco"),
        cor("  GET /v7/finance/options/{symbol}", "ambar"),
        cor(f"  app de terminal · v{__version__} · stdlib pura · Python 3.8+", "dim"),
    ]))
    print(cor("  sem argumentos = menu; a janela só fecha no Sair "
              "(Ctrl+C duas vezes também sai)", "dim"))


def statuslinha(est: "Estado") -> None:
    if est.cliente is None:
        auth = cor("sessão não iniciada (inicializa na 1ª consulta)", "amarelo")
        nreq = 0
    else:
        auth = cor(f"crumb ativo {mascarar(est.cliente.crumb)}", "verde")
        nreq = est.cliente.requisicoes
    print(cor(f"  host {est.host} · lang {est.lang} · region {est.region} · "
              f"{auth} · requisições {nreq}", "dim"))


# ───────────────────── Formatação pt-BR (números, datas, barras) ─────────── #

def desempacotar(v: Any) -> Any:
    """{raw, fmt[, longFmt]} → valor cru; escalar passa direto."""
    if isinstance(v, dict) and "raw" in v:
        return v["raw"]
    return v


def fnum(n, dec: int = 0) -> str:
    """1234567.5 → '1.234.567,50'; None → '—' (padrão pt-BR)."""
    if n is None or not isinstance(n, (int, float)) or isinstance(n, bool):
        return "—"
    if isinstance(n, float) and n == int(n) and dec == 0:
        n = int(n)
    if isinstance(n, int) and dec == 0:
        return f"{n:,}".replace(",", ".")
    s = f"{n:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fdec(x, nd: int = 2) -> str:
    if x is None or not isinstance(x, (int, float)) or isinstance(x, bool):
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def fpct(x, nd: int = 2, sinal: bool = False) -> str:
    """Percentual já em unidades de %: 13.39 → '13,39%' (sinal=True → '+13,39%')."""
    if x is None or not isinstance(x, (int, float)) or isinstance(x, bool):
        return "—"
    s = f"{x:+.{nd}f}" if sinal else f"{x:.{nd}f}"
    return (s + "%").replace(".", ",")


def fiv(iv, nd: int = 2) -> str:
    """IV em fração anualizada → '37,50%' (o fio traz 0.375 = 37,5%)."""
    if iv is None or not isinstance(iv, (int, float)) or isinstance(iv, bool):
        return "—"
    return fpct(iv * 100, nd)


def _fuso_ny():
    """ZoneInfo America/New_York com fallback offset fixo -5 (Windows sem tzdata)."""
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        return ZoneInfo("America/New_York")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=-5))


def fdata(ts, com_hora: bool = False, ny: bool = False) -> str:
    """Epoch em SEGUNDOS → data humana; 0/None → '—'; ny=True → fuso da bolsa."""
    if ts is None:
        return "—"
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return str(ts)
    if ts <= 0:
        return "—"
    tz = _fuso_ny() if ny else datetime.timezone.utc
    try:
        dt = datetime.datetime.fromtimestamp(ts, tz)
        return dt.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")
    except (OverflowError, ValueError, OSError):
        return str(ts)


def dte(ts) -> str:
    """Dias até o vencimento (data local; vencido → '—')."""
    if ts is None:
        return "—"
    try:
        alvo = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return "—"
    dias = (alvo - datetime.datetime.now(datetime.timezone.utc).date()).days
    return str(max(dias, 0)) + (" (hoje)" if dias == 0 else "")


def barra(frac: float, larg: int = 20) -> str:
    frac = min(1.0, max(0.0, float(frac or 0.0)))
    cheio = round(frac * larg)
    return _cs("blk") * cheio + _cs("lt") * (larg - cheio)


def lado_cp(contract_symbol: str) -> str:
    """'C' ou 'P' — 9ª casa do símbolo OCC a partir do fim."""
    try:
        return "C" if contract_symbol[-9].upper() == "C" else "P"
    except IndexError:
        return "?"


def moneyness(spot, strike) -> str:
    """Moneyness do strike vs spot: '(+3,2%)' acima / '(−1,5%)' abaixo do spot."""
    if not isinstance(spot, (int, float)) or not spot or \
       not isinstance(strike, (int, float)) or not strike:
        return "—"
    p = (strike / spot - 1.0) * 100.0
    return f"{'+' if p >= 0 else '−'}{abs(p):.1f}%".replace(".", ",")


# ─────────────────────── Cliente — transporte do endpoint ────────────────── #

class ErroEndpoint(RuntimeError):
    """Erro com o status HTTP embutido (para as dicas da UI)."""

    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


class Cliente:
    """Bootstrap A3+crumb em 2 passos + requisições com retry.

    O crumb viaja como query param em GET (vetor do cliente oficial);
    o header x-crumb é o vetor alternativo (aceito pelo servidor).
    """

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT,
                 lang: str = "en-US", region: str = "US") -> None:
        self.base = HOSTS_EP[host]
        self.host_nome = host
        self.timeout = timeout
        self.lang = lang
        self.region = region
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [
            ("User-Agent", UA_BROWSER), ("Accept", "*/*"),
            ("Referer", "https://finance.yahoo.com/")]
        self.crumb: Optional[str] = None
        self.requisicoes = 0
        self.ultimo_resp: Optional[Resp] = None

    # ------------------------------------------------------------------ #
    def bootstrap(self, tentativas: int = 4, espera: float = 2.0,
                  silencioso: bool = False) -> str:
        """fc.yahoo.com (A3; 404 sem redirect é esperado) → getcrumb (UA+Referer)."""
        ultimo = ""
        for tent in range(tentativas):
            if not silencioso:
                print(cor(f"  [bootstrap] A3 (fc.yahoo.com) + crumb (getcrumb) — "
                          f"tentativa {tent + 1}/{tentativas}…", "dim"))
            try:
                self.opener.open("https://fc.yahoo.com", timeout=self.timeout)
            except urllib.error.HTTPError:
                pass  # 404 com Set-Cookie A3 — o cookie já está no jar
            except urllib.error.URLError as e:
                if not silencioso:
                    aviso(f"rede: {e.reason} — nova tentativa…")
                time.sleep(espera)
                continue
            try:
                r = self.opener.open(
                    "https://query1.finance.yahoo.com/v1/test/getcrumb",
                    timeout=self.timeout)
                corpo = r.read().decode("utf-8", "replace").strip()
            except urllib.error.HTTPError as e:
                corpo = e.read().decode("utf-8", "replace").strip() if e.fp else ""
            except urllib.error.URLError as e:
                if not silencioso:
                    aviso(f"rede: {e.reason} — nova tentativa…")
                time.sleep(espera)
                continue
            self.requisicoes += 2
            # crumb válido: token curto sem whitespace/HTML (o alfabeto VARIA entre
            # sessões — não exigir [A-Za-z0-9]; vi observado: 11 chars com hífen)
            if corpo and 6 <= len(corpo) <= 64 and "<" not in corpo \
                    and not re.search(r"\s", corpo):
                ultimo = corpo
                break
            time.sleep(espera)
        if not ultimo:
            raise ErroEndpoint(
                "bootstrap: getcrumb não devolveu um crumb válido "
                "(sessão bloqueada ou rate limit — aguarde alguns segundos)",
                429)
        self.crumb = ultimo
        return ultimo

    # ------------------------------------------------------------------ #
    def consultar(self, simbolo: str, params: Optional[Dict] = None,
                  metodo: str = "GET", headers: Optional[Dict] = None,
                  sem_crumb: bool = False) -> Resp:
        """Requisição crua → Resp(status, corpo, headers, ms, url)."""
        params = dict(params or {})
        if self.crumb and metodo == "GET" and not sem_crumb:
            params.setdefault("crumb", self.crumb)
        q = urllib.parse.urlencode(params)
        url = f"{self.base}{PATH_BASE}/{simbolo}" + (f"?{q}" if q else "")
        req = urllib.request.Request(url, method=metodo)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        t0 = time.perf_counter()
        self.requisicoes += 1
        try:
            r = self.opener.open(req, timeout=self.timeout)
            corpo = r.read().decode("utf-8", "replace")
            hdrs = {k.lower(): v for k, v in r.headers.items()}
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

    # ------------------------------------------------------------------ #
    def pedido(self, simbolo: str, params: Optional[Dict] = None,
               metodo: str = "GET", headers: Optional[Dict] = None,
               sem_crumb: bool = False) -> Resp:
        """Executa com retries: 401 → renova o par uma vez; 429/503 → backoff."""
        base_params = dict(params or {})
        r: Optional[Resp] = None
        for tentativa in range(5):
            r = self.consultar(simbolo, base_params, metodo, headers, sem_crumb)
            if r.status == 401 and tentativa == 0:
                aviso("401 Invalid Crumb — renovando o par A3+crumb…")
                self.crumb = None
                self.bootstrap(silencioso=True)
                continue
            if r.status in (429, 503) and tentativa < 4:
                espera = 2 ** tentativa + random.uniform(0.1, 0.5)
                aviso(f"HTTP {r.status} — backoff de {espera:.1f}s ({tentativa + 1}/5)…")
                time.sleep(espera)
                continue
            return r
        return r  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse(r: Resp) -> dict:
        """Interpreta a resposta com os envelopes ESPECÍFICOS deste endpoint."""
        corpo = r.corpo
        if r.status == 200 and not corpo.strip().startswith("{"):
            # barra final devolve 'Not Found' em texto puro com 404; aqui é salvaguarda
            raise ErroEndpoint(f"HTTP {r.status}: corpo não-JSON {corpo[:120]!r}", r.status)
        try:
            j = json.loads(corpo)
        except ValueError as e:
            raise ErroEndpoint(f"HTTP {r.status}: corpo não-JSON {corpo[:120]!r}", r.status) from e
        if r.status != 200:
            fin = j.get("finance") or {} if isinstance(j, dict) else {}
            err = fin.get("error") or {}
            code = err.get("code") or "?"
            desc = err.get("description") or corpo[:100]
            raise ErroEndpoint(f"HTTP {r.status} {code}: {desc}", r.status)
        if "optionChain" in j:
            return j
        if "finance" in j:  # resposta inesperada com camada finance no sucesso
            raise ErroEndpoint(f"envelope inesperado (finance no 200): chaves {sorted(j)}", 200)
        raise ErroEndpoint(f"envelope inesperado: chaves {sorted(j)}", 200)

    # ------------------------------------------------------------------ #
    def cadeia(self, simbolo: str, date: str = "-1", formatted: bool = True,
               straddle: bool = False, strike: Optional[float] = None,
               raw_params: Optional[Dict] = None) -> dict:
        """Consulta canônica + interpretada. Modos:
        date='-1' (primeira futura) | date=<epoch s> | strike=<k> (todos os
        vencimentos: strikeMin=Max + getAllData=true, SEM date)."""
        params: Dict[str, str] = {
            "formatted": "true" if formatted else "false",
            "straddle": "true" if straddle else "false",
            "lang": self.lang, "region": self.region,
        }
        if strike is not None:
            params["strikeMin"] = _fmt_num_param(strike)
            params["strikeMax"] = _fmt_num_param(strike)
            params["getAllData"] = "true"          # SEM date — o cliente oficial deleta
        else:
            params["date"] = str(date)
        params.update({k: str(v) for k, v in (raw_params or {}).items()})
        r = self.pedido(urllib.parse.quote(simbolo), params)
        return self._parse(r)

    # ------------------------------------------------------------------ #
    def info_auth(self) -> dict:
        return {
            "host": self.host_nome, "base": self.base,
            "crumb_mascarado": mascarar(self.crumb),
            "cookies": [c.name for c in self.jar],
            "a3": any(c.name == "A3" for c in self.jar),
            "requisicoes": self.requisicoes,
        }


def _fmt_num_param(k: float) -> str:
    """160.0 → '160' · 187.5 → '187.5' · NaN/Infinity preservados (o servidor os aceita)."""
    k = float(k)
    if math.isnan(k):
        return "NaN"
    if math.isinf(k):
        return "Infinity" if k > 0 else "-Infinity"
    return str(int(k)) if k == int(k) else str(k)


# ───────────────────── Interpretação da cadeia (modelos locais) ──────────── #

def _result0(payload: dict) -> dict:
    res = (payload.get("optionChain") or {}).get("result") or []
    if not res:
        raise ErroEndpoint(
            "optionChain.result vazio — símbolo inexistente ou sem dados "
            "(o endpoint devolve 200 com result: [] em vez de erro)", 200)
    return res[0]


class Cadeia:
    """Visão normalizada (valores crus desempacotados) da cadeia de um símbolo."""

    def __init__(self, payload: dict):
        r0 = _result0(payload)
        self.r0 = r0
        self.simbolo = r0.get("underlyingSymbol", "?")
        self.expiracoes: List[int] = list(r0.get("expirationDates") or [])
        self.strikes: List[float] = list(r0.get("strikes") or [])
        self.has_mini = bool(r0.get("hasMiniOptions"))
        self.quote: Dict[str, Any] = r0.get("quote") or {}
        self.spot = desempacotar(self.quote.get("regularMarketPrice"))
        self.market_state = self.quote.get("marketState", "—")
        self.moeda = self.quote.get("currency", "—")
        self.blocos: List[Dict] = list(r0.get("options") or [])
        self.vencimento: Optional[int] = (self.blocos[0] or {}).get("expirationDate") \
            if self.blocos else None
        self.straddle_view = bool(self.blocos and self.blocos[0] and
                                  "straddles" in (self.blocos[0] or {}))

    # ------------------------------------------------------------------ #
    def contratos(self, lado: str = "calls", bloco: int = 0) -> List[Dict]:
        """Contratos crus do bloco (lado='calls'|'puts'); [] se ausente."""
        if not self.blocos:
            return []
        b = self.blocos[min(bloco, len(self.blocos) - 1)] or {}
        return list(b.get(lado) or [])

    # ------------------------------------------------------------------ #
    def resumo_lados(self, lado: str = "calls", bloco: int = 0) -> Dict:
        """Agregados locais de um lado: volume, OI, ITM, máx IV — computados AQUI
        (o endpoint da cadeia não traz summaries; o analytics é o irmão)."""
        cs = self.contratos(lado, bloco)
        vol = sum(desempacotar(c.get("volume")) or 0 for c in cs)
        oi = sum(desempacotar(c.get("openInterest")) or 0 for c in cs)
        itm = sum(1 for c in cs if c.get("inTheMoney"))
        ivs = [desempacotar(c.get("impliedVolatility")) for c in cs
               if isinstance(desempacotar(c.get("impliedVolatility")), (int, float))]
        return {"n": len(cs), "volume": vol, "oi": oi, "itm": itm,
                "iv_media": (sum(ivs) / len(ivs)) if ivs else None}

    # ------------------------------------------------------------------ #
    def strike_mais_proximo(self) -> Optional[float]:
        if not self.strikes or not isinstance(self.spot, (int, float)) or not self.spot:
            return None
        return min(self.strikes, key=lambda k: abs(k - self.spot))


# ─────────────────────────── Exibição — visões da cadeia ─────────────────── #

def _col_contract(c: Dict, spot=None) -> Tuple[str, str, str, str, str, str, str, str, str, str, str, str]:
    """12 colunas da grade no padrão da página oficial (+ moneyness no ITM)."""
    occ = c.get("contractSymbol", "—")
    trade = c.get("lastTradeDate")
    trade_str = (fdata(desempacotar(trade), com_hora=True, ny=True)
                 if trade is not None else "—")
    strike = desempacotar(c.get("strike"))
    last = desempacotar(c.get("lastPrice"))
    bid = desempacotar(c.get("bid"))
    ask = desempacotar(c.get("ask"))
    chg = desempacotar(c.get("change"))
    pct = desempacotar(c.get("percentChange"))
    vol = desempacotar(c.get("volume"))
    oi = desempacotar(c.get("openInterest"))
    iv = desempacotar(c.get("impliedVolatility"))
    itm = bool(c.get("inTheMoney"))
    return (
        occ,
        trade_str,
        fdec(strike),
        fdec(last),
        fdec(bid),
        fdec(ask),
        fdec(chg),
        cor(fpct(pct, 2, sinal=True), "verde" if (pct or 0) > 0
            else ("vermelho" if (pct or 0) < 0 else "branco")),
        fnum(vol),
        fnum(oi),
        cor(fiv(iv), "amarelo"),
        (cor("SIM " + moneyness(spot, strike), "verde", "negrito")
         if itm else cor("não", "cinza_esc")),
    )


def exibir_grade(cadeia: Cadeia, lado: str, titulo: str) -> None:
    """A TABELA DETALHADA completa — TODOS os contratos negociados do bloco,
    com as 11 colunas da página oficial + moneyness."""
    cs = cadeia.contratos(lado)
    if not cs:
        aviso(f"nenhum contrato nesta perna ({lado}) — ativo sem cadeia ou "
              "expiração sem contratos")
        return
    print()
    print(cor(f" {titulo}", "negrito", "branco"))
    print(cor(f"  {len(cs)} contratos · vencimento "
              f"{fdata(cadeia.vencimento)} ({dte(cadeia.vencimento)}) · "
              f"spot {fdec(cadeia.spot)} · {cadeia.market_state} · {cadeia.moeda}",
              "dim"))
    headers = ["CONTRATO", "ÚLT. NEGÓCIO (NY)", "STRIKE", "ÚLTIMO", "BID",
               "ASK", "VAR", "%VAR", "VOL", "OPEN INT", "IV", "ITM"]
    aligns = ["<", ">", ">", ">", ">", ">", ">", ">", ">", ">", ">", "<"]
    rows = [_col_contract(c, cadeia.spot) for c in cs]
    imprimir_tabela(headers, rows, aligns)
    print(cor("  unidades: IV em % anualizada (fio em fração) · VOL/OI com milhar pt-BR · "
              "— = volume OMITIDO (sem negociação no dia; lastTradeDate pode permanecer) · "
              "ITM mostra moneyness vs spot", "dim"))


def exibir_combinada(cadeia: Cadeia) -> None:
    """CALLS e PUTS lado a lado por strike (visão 'options chain' clássica)."""
    calls = {desempacotar(c.get("strike")): c for c in cadeia.contratos("calls")}
    puts = {desempacotar(c.get("strike")): c for c in cadeia.contratos("puts")}
    strikes = sorted(set(calls) | set(puts))
    if not strikes:
        aviso("sem contratos neste vencimento")
        return
    print()
    print(cor(f" CADEIA COMBINADA — {cadeia.simbolo} · vencimento "
              f"{fdata(cadeia.vencimento)} ({dte(cadeia.vencimento)})",
              "negrito", "branco"))
    print(cor("  CALL (verde) | STRIKE | PUT (magenta) · ITM marcado · "
              "spot " + fdec(cadeia.spot), "dim"))
    headers = ["ÚLT", "VOL", "IV", "BID/ASK", "STRIKE", "BID/ASK", "IV", "VOL", "ÚLT", "ITM"]
    aligns = [">", ">", ">", "^", "^", "^", "<", "<", "<", "^"]
    rows = []
    prox = cadeia.strike_mais_proximo()
    for k in strikes:
        c = calls.get(k) or {}
        p = puts.get(k) or {}
        cl = desempacotar(c.get("lastPrice"))
        pl = desempacotar(p.get("lastPrice"))
        cba = f"{fdec(desempacotar(c.get('bid')))} / {fdec(desempacotar(c.get('ask')))}" if c else "—"
        pba = f"{fdec(desempacotar(p.get('bid')))} / {fdec(desempacotar(p.get('ask')))}" if p else "—"
        marca = cor("◄ ATM", "ambar", "negrito") if k == prox else \
            ("C" if k < (cadeia.spot or 0) else "P") if cadeia.spot else ""
        rows.append([
            cor(fdec(cl), "verde") if c else "—",
            fnum(desempacotar(c.get("volume"))) if c else "—",
            cor(fiv(desempacotar(c.get("impliedVolatility"))), "amarelo") if c else "—",
            cba,
            cor(fdec(k), "ambar", "negrito") + (f" {marca}" if marca else ""),
            pba,
            cor(fiv(desempacotar(p.get("impliedVolatility"))), "amarelo") if p else "—",
            fnum(desempacotar(p.get("volume"))) if p else "—",
            cor(fdec(pl), "magenta") if p else "—",
            cor("ITM", "verde") if (p and p.get("inTheMoney")) or (c and c.get("inTheMoney"))
            else cor("—", "cinza_esc"),
        ])
    imprimir_tabela(headers, rows, aligns)
    print(cor("  ITM marca a perna dentro do dinheiro (call ITM: strike < spot · "
              "put ITM: strike > spot)", "dim"))


def exibir_straddle(cadeia: Cadeia) -> None:
    """Visão straddle=true do fio: straddles[{strike, call, put}] — o strike
    vem FORA das pernas (diferente de um zip de calls/puts)."""
    if not cadeia.straddle_view:
        aviso("esta consulta não veio em modo straddle — refaça com straddle=true "
              "(menu de visões ou --straddle)")
        return
    st = cadeia.blocos[0].get("straddles") or []
    if not st:
        aviso("straddles vazio neste vencimento")
        return
    print()
    print(cor(f" STRADDLES — {cadeia.simbolo} · vencimento {fdata(cadeia.vencimento)} "
              f"({dte(cadeia.vencimento)}) · {len(st)} pares", "negrito", "branco"))
    headers = ["STRIKE", "CALL ÚLT", "CALL IV", "CALL B/A", "PUT ÚLT", "PUT IV",
               "PUT B/A", "SOMA ÚLT"]
    aligns = ["^", ">", ">", "^", "<", "<", "<", ">"]
    rows = []
    for s in st:
        k = desempacotar(s.get("strike"))
        c = s.get("call") or {}
        p = s.get("put") or {}
        cl = desempacotar(c.get("lastPrice"))
        pl = desempacotar(p.get("lastPrice"))
        soma = (cl + pl) if isinstance(cl, (int, float)) and isinstance(pl, (int, float)) else None
        rows.append([
            cor(fdec(k), "ambar", "negrito"),
            fdec(cl) if c else "—",
            cor(fiv(desempacotar(c.get("impliedVolatility"))), "amarelo") if c else "—",
            f"{fdec(desempacotar(c.get('bid')))} / {fdec(desempacotar(c.get('ask')))}" if c else "—",
            cor(fdec(pl), "magenta") if p else "—",
            cor(fiv(desempacotar(p.get("impliedVolatility"))), "amarelo") if p else "—",
            f"{fdec(desempacotar(p.get('bid')))} / {fdec(desempacotar(p.get('ask')))}" if p else "—",
            fdec(soma),
        ])
    imprimir_tabela(headers, rows, aligns)
    print(cor("  SOMA ÚLT = débito do straddle comprado (call + put do mesmo strike/vencimento)", "dim"))


def exibir_strike_todos_vencimentos(cadeia: Cadeia, strike: float, payload: dict) -> None:
    """Modo strike único: UMA ENTRADA POR VENCIMENTO — tabela temporal do strike."""
    r0 = _result0(payload)
    blocos = r0.get("options") or []
    if not blocos:
        aviso("sem entradas de vencimento nesta resposta")
        return
    print()
    print(cor(f" STRIKE {fdec(strike)} EM TODOS OS VENCIMENTOS — {cadeia.simbolo} "
              f"({len(blocos)} vencimentos)", "negrito", "branco"))
    print(cor(f"  header strikes EXPANDIDO: {len(r0.get('strikes') or [])} valores "
              f"(união de todas as expirações)", "dim"))
    headers = ["VENCIMENTO", "DTE", "CALL ÚLT", "CALL IV", "CALL VOL", "CALL OI",
               "PUT ÚLT", "PUT IV", "PUT VOL", "PUT OI"]
    aligns = ["<", ">", ">", ">", ">", ">", ">", ">", ">", ">"]
    rows = []
    for b in blocos:
        b = b or {}
        exp = b.get("expirationDate")
        c = (b.get("calls") or [{}])[0] if b.get("calls") else {}
        p = (b.get("puts") or [{}])[0] if b.get("puts") else {}
        if not c and not p and b.get("straddles"):
            s0 = b["straddles"][0] or {}
            c = s0.get("call") or {}
            p = s0.get("put") or {}
        rows.append([
            fdata(exp),
            dte(exp),
            fdec(desempacotar(c.get("lastPrice"))) if c else cor("sem", "cinza_esc"),
            cor(fiv(desempacotar(c.get("impliedVolatility"))), "amarelo") if c else "—",
            fnum(desempacotar(c.get("volume"))) if c else "—",
            fnum(desempacotar(c.get("openInterest"))) if c else "—",
            cor(fdec(desempacotar(p.get("lastPrice"))), "magenta") if p else cor("sem", "cinza_esc"),
            cor(fiv(desempacotar(p.get("impliedVolatility"))), "amarelo") if p else "—",
            fnum(desempacotar(p.get("volume"))) if p else "—",
            fnum(desempacotar(p.get("openInterest"))) if p else "—",
        ])
    imprimir_tabela(headers, rows, aligns)
    print(cor("  'sem' = o vencimento não lista esse strike (nem toda malha o tem)", "dim"))


def exibir_resumo(cadeia: Cadeia) -> None:
    """Resumo analítico: subjacente + agregados locais de volume/OI/ITM por lado."""
    rc = cadeia.resumo_lados("calls")
    rp = cadeia.resumo_lados("puts")
    tot_vol = rc["volume"] + rp["volume"]
    tot_oi = rc["oi"] + rp["oi"]
    pc_vol = (rp["volume"] / rc["volume"]) if rc["volume"] else None
    pc_oi = (rp["oi"] / rc["oi"]) if rc["oi"] else None
    q = cadeia.quote
    linhas = [
        cor(f"{cadeia.simbolo} — cadeia do vencimento {fdata(cadeia.vencimento)} "
            f"({dte(cadeia.vencimento)})", "negrito", "branco"),
        f"spot {fdec(cadeia.spot)} ({cadeia.market_state}) · moeda {cadeia.moeda} · "
        f"{len(cadeia.expiracoes)} vencimentos · {len(cadeia.strikes)} strikes"
        + (cor(" · hasMiniOptions", "teal") if cadeia.has_mini else ""),
        f"nome {q.get('shortName') or q.get('longName') or '—'} · "
        f"52s {q.get('fiftyTwoWeekRange', '—')} · "
        f"P/L {fdec(q.get('trailingPE'))} · DY {fdec(q.get('dividendYield'))}",
        "",
        "VOLUME (vencimento ativo)  " + cor("computado localmente do bloco", "dim"),
        f"  CALLS {fnum(rc['volume']):>12}  {cor(barra(rc['volume'] / tot_vol if tot_vol else 0), 'verde')}"
        f"  {fpct((rc['volume'] / tot_vol * 100) if tot_vol else 0, 1):>7}",
        f"  PUTS  {fnum(rp['volume']):>12}  {cor(barra(rp['volume'] / tot_vol if tot_vol else 0), 'magenta')}"
        f"  {fpct((rp['volume'] / tot_vol * 100) if tot_vol else 0, 1):>7}",
        f"  TOTAL {fnum(tot_vol):>12}   razão P/C {fdec(pc_vol)}"
        + (cor("  (≥1 = pressão vendedora)", "dim") if pc_vol is not None else ""),
        "",
        "INTERESSE ABERTO (vencimento ativo)",
        f"  CALLS {fnum(rc['oi']):>12}  {cor(barra(rc['oi'] / tot_oi if tot_oi else 0), 'verde')}"
        f"  ITM {rc['itm']}/{rc['n']}",
        f"  PUTS  {fnum(rp['oi']):>12}  {cor(barra(rp['oi'] / tot_oi if tot_oi else 0), 'magenta')}"
        f"  ITM {rp['itm']}/{rp['n']}",
        f"  TOTAL {fnum(tot_oi):>12}   razão P/C {fdec(pc_oi)}",
        "",
        f"IV média do vencimento: calls {fiv(rc['iv_media'])} · puts {fiv(rp['iv_media'])}"
        + (f" · ATM mais próximo: {fdec(cadeia.strike_mais_proximo())}"
           if cadeia.strike_mais_proximo() is not None else ""),
    ]
    print("\n" + caixa(linhas))


def exibir_vencimentos(cadeia: Cadeia) -> None:
    print()
    print(cor(f" VENCIMENTOS DISPONÍVEIS — {cadeia.simbolo} "
              f"({len(cadeia.expiracoes)} datas)", "negrito", "branco"))
    rows = []
    for i, ep in enumerate(cadeia.expiracoes, 1):
        marca = cor("  ◄ ativo", "ambar") if ep == cadeia.vencimento else ""
        rows.append([f"{i:>2}", fdata(ep), f"{ep}", dte(ep),
                     "sex" if datetime.datetime.fromtimestamp(ep, datetime.timezone.utc)
                     .weekday() == 4 else "—", marca.strip()])
    imprimir_tabela(["#", "DATA", "EPOCH (s)", "DTE", "DIA", ""], rows,
                    [">", "<", ">", ">", "^", "<"])
    print(cor("  o epoch da coluna EPOCH vai direto no date= (cópia pronta)", "dim"))


def exibir_subjacente(cadeia: Cadeia) -> None:
    q = cadeia.quote
    linhas = [
        f"• Ticker : {q.get('symbol', '—')} ({q.get('shortName') or q.get('longName') or '—'})"
        + (f" · display {q.get('displayName')}" if q.get('displayName') else ""),
        f"• Preço  : {fdec(q.get('regularMarketPrice'))} {q.get('currency', '—')} "
        f"({q.get('marketState', '—')}) · fonte {q.get('quoteSourceName', '—')}",
        f"• Dia    : {fdec(q.get('regularMarketChange'))} "
        f"({fpct(q.get('regularMarketChangePercent'), 2, sinal=True)}) · "
        f"abertura {fdec(q.get('regularMarketOpen'))} · "
        f"faixa {fdec(q.get('regularMarketDayLow'))}–{fdec(q.get('regularMarketDayHigh'))}",
        f"• 52 sem : {q.get('fiftyTwoWeekRange', '—')} · "
        f"volume {fnum(q.get('regularMarketVolume'))} "
        f"(méd 3m {fnum(q.get('averageDailyVolume3Month'))})",
        f"• Múltiplos: P/L {fdec(q.get('trailingPE'))} · forward {fdec(q.get('forwardPE'))} · "
        f"P/VP {fdec(q.get('priceToBook'))}",
        f"• Bolsa  : {q.get('fullExchangeName', '—')} ({q.get('exchange', '—')}) · "
        f"fuso {q.get('exchangeTimezoneName', '—')}",
        f"• Cadeia : {len(cadeia.expiracoes)} vencimentos · {len(cadeia.strikes)} strikes "
        f"· hasMiniOptions {cadeia.has_mini}",
    ]
    print("\n" + caixa(linhas, titulo=f"SUBJACENTE — {cadeia.simbolo}"))


def exibir_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _mostrar_requisicao(c: Cliente) -> None:
    r = c.ultimo_resp
    if r is None:
        return
    url = r.url.replace(c.crumb, "…") if c.crumb else r.url
    print(cor(f"  {url} · HTTP {r.status} · {len(r.corpo)} bytes · {r.ms:.0f} ms", "dim"))


# ────────────── Visão "Avenue" — ladder de cartões + payoff ──────────────── #
# Replica o layout da página de opções do Avenue (pit.avenue.us/options/{symbol}):
# header do ativo, frase editorial, faixa do spot cravada no ladder de strikes,
# cartões Strike/Breakeven/Prêmio, separador ITM e o gráfico de payoff por contrato.

MESES_PT = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio",
            6: "junho", 7: "julho", 8: "agosto", 9: "setembro", 10: "outubro",
            11: "novembro", 12: "dezembro"}


def fdata_extenso(ts) -> str:
    """Epoch s → '20 de novembro de 2026' (pt-BR, como a página oficial)."""
    try:
        d = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date()
        return f"{d.day} de {MESES_PT[d.month]} de {d.year}"
    except (TypeError, ValueError, OverflowError, OSError):
        return "—"


def fvol_compacto(n) -> str:
    """40662410 → '40,7M' · 1250 → '1,3k' · 870 → '870' (padrão da página)."""
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return "—"
    n = float(n)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= div:
            return fdec(n / div, 1) + suf
    return fnum(int(n))


def fechamento_brt(ts) -> str:
    """'18h'/'17h' — fechamento 16:00 ET convertido para BRT conforme o DST americano."""
    try:
        d = datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).date()
        p1 = datetime.date(d.year, 3, 1)
        ini = p1 + datetime.timedelta(days=(6 - p1.weekday()) % 7 + 7)
        p11 = datetime.date(d.year, 11, 1)
        fim = p11 + datetime.timedelta(days=(6 - p11.weekday()) % 7)
        return "17h" if ini <= d < fim else "18h"
    except (TypeError, ValueError, OverflowError, OSError):
        return "16h (ET)"


def _breakeven(lado: str, strike, premio):
    k, p = desempacotar(strike), desempacotar(premio)
    if not isinstance(k, (int, float)) or not isinstance(p, (int, float)):
        return None
    return k + p if lado == "calls" else k - p


def _premio_efetivo(c: Dict) -> Any:
    """lastPrice; sem negociação, o meio de bid/ask (o que a página exibe)."""
    p = desempacotar(c.get("lastPrice"))
    if isinstance(p, (int, float)):
        return p
    b, a = desempacotar(c.get("bid")), desempacotar(c.get("ask"))
    if isinstance(b, (int, float)) and isinstance(a, (int, float)) and a + b > 0:
        return (b + a) / 2.0
    return None


def _cartao_avenue(lado: str, c: Dict) -> None:
    """Cartão do ladder: Strike + Breakeven à esquerda, Prêmio e Compra (ask) à direita."""
    k = desempacotar(c.get("strike"))
    prem = _premio_efetivo(c)
    be = _breakeven(lado, k, prem)
    ask = desempacotar(c.get("ask"))
    w = 58
    esq1 = f"$ {fdec(k)} Strike"
    dir1 = f"Prêmio: $ {fdec(prem)}" if prem is not None else "Prêmio: —"
    lin1 = " " + esq1 + " " * max(1, w - _vis(esq1) - _vis(dir1) - 1) + dir1 + " "
    be_txt = f"Breakeven: $ {fdec(be)}" if be is not None else "Breakeven: —"
    cmp_txt = f"Compra (ask): $ {fdec(ask)}" if ask is not None else "Compra: —"
    lin2 = " " + be_txt + " " * max(1, w - _vis(be_txt) - _vis(cmp_txt) - 1) + cmp_txt + " "
    print(_cs("tl") + _cs("h") * (w + 2) + _cs("tr"))
    print(_cs("v") + _pad(lin1, w + 2) + _cs("v"))
    print(_cs("v") + _pad(lin2, w + 2) + _cs("v"))
    print(_cs("bl") + _cs("h") * (w + 2) + _cs("br"))


def _faixa_spot(cadeia: Cadeia) -> None:
    """Faixa de posição: '{symbol} está a US$ {spot} ({pct})' — vermelho/verde."""
    q = cadeia.quote
    pct = q.get("regularMarketChangePercent")
    sinal = "−" if isinstance(pct, (int, float)) and pct < 0 else "+"
    pct_txt = (sinal + f"{abs(pct):.2f}".replace(".", ",")) if isinstance(pct, (int, float)) else "—"
    crotxt = "vermelho" if isinstance(pct, (int, float)) and pct < 0 else "verde"
    hora = datetime.datetime.fromtimestamp(q.get("regularMarketTime") or time.time()) \
        .strftime("%H:%M")
    txt = cor(f"▼ {cadeia.simbolo} está a US$ {fdec(cadeia.spot)} ({pct_txt}%)", crotxt, "negrito")
    print(txt + cor(f"   · atualização {hora}", "dim"))


def exibir_avenue(cadeia: Cadeia, lado: str = "calls") -> None:
    """O ladder da página oficial: header do ativo, frase editorial, faixa do spot
    cravada na posição correta, cartões Strike/Breakeven/Prêmio e separador ITM."""
    perna = "CALL" if lado == "calls" else "PUT"
    verbo = "subir" if lado == "calls" else "cair"
    q = cadeia.quote
    spot = cadeia.spot
    hora = datetime.datetime.fromtimestamp(q.get("regularMarketTime") or time.time()) \
        .strftime("%H:%M")
    estado = q.get("marketState", "—")
    aberto = estado in ("PRE", "REGULAR", "POST", "POSTPOST")
    print()
    fonte = q.get("quoteSourceName") or "—"
    atrasada = "delayed" in str(fonte).lower()
    fonte_txt = cor(f"· fonte: {fonte}" + (" (cotação atrasada — a página oficial exibe aviso)" if atrasada else ""),
                    "amarelo" if atrasada else "dim")
    print(cor(f" {cadeia.simbolo}", "negrito", "branco")
          + f"   Cotação US$ {fdec(spot)}   Máximo US$ {fdec(q.get('regularMarketDayHigh'))}"
          + f"   Mínimo US$ {fdec(q.get('regularMarketDayLow'))}"
          + f"   Volume {fvol_compacto(q.get('regularMarketVolume'))}"
          + cor(f"   · última atualização às {hora}", "dim")
          + "  " + fonte_txt)
    verbc = "verde" if lado == "calls" else "magenta"
    print()
    print(cor("Acredito que ", "negrito") + cor(cadeia.simbolo, "negrito", "branco")
          + cor(" vai ", "negrito") + cor(verbo, "negrito", verbc)
          + cor(" até dia ", "negrito")
          + cor(fdata_extenso(cadeia.vencimento), "negrito", "ciano")
          + cor(".", "negrito"))
    print()
    print(cor(f" [ {perna} ]", "negrito", verbc)
          + cor("  (troque a perna no menu)", "dim")
          + f"   Ver opções que expiram em: "
          + cor(fdata_extenso(cadeia.vencimento), "negrito")
          + cor(f"   · {'Mercado aberto até às ' + fechamento_brt(q.get('regularMarketTime')) if aberto else 'Mercado fechado (' + str(estado) + ')'}",
                "verde" if aberto else "amarelo"))
    cs = cadeia.contratos(lado)
    if not cs:
        aviso(f"nenhum contrato nesta perna ({perna}) — ativo sem cadeia")
        return

    def strike_of(c):
        return desempacotar(c.get("strike")) or 0.0

    ordenados = sorted(cs, key=strike_of, reverse=True)
    spot_v = spot if isinstance(spot, (int, float)) and not isinstance(spot, bool) else None
    faixa_feita = False
    itm_feito = False
    for c in ordenados:
        k = strike_of(c)
        if not faixa_feita and spot_v is not None and k < spot_v:
            print()
            _faixa_spot(cadeia)
            if not itm_feito:
                print()
                print(cor("▼ In the money (ITM)", "negrito", "dim"))
                print(cor(_cs("h") * min(largura_tela(), 96), "dim"))
                print()
                itm_feito = True
            faixa_feita = True
        _cartao_avenue(lado, c)
    if not faixa_feita and spot_v is not None:
        print()
        _faixa_spot(cadeia)


def _payoff_fn(lado: str, strike: float, premio: float):
    """Payoff do COMPRADOR por contrato (100 ações) na expiração."""
    if lado == "calls":
        return lambda s: 100.0 * (max(s - strike, 0.0) - premio)
    return lambda s: 100.0 * (max(strike - s, 0.0) - premio)


def grafico_payoff_ascii(lado: str, strike: float, premio: float, spot,
                         larg: int = 58, alt: int = 12) -> str:
    """Gráfico de payoff ASCII estilo Avenue: quebra no strike, cruzamento no
    breakeven, marcas verticais e eixo Y por contrato (100 ações)."""
    be = _breakeven(lado, strike, premio) or strike
    fn = _payoff_fn(lado, strike, premio)
    refs = [v for v in (spot, strike, be) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    xmin = max(min(refs or [strike]) * 0.9, 0.01)
    xmax = max(refs or [strike]) * 1.35
    col = lambda x: round((x - xmin) / (xmax - xmin) * (larg - 1)) if xmax > xmin else 0
    ymin = -premio * 100.0
    # teto visual ~5× a perda máxima (a diagonal é CLIPADA no topo — como o
    # Chart.js da página oficial; sem isso o ganho máximo domina a escala e a
    # perda colapsa na linha do zero)
    perda = abs(ymin) or 100.0
    ymax = max(perda * 5.0, 1.0)
    lin = lambda y: alt - 1 - round((y - ymin) / (ymax - ymin) * (alt - 1))
    grid = [[" "] * larg for _ in range(alt)]
    for cx in range(larg):
        x = xmin + (xmax - xmin) * cx / (larg - 1)
        ly = lin(fn(x))
        if 0 <= ly < alt:
            grid[ly][cx] = "●"
    cK, cB = col(strike), col(be)
    cS = col(spot) if isinstance(spot, (int, float)) and not isinstance(spot, bool) else -1
    zl = lin(0.0)
    for cy in range(alt):
        if 0 <= cK < larg and grid[cy][cK] == " ":
            grid[cy][cK] = "┊"
        if 0 <= cB < larg and grid[cy][cB] == " ":
            grid[cy][cB] = "┊"
    if 0 <= zl < alt:
        for cx in range(larg):
            if grid[zl][cx] == " ":
                grid[zl][cx] = "·"
    linhas = []
    ltop = ("+" if ymax > 0 else "") + fnum(ymax, 0)
    lzero = "0,00"
    lbot = ("−" if ymin < 0 else "") + fnum(abs(ymin), 0)
    lmax_w = max(len(ltop), len(lzero), len(lbot)) + 1
    for cy in range(alt):
        rot = (ltop if cy == 0 else (lzero if cy == zl else (lbot if cy == alt - 1 else "")))
        linhas.append(f"{_pad(rot, lmax_w, '>')} ┤ " + "".join(grid[cy]))
    linhas.append(" " * lmax_w + " └" + _cs("h") * larg + "→ preço do ativo")
    # rótulos em faixas (evita sobreposição quando breakeven/spot/strike são adjacentes)
    rotulos = [(t, cc) for t, cc in ((f"Breakeven $ {fdec(be)}", cB),
                                     (f"spot $ {fdec(spot)}", cS),
                                     (f"Strike $ {fdec(strike)}", cK))
               if cc is not None and 0 <= cc < larg]
    rotulos.sort(key=lambda p: p[1])
    faixas: List[List[str]] = []
    for txt, cc in rotulos:
        for faixa in faixas:
            fim_ult = faixa[1] + len(faixa[0])
            if cc >= fim_ult + 2:
                faixa[0], faixa[1] = txt, cc
                break
        else:
            faixas.append([txt, cc])
    for fi, faixa in enumerate(faixas[:3]):
        linha_rot = [" "] * (lmax_w + 3 + larg)
        txt, cc = faixa
        ini = max(0, min(lmax_w + 2 + cc - len(txt) // 2, len(linha_rot) - len(txt)))
        for i2, ch in enumerate(txt):
            linha_rot[ini + i2] = ch
        linhas.append("".join(linha_rot).rstrip())
    linhas.append(cor("  por contrato (100 ações) · ┊ strike/breakeven/spot · ● payoff na expiração", "dim"))
    return "\n".join(linhas)


def exibir_detalhe_avenue(cadeia: Cadeia, lado: str, strike: float) -> None:
    """Ficha do contrato + gráfico de payoff, no layout da página de detalhe."""
    perna = "CALL" if lado == "calls" else "PUT"
    c = None
    for x in cadeia.contratos(lado):
        k = desempacotar(x.get("strike"))
        if isinstance(k, (int, float)) and abs(k - strike) < 1e-9:
            c = x
            break
    if c is None:
        aviso(f"strike {fdec(strike)} sem contrato na perna {perna} deste vencimento")
        return
    prem = _premio_efetivo(c)
    be = _breakeven(lado, desempacotar(c.get("strike")), prem)
    ask = desempacotar(c.get("ask"))
    pago = ask if isinstance(ask, (int, float)) else prem   # o custo REAL de comprar agora é o ask
    be_compra = _breakeven(lado, desempacotar(c.get("strike")), pago)
    spot = cadeia.spot
    chg = desempacotar(c.get("change"))
    pct = desempacotar(c.get("percentChange"))
    vol = desempacotar(c.get("volume"))
    oi = desempacotar(c.get("openInterest"))
    itm = bool(c.get("inTheMoney"))
    badge = cor(" IN THE MONEY ", "negrito", "verde") if itm else cor(" OUT OF THE MONEY ", "negrito", "vermelho")
    baixa = (vol or 0) < 100 and (oi or 0) < 100
    print()
    print(badge)
    print(cor(f" {cadeia.simbolo} $ {fdec(strike)} {perna}", "negrito", "branco")
          + cor(f"   · expira em {fdata(cadeia.vencimento)} ({dte(cadeia.vencimento)})", "dim"))
    print()
    print(f" Prêmio (últ.)  $ {fdec(prem)}"
          + (f"   ({fdec(chg)} · {fpct(pct, 2, sinal=True)})" if isinstance(pct, (int, float)) else ""))
    print(f" Compra (ask)   $ {fdec(ask)}"
          + f"     Venda (bid) $ {fdec(desempacotar(c.get('bid')))}")
    print(f" Breakeven p/ compra $ {fdec(be_compra)}"
          + f"  (pelo último: $ {fdec(be)})")
    print(f" {cadeia.simbolo} atual US$ {fdec(spot)} ({cadeia.market_state})")
    print(f" Volume    {fnum(vol)}    Open Int.  {fnum(oi)}"
          + f"     IV {fiv(desempacotar(c.get('impliedVolatility')))}")
    lt = c.get("lastTradeDate")
    print(f" Últ. negócio {fdata(desempacotar(lt), com_hora=True, ny=True) if lt is not None else '—'} (NY)"
          + f"   · contrato {c.get('contractSymbol', '—')}")
    if baixa:
        print(cor(" ⚠ Este contrato possui baixa liquidez", "amarelo"))
    print()
    print(cor(" Gráfico de Payoff", "negrito", "ambar")
          + cor(f"   · compra de uma {perna} pelo ask $ {fdec(ask)} (custo real de entrada)", "dim"))
    print(grafico_payoff_ascii(lado, strike, pago if isinstance(pago, (int, float)) else 0.0, spot))
    print()
    print(cor(" Informações", "negrito", "ambar"))
    print(f" Volume {fnum(vol)}   ·   Open Int. {fnum(oi)}   ·   Liquidação T+1 (1 dia útil)")
    print(cor("  (o endpoint não expõe máx/mín do dia do contrato — só último/bid/ask)", "dim"))
    print(cor("  cenários da compra: perda do prêmio pago até o strike · empate no breakeven · lucro acima dele", "dim"))


# ───────────────────── Estado + ações do menu interativo ────────────────── #

class Estado:
    def __init__(self, host: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT,
                 lang: str = "en-US", region: str = "US") -> None:
        self.host = host
        self.timeout = timeout
        self.lang = lang
        self.region = region
        self.cliente: Optional[Cliente] = None
        self.ultimo_payload: Optional[dict] = None
        self.ultimo_simbolo: Optional[str] = None
        self.ultimo_strike: Optional[float] = None


def obter_cliente(est: Estado) -> Cliente:
    if est.cliente is None:
        print()
        aviso("inicializando sessão: bootstrap A3 + crumb (2 passos)")
        c = Cliente(est.host, est.timeout, est.lang, est.region)
        c.bootstrap()
        cookies = ", ".join(c.info_auth()["cookies"]) or "—"
        ok(f"sessão pronta — crumb {mascarar(c.crumb)} · cookies {cookies}")
        est.cliente = c
    return est.cliente


def acao_consultar(est: Estado) -> None:
    simbolo = pedir("Símbolo (ex.: AAPL, NVDA, SPY, PETR4.SA, ^GSPC)", default="AAPL")
    if not simbolo:
        return
    c = obter_cliente(est)
    payload = c.cadeia(simbolo)
    est.ultimo_payload = payload
    est.ultimo_simbolo = simbolo
    est.ultimo_strike = None
    cadeia = Cadeia(payload)
    print()
    _mostrar_requisicao(c)
    exibir_resumo(cadeia)
    _loop_visoes(est, cadeia)


def _loop_visoes(est: Estado, cadeia: Cadeia) -> None:
    """Submenu de visões da cadeia do símbolo em tela (loop contínuo)."""
    while True:
        op = escolher("VISÕES DA CADEIA", [
            ("Grade de CALLS", "TODOS os contratos — 11 colunas da página oficial"),
            ("Grade de PUTS", "idem, perna de venda"),
            ("Cadeia combinada", "call | strike | put lado a lado"),
            ("Straddle", "pares {strike, call, put} do fio (straddle=true)"),
            ("Trocar vencimento", f"{len(cadeia.expiracoes)} datas disponíveis"),
            ("Visão de um strike", "um strike em TODOS os vencimentos (getAllData)"),
            ("Vencimentos", "tabela com epoch pronto para copiar"),
            ("Ficha do subjacente", "quote embutido do payload"),
            ("JSON bruto", "envelope integral indentado"),
            ("Salvar JSON", "corpo cru em arquivo"),
            ("Ladder Avenue", "cartões Strike/Breakeven/Prêmio (Call ou Put)"),
            ("Detalhe + payoff (Avenue)", "ficha do contrato + gráfico de payoff"),
        ])
        if op == 0:
            return
        try:
            if op == 1:
                exibir_grade(cadeia, "calls",
                             f"GRADE DE CALLS — {cadeia.simbolo}")
            elif op == 2:
                exibir_grade(cadeia, "puts",
                             f"GRADE DE PUTS — {cadeia.simbolo}")
            elif op == 3:
                exibir_combinada(cadeia)
            elif op == 4:
                c = obter_cliente(est)
                p2 = c.cadeia(cadeia.simbolo, date=str(cadeia.vencimento or "-1"),
                              straddle=True)
                _mostrar_requisicao(c)
                exibir_straddle(Cadeia(p2))
            elif op == 5:
                exibir_vencimentos(cadeia)
                idx = pedir_int(f"Vencimento (1..{len(cadeia.expiracoes)}, 0=voltar)",
                                0, len(cadeia.expiracoes), 0)
                if idx:
                    c = obter_cliente(est)
                    p2 = c.cadeia(cadeia.simbolo, date=str(cadeia.expiracoes[idx - 1]))
                    _mostrar_requisicao(c)
                    cadeia = Cadeia(p2)
                    est.ultimo_payload = p2
                    exibir_resumo(cadeia)
            elif op == 6:
                k = pedir("Strike (ex.: 160 · 187.5)", default=str(
                    cadeia.strike_mais_proximo() or ""))
                try:
                    k_num = float(str(k).replace(",", "."))
                except (TypeError, ValueError):
                    aviso("strike numérico inválido")
                    continue
                c = obter_cliente(est)
                p2 = c.cadeia(cadeia.simbolo, strike=k_num)
                _mostrar_requisicao(c)
                est.ultimo_payload = p2
                est.ultimo_strike = k_num
                exibir_strike_todos_vencimentos(Cadeia(p2), k_num, p2)
            elif op == 7:
                exibir_vencimentos(cadeia)
            elif op == 8:
                exibir_subjacente(cadeia)
            elif op == 9:
                print()
                exibir_json(est.ultimo_payload or {})
            elif op == 10:
                _salvar_json(est)
            elif op == 11:
                lado_av = escolher("Perna do ladder Avenue", ["CALLS", "PUTS"])
                if lado_av:
                    exibir_avenue(cadeia, "calls" if lado_av == 1 else "puts")
            elif op == 12:
                k_av = pedir("Strike do contrato", default=str(cadeia.strike_mais_proximo() or ""))
                try:
                    k_num = float(str(k_av).replace(",", "."))
                except (TypeError, ValueError):
                    aviso("strike numérico inválido")
                    continue
                lado_dt = escolher("Perna", ["CALLS", "PUTS"])
                if lado_dt:
                    exibir_detalhe_avenue(cadeia, "calls" if lado_dt == 1 else "puts", k_num)
        except ErroEndpoint as e:
            imprimir_erro(e)


def _salvar_json(est: Estado) -> None:
    if not est.ultimo_payload:
        aviso("consulte um símbolo primeiro")
        return
    eco = est.ultimo_simbolo or (est.ultimo_payload.get("optionChain", {})
                                 .get("result", [{}])[0].get("underlyingSymbol", "x")
                                 if est.ultimo_payload.get("optionChain", {})
                                 .get("result") else "x")
    padrao = f"options_{eco}_{int(time.time())}.json"
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
    bruto = pedir("Símbolos separados por vírgula (máx. 8)",
                  default="AAPL,NVDA,SPY,QQQ")
    if not bruto:
        return
    simbolos = [s.strip() for s in bruto.split(",") if s.strip()][:8]
    c = obter_cliente(est)
    resultados = []
    for s in simbolos:
        try:
            p = c.cadeia(s)
            resultados.append((s, Cadeia(p), None))
        except Exception as e:  # noqa: BLE001 — uma falha não derruba a tabela
            resultados.append((s, None, str(e)))
        time.sleep(0.6)  # respeita o rate da edge
    headers = ["SÍMBOLO", "VENC. ATIVO", "DTE", "EXP.", "STRIKES",
               "VOL C", "VOL P", "P/C", "OI C", "OI P", "P/C", "IVm C", "IVm P"]
    aligns = ["<", ">", ">", ">", ">", ">", ">", ">", ">", ">", ">", ">", ">"]
    rows = []
    for simb, cadeia, err in resultados:
        if err or cadeia is None:
            rows.append([simb, cor(f"erro: {err}", "vermelho")] + ["—"] * 11)
            continue
        rc = cadeia.resumo_lados("calls")
        rp = cadeia.resumo_lados("puts")
        rows.append([
            cadeia.simbolo, fdata(cadeia.vencimento), dte(cadeia.vencimento),
            len(cadeia.expiracoes), len(cadeia.strikes),
            fnum(rc["volume"]), fnum(rp["volume"]),
            fdec(rp["volume"] / rc["volume"]) if rc["volume"] else "—",
            fnum(rc["oi"]), fnum(rp["oi"]),
            fdec(rp["oi"] / rc["oi"]) if rc["oi"] else "—",
            fiv(rc["iv_media"]), fiv(rp["iv_media"]),
        ])
    print("\n" + cor(" COMPARAÇÃO — uma requisição por símbolo (a API não tem lote)",
                     "negrito", "ambar"))
    imprimir_tabela(headers, rows, aligns)
    print(cor("  VOL/OI do VENCIMENTO ATIVO de cada símbolo (o endpoint devolve 1 "
              "expiração por vez)", "dim"))


def acao_console(est: Estado) -> None:
    print(cor("\n CONSOLE DE REQUISIÇÃO — monte e dispare a requisição bruta",
              "negrito", "ambar"))
    print(cor("  (GET canônico; POST → 405; HEAD → 200 sem corpo; OPTIONS → Allow)",
              "dim"))
    simbolo = pedir("Símbolo no path (crudo, com encoding se precisar: %5EGSPC)",
                    default="AAPL")
    if not simbolo:
        return
    opm = escolher("Método", [
        ("GET (canônica)", "crumb no query param"),
        ("POST", "esperado 405"),
        ("HEAD", "esperado 200 com Content-Length 0"),
        ("OPTIONS", "esperado 200 com Allow: HEAD,GET,OPTIONS"),
    ])
    if opm == 0:
        return
    metodo = ["GET", "POST", "HEAD", "OPTIONS"][opm - 1]

    extras = pedir("Params extras k=v (separe com & — vazio = nenhum)", default="") or ""
    params: Dict[str, str] = {"lang": est.lang, "region": est.region,
                              "date": "-1", "formatted": "true", "straddle": "false"}
    for par in extras.replace(";", "&").split("&"):
        if "=" in par:
            k, v = par.split("=", 1)
            params[k.strip()] = v.strip()

    headers: Dict[str, str] = {}
    usar_x_crumb = False
    if metodo == "GET":
        r = pedir("Enviar o crumb via header x-crumb em vez do query param? s/n",
                  default="n")
        usar_x_crumb = bool(r) and str(r).lower().startswith("s")
    extra_h = pedir("Headers extras 'Nome: valor' (separe com ; — vazio = nenhum)",
                    default="") or ""
    for par in extra_h.split(";"):
        if ":" in par:
            k, v = par.split(":", 1)
            headers[k.strip()] = v.strip()

    c = obter_cliente(est)
    if usar_x_crumb:
        headers["x-crumb"] = c.crumb or ""
    elif metodo in ("GET", "HEAD"):
        params.setdefault("crumb", c.crumb or "")
    r = c.consultar(simbolo, params, metodo, headers or None, sem_crumb=usar_x_crumb)

    print("\n" + caixa([
        f"método ....... {metodo}",
        f"url .......... {r.url.replace(c.crumb, '…') if c.crumb else r.url}",
        f"headers extras {headers or '—'}",
    ], titulo="REQUISIÇÃO"))
    linhas_resp = [f"status ....... {r.status}", f"tempo ........ {r.ms:.0f} ms",
                   f"corpo ........ {len(r.corpo)} bytes", ""]
    linhas_resp += [f"{k}: {v}" for k, v in sorted(r.headers.items())]
    print(caixa(linhas_resp, titulo="RESPOSTA"))

    if r.corpo:
        try:
            j = json.loads(r.corpo)
            txt = json.dumps(j, indent=2, ensure_ascii=False)
            print("\n" + cor(" CORPO (JSON indentado)", "negrito", "ambar"))
            print(txt[:6000] + (cor("\n… (truncado — 'salvar' para o integral)", "dim")
                                if len(txt) > 6000 else ""))
        except ValueError:
            print("\n" + cor(" CORPO (texto puro — ex.: 404 da barra final ou 429 da edge)",
                             "negrito", "ambar"))
            print(r.corpo[:4000])
    else:
        aviso("corpo vazio (HEAD suprime o corpo — Content-Length 0)")
    if pedir("Salvar o corpo em arquivo? s/n", default="n").lower().startswith("s"):
        nome = pedir("Arquivo", default=f"resposta_{metodo.lower()}_{simbolo[:8]}.txt")
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
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "yh-finance-api", "v7_finance_options", "v7_finance_options.json"),
        "v7_finance_options.json",
    ]
    padrao = next((os.path.abspath(p) for p in candidatos if os.path.isfile(p)),
                  "v7_finance_options.json")
    arq = pedir("Fixture JSON (optionChain) para auditar", default=padrao)
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


def acao_autenticacao(est: Estado) -> None:
    while True:
        op = escolher("AUTENTICAÇÃO — par atômico Cookie A3 + Crumb", [
            ("Status da sessão", "crumb mascarado, cookies, contadores"),
            ("Renovar o par agora", "bootstrap 2 passos: fc.yahoo.com → getcrumb"),
            ("Teste anônimo (esperado 401)", "sem cookie e sem crumb — envelope de 89 B"),
            ("Teste crumb garbage (esperado 401)", "cookie válido + crumb inválido"),
            ("Teste vetor duplo x-crumb (esperado 200)", "crumb no header em vez do query"),
            ("Teste UA de biblioteca (esperado 429)", "User-Agent Python-urllib na edge"),
        ])
        if op == 0:
            return
        if op == 1:
            c = obter_cliente(est)
            info = c.info_auth()
            print("\n" + caixa([
                f"host ............. {info['host']}  ({info['base']})",
                f"crumb ............ {info['crumb_mascarado']}",
                f"cookie A3 ........ {'presente' if info['a3'] else 'AUSENTE'}",
                f"cookies no jar ... {', '.join(info['cookies']) or '—'}",
                f"requisições ...... {info['requisicoes']}",
                "fluxo ........... fc.yahoo.com (404 sem redirect; Set-Cookie A3) → "
                "v1/test/getcrumb (UA + Referer)",
            ], titulo="SESSÃO"))
        elif op == 2:
            if est.cliente is None:
                obter_cliente(est)
            else:
                aviso("renovando: novo bootstrap (par atômico — sempre junto)")
                est.cliente.crumb = None
                est.cliente.bootstrap()
                ok(f"par renovado — crumb {mascarar(est.cliente.crumb)}")
        elif op == 3:
            c2 = Cliente(est.host, est.timeout, est.lang, est.region)  # jar limpo
            r = c2.consultar("AAPL", {"lang": est.lang, "region": est.region})
            print(f"\n  status {r.status} · {len(r.corpo)} bytes · {r.corpo[:120]}")
            if r.status == 401 and "Invalid Crumb" in r.corpo:
                ok("401 Invalid Crumb com envelope finance de 89 B, como esperado")
            else:
                erro(f"esperado 401 Invalid Crumb, veio {r.status}")
        elif op == 4:
            c = obter_cliente(est)
            r = c.consultar("AAPL", {"lang": est.lang, "region": est.region,
                                     "crumb": "garbage123XYZ"})
            print(f"\n  status {r.status} · {r.corpo[:120]}")
            if r.status == 401 and "Invalid Crumb" in r.corpo:
                ok("401 Invalid Crumb com crumb desemparelhado (o servidor valida o par)")
            else:
                erro(f"esperado 401, veio {r.status}")
        elif op == 5:
            c = obter_cliente(est)
            r = c.consultar("AAPL", {"lang": est.lang, "region": est.region,
                                     "date": "-1", "formatted": "true",
                                     "straddle": "false"},
                            headers={"x-crumb": c.crumb or ""}, sem_crumb=True)
            if r.status == 200 and '"optionChain"' in r.corpo:
                ok("200 com envelope optionChain — o vetor x-crumb sozinho é aceito")
            else:
                erro(f"esperado 200 optionChain, veio {r.status}: {r.corpo[:120]}")
        elif op == 6:
            c = obter_cliente(est)
            r = c.consultar("AAPL", {"lang": est.lang, "region": est.region},
                            headers={"User-Agent": "Python-urllib/3.13"})
            print(f"\n  status {r.status} · corpo: {r.corpo[:80]!r}")
            if r.status == 429:
                ok("429 Edge (bloqueio por assinatura de UA, não por volume)")
            else:
                erro(f"esperado 429, veio {r.status}")


def _atualizar_cliente(est: Estado) -> None:
    if est.cliente:
        est.cliente.lang = est.lang
        est.cliente.region = est.region


def acao_config(est: Estado) -> None:
    while True:
        op = escolher("CONFIGURAÇÕES", [
            (f"Host: {est.host}", "query1 (produção) · query2 (espelho) · iquery (interno)"),
            (f"lang: {est.lang}", "injetado pelo transporte (default en-US)"),
            (f"region: {est.region}", "idem"),
            (f"timeout: {est.timeout:g} s", "o cliente oficial usa 15 s"),
            ("cores: ligar/desligar", "verde=call · magenta=put · ambar=marca"),
            ("caracteres: unicode/ascii", "se os desenhos saírem estranhos, use ASCII"),
        ])
        if op == 0:
            return
        if op == 1:
            h = escolher("Host", list(HOSTS_EP.keys()))
            if h:
                est.host = list(HOSTS_EP)[h - 1]
                est.cliente = None  # nova sessão no novo host
                aviso(f"host mudou para {est.host} — nova sessão na próxima consulta")
        elif op == 2:
            v = pedir("lang", default=est.lang)
            if v:
                est.lang = v
                _atualizar_cliente(est)
        elif op == 3:
            v = pedir("region", default=est.region)
            if v:
                est.region = v
                _atualizar_cliente(est)
        elif op == 4:
            v = pedir("timeout em segundos", default=str(est.timeout))
            try:
                est.timeout = max(3.0, float(str(v)))
                if est.cliente:
                    est.cliente.timeout = est.timeout
            except ValueError:
                aviso("valor inválido — mantido o anterior")
        elif op == 5:
            global _CORES
            _CORES = not _CORES
            aviso(f"cores {'ligadas' if _CORES else 'desligadas'}")
        elif op == 6:
            global _ASCII
            _ASCII = not _ASCII


def acao_ajuda(est: Estado) -> None:
    print()
    secao("O QUE A CONSULTA DEVOLVE")
    print('  envelope: {"optionChain": {"result": [...], "error": null}} '
          "(topo próprio; finance só nos ERROS)")
    print()
    print("  result[0] — 6 chaves:")
    print("    underlyingSymbol ....... eco do symbol do PATH (a seleção não é por query)")
    print("    expirationDates ........ TODAS as expirações, epoch em SEGUNDOS, ordenada")
    print("    strikes ................ malha do símbolo (EXPANDE p/ união de todas as")
    print("                             expirações no modo strike+getAllData: 76 → 130 em AAPL)")
    print("    hasMiniOptions ......... mini-contratos (nunca true observado aqui)")
    print("    quote .................. o PACOTE v7 do subjacente EMBUTIDO (83–90 campos")
    print("                             em ações; 61 no ^GSPC; deslistado → NONE; quirks")
    print("                             prevName/nameChangeDate em renomeações)")
    print("    options[] .............. UMA entrada por expiração pedida (date/-1) OU uma")
    print("                             por vencimento no modo strike; cada uma com")
    print("                             expirationDate, hasMiniOptions e calls[]/puts[]")
    print("                             (ou straddles[] com straddle=true)")
    print()
    print("  cada contrato: 15 campos lidos POR NOME (a ordem no wire VARIA entre")
    print("  símbolos): contractSymbol (OCC), strike, currency, lastPrice, change,")
    print("  percentChange, volume, openInterest, bid, ask, contractSize, expiration,")
    print("  lastTradeDate, impliedVolatility, inTheMoney.")
    secao("UNIDADES E PACOTAMENTO")
    print("""  formatted=true (o app oficial envia SEMPRE) → {raw, fmt, longFmt};
  longFmt = milhar em volume/openInterest; data+hora em lastTradeDate/expiration;
  inTheMoney e currency são crus; IV em FRAÇÃO anualizada (1.0 = 100%).
  formatted=false → números crus (strike: 160, lastPrice: 184.91).
  volume é OMITIDO quando não há negociação no dia; lastTradeDate pode
  permanecer de um trade anterior.""")
    secao("PARÂMETROS")
    print("""  {symbol} (path) .. obrigatório, URL-encoded (^GSPC → %5EGSPC); SEM LOTE
  date ............. epoch em SEGUNDOS DE expirationDates; -1 LITERAL = primeira
                     futura (o app envia); AUSENTE ≡ -1; abc/1.5 → 400
                     'Parameter=date has an invalid type' (109 B); 0/-2/fora da
                     lista → 200 ecoando o valor com arrays vazios
  formatted ........ true empacota {raw,fmt[,longFmt]}; 1/abc NÃO ativam
  straddle ......... true troca calls/puts por straddles[{strike, call, put}];
                     funciona com date e com o modo strike
  strikeMin/strikeMax .. limites inclusivos; não-numéricos → 400 (114 B);
                     NaN = sem filtro; Infinity em min = 0, em max = tudo
  getAllData ....... sem date/-1 → TODAS as expirações; date específico → 1;
                     0/-2 → 1 entrada vazia; + par de strikes (sem date) → 1
                     entrada POR VENCIMENTO
  lang/region ...... da sessão (transporte); NÃO ecoam no quote embutido
  crumb ............ OBRIGATÓRIO, casado com o Cookie A3; query é o vetor usual,
                     header x-crumb sozinho também é aceito (query vence em
                     divergência; crumb válido sem cookie A3 → 401)""")
    secao("ERROS E DEGRADAÇÕES (verificado ao vivo em 2026-11-05/06)")
    print("""  401 Unauthorized / Invalid Crumb (89 B) . par A3+crumb ausente/desemparelhado
  400 Bad Request / Parameter=date has an invalid type (109 B) . date não-numérico
  400 Bad Request / Parameter=strikeMin has an invalid type (114 B) . strike não-numérico
  404 TEXTO PURO 'Not Found' ........ barra final (/options/AAPL/)
  404 envelope finance .............. path sem símbolo (/options/)
  405 Method Not Allowed ............ POST
  429 'Edge: Too Many Requests' ..... UA de biblioteca (assinatura, não volume)
  200 result: [] (42 B) ............. símbolo inexistente (ZZZZZZ, 2026-11-05)
  200 quote NONE + options[0] = {} .. deslistado (TWTR)
  200 arrays vazios + quote completo  sem cadeia pública (PETR4.SA, ^GSPC;
                                      83–90 campos em ações; 61 no ^GSPC)
  cache de borda: GET 200 = 'public, max-age=1, stale-while-revalidate=9'
  (janela de ~10 s — não reconsulte em rajada); HEAD = no-store""")
    secao("CURIOSIDADES")
    print("""  · o quote do header da página NÃO vem daqui — vem do pipeline comum de quote;
    o payload o carrega por redundância (só a ficha do app o usa).
  · seletor de strike da página: sentinela local 'ALL_STRIKE_PRICES' — o ALL não
    vai ao fio; escolher um strike entra no modo getAllData.
  · a cadeia do vencimento ATIVO só muda de vencimento por NOVA chamada (sem poller).
  · irmão /v7/finance/options/analytics/{symbol}: summaries e top-10 (outro endpoint).

  relatório completo: yh-finance-api/v7_finance_options/v7_finance_options.md""")


# ─────────────────────── Auditoria de invariantes (offline) ──────────────── #

def auditar_payload(payload: dict) -> List[Tuple[str, bool, str]]:
    out: List[Tuple[str, bool, str]] = []

    def chk(nome, cond, det=""):
        out.append((nome, bool(cond), det))

    oc = payload.get("optionChain") or {}
    chk("envelope optionChain com error null",
        oc.get("error") is None and isinstance(oc.get("result"), list))
    if not oc.get("result"):
        return out
    r0 = oc["result"][0]
    chk("6 chaves raiz presentes",
        CHAVES_RAIZ.issubset(set(r0)), f"keys={sorted(r0)}")
    exps = r0.get("expirationDates") or []
    chk("expirationDates ordenada crescente e positiva",
        exps == sorted(exps) and all(e > 0 for e in exps),
        f"{len(exps)} datas")
    strikes = r0.get("strikes") or []
    chk("strikes ordenada crescente e sem repetição",
        strikes == sorted(strikes) and len(set(strikes)) == len(strikes),
        f"{len(strikes)} strikes")
    quote = r0.get("quote") or {}
    chk("quote.symbol == underlyingSymbol",
        quote.get("symbol") == r0.get("underlyingSymbol"),
        f"{quote.get('symbol')} vs {r0.get('underlyingSymbol')}")
    spot = quote.get("regularMarketPrice")
    if isinstance(spot, (int, float)) and not isinstance(spot, bool):
        chk("quote do subjacente com escalares crus (formatted não empacota o quote)",
            isinstance(spot, (int, float)))
    blocos = r0.get("options") or []
    ncontr = 0
    viol_occ, viol_itm, viol_pack, viol_exp = [], [], [], []
    for b in blocos:
        b = b or {}
        exp_b = b.get("expirationDate")
        for lado in ("calls", "puts"):
            for c in b.get(lado) or []:
                ncontr += 1
                occ = c.get("contractSymbol", "")
                m = RE_OCC.match(occ)
                if not m:
                    viol_occ.append(occ)
                    continue
                # data do OCC (20YY-MM-DD) deve ser o vencimento do contrato
                yy, mm, dd = int(m.group("yy")), int(m.group("mm")), int(m.group("dd"))
                try:
                    d_occ = datetime.date(2000 + yy, mm, dd)
                    d_exp = datetime.datetime.fromtimestamp(
                        desempacotar(c.get("expiration")) or 0,
                        datetime.timezone.utc).date()
                    if d_occ != d_exp:
                        viol_exp.append(occ)
                except (ValueError, OverflowError, OSError, TypeError):
                    viol_exp.append(occ)
                if isinstance(spot, (int, float)) and not isinstance(spot, bool):
                    st = desempacotar(c.get("strike"))
                    if isinstance(st, (int, float)):
                        esperado = (st < spot) if lado == "calls" else (st > spot)
                        if bool(c.get("inTheMoney")) != esperado:
                            viol_itm.append(occ)
                if "formatted" not in payload:  # heurística: empacotado tem dicts
                    k = c.get("strike")
                    if isinstance(k, dict) and ("raw" not in k):
                        viol_pack.append(occ)
                    lf_extra = [f for f in ("strike", "lastPrice", "bid", "ask")
                                if isinstance(c.get(f), dict) and "longFmt" in c[f]]
                    if lf_extra:
                        viol_pack.append(f"{occ}:{','.join(lf_extra)}")
    chk(f"contratos com contractSymbol no padrão OCC ({ncontr} contratos)",
        not viol_occ, f"violações: {viol_occ[:3]}" if viol_occ else "todas válidas")
    if isinstance(spot, (int, float)) and not isinstance(spot, bool) and ncontr:
        chk("inTheMoney consistente com o spot (call ITM: strike < spot; put: strike > spot)",
            not viol_itm, f"violações: {viol_itm[:3]}" if viol_itm else "todas consistentes")
    chk("empacotamento {raw, fmt} correto (longFmt só em volume/OI/lastTradeDate/expiration)",
        not viol_pack, f"violações: {viol_pack[:3]}" if viol_pack else "nenhuma")
    chk("data do contractSymbol OCC == expiration do contrato",
        not viol_exp, f"violações: {viol_exp[:3]}" if viol_exp else "todas coincidem")
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


# ─────────────────────── Suíte de verificação ao vivo (23) ────────────────── #

def verificacao(c: Cliente, simbolo: str = "AAPL") -> bool:
    print(cor(f"\n SUÍTE DE VERIFICAÇÃO AO VIVO — {simbolo}", "negrito", "ambar"))
    print(cor("  cada checagem faz requisição real; pausa curta para não tomar 429", "dim"))
    resultados: List[bool] = []

    def chk(nome, cond, detalhe=""):
        resultados.append(bool(cond))
        marca = cor("✔ PASS", "verde") if cond else cor("✖ FAIL", "vermelho")
        print(f"  {marca}  {nome}" + (cor(f" — {detalhe}", "dim") if detalhe else ""))
        time.sleep(1.0)

    # 1. anônimo → 401 Invalid Crumb (89 B)
    c2 = Cliente(host=c.host_nome, timeout=c.timeout, lang=c.lang, region=c.region)
    r = c2.consultar(simbolo, {"lang": c.lang, "region": c.region})
    chk("anônimo → 401 Invalid Crumb (89 B)",
        r.status == 401 and "Invalid Crumb" in r.corpo and len(r.corpo) == 89,
        f"status={r.status} len={len(r.corpo)}")

    # 2. UA de biblioteca → 429
    r = c.consultar(simbolo, {"lang": c.lang, "region": c.region},
                    headers={"User-Agent": "Python-urllib/3.13"})
    chk("User-Agent python-urllib → 429 Edge", r.status == 429, f"status={r.status}")

    # 3. canônica date=-1 → 200 + eco
    p = c.cadeia(simbolo)
    cadeia = Cadeia(p)
    chk("canônica date=-1 → 200 com underlyingSymbol ecoado",
        cadeia.simbolo == simbolo.upper(), f"{cadeia.simbolo}")

    # 4. 6 chaves raiz
    chk("result[0] com as 6 chaves raiz", CHAVES_RAIZ.issubset(set(cadeia.r0)),
        f"{sorted(cadeia.r0)}")

    # 5. date=-1 → 1 vencimento em options[]
    chk("date=-1 → exatamente 1 entrada em options[]", len(cadeia.blocos) == 1,
        f"len={len(cadeia.blocos)}")

    # 6. o vencimento ativo == expirationDates[0]
    chk("options[0].expirationDate == expirationDates[0]",
        cadeia.vencimento == cadeia.expiracoes[0],
        f"{cadeia.vencimento} vs {cadeia.expiracoes[0] if cadeia.expiracoes else None}")

    # 7. contrato com o esquema canônico (15 campos; volume pode faltar sem negócio)
    cs = cadeia.contratos("calls")
    faltando = (set(CAMPOS_CONTRATO) - set(cs[0])) if cs else set(CAMPOS_CONTRATO)
    chk("contrato com o esquema canônico (15 campos; volume pode faltar sem negócio)",
        bool(cs) and faltando <= {"volume"},
        f"faltando={sorted(faltando)}" if faltando else "todos presentes")

    # 8. formatted=true empacota strike em {raw, fmt}
    if cs:
        k = cs[0].get("strike")
        chk("formatted=true → strike em {raw, fmt}",
            isinstance(k, dict) and "raw" in k and "fmt" in k)
    # 9. inTheMoney cru
    if cs:
        chk("inTheMoney permanece booleano cru", isinstance(cs[0].get("inTheMoney"), bool))
    # 10. quote cru
    chk("quote do subjacente com escalares crus",
        isinstance(cadeia.spot, (int, float)) and not isinstance(cadeia.spot, bool),
        f"spot={cadeia.spot}")

    # 11. date não-numérico → 400 tipado
    r = c.consultar(simbolo, {"date": "abc", "formatted": "true",
                              "straddle": "false", "lang": c.lang, "region": c.region,
                              "crumb": c.crumb or ""})
    chk("date=abc → 400 'Parameter=date has an invalid type' (109 B)",
        r.status == 400 and "Parameter=date has an invalid type" in r.corpo
        and len(r.corpo) == 109, f"status={r.status} len={len(r.corpo)}")

    # 11b. strikeMin não-numérico → 400 tipado (114 B)
    r = c.consultar(simbolo, {"date": "-1", "formatted": "true",
                              "straddle": "false", "strikeMin": "abc",
                              "strikeMax": "160", "lang": c.lang,
                              "region": c.region, "crumb": c.crumb or ""})
    chk("strikeMin=abc → 400 'Parameter=strikeMin has an invalid type' (114 B)",
        r.status == 400 and "Parameter=strikeMin has an invalid type" in r.corpo
        and len(r.corpo) == 114, f"status={r.status} len={len(r.corpo)}")

    # 12. date sem contratos → 200 com entrada vazia ecoando
    pz = c.cadeia(simbolo, date="9999999999")
    rz = _result0(pz)
    optz = (rz.get("options") or [{}])[0]
    chk("date sem contratos → 200, entrada ecoa o date com calls/puts vazios",
        optz.get("expirationDate") == 9999999999 and optz.get("calls") == [])

    # 13. straddle=true → straddles[{strike, call, put}] sem calls/puts
    ps = c.cadeia(simbolo, date=str(cadeia.vencimento or "-1"), straddle=True)
    o_s = (_result0(ps).get("options") or [{}])[0]
    s0 = (o_s.get("straddles") or [{}])[0]
    chk("straddle=true → straddles com strike FORA das pernas",
        "straddles" in o_s and "calls" not in o_s
        and {"strike", "call", "put"}.issubset(set(s0)),
        f"{len(o_s.get('straddles') or [])} pares")

    # 14/15. strike único → 1 entrada por vencimento + strikes expandidos
    k = cadeia.strike_mais_proximo()
    if k is not None:
        pk = c.cadeia(simbolo, strike=k)
        rk = _result0(pk)
        chk("strike único → options[] com UMA ENTRADA POR VENCIMENTO",
            len(rk.get("options") or []) == len(rk.get("expirationDates") or []),
            f"{len(rk.get('options') or [])} entradas")
        chk("header strikes EXPANDE no modo getAllData",
            len(rk.get("strikes") or []) > len(cadeia.strikes),
            f"{len(rk.get('strikes') or [])} vs {len(cadeia.strikes)}")
    else:
        chk("strike único → options[] com UMA ENTRADA POR VENCIMENTO", False,
            "sem strikes no payload para escolher")
        chk("header strikes EXPANDE no modo getAllData", False, "idem")

    # 16. símbolo inexistente → 200 result [] (42 B)
    r = c.consultar("TICKER_INEXISTENTE_XYZ99",
                    {"date": "-1", "formatted": "true", "straddle": "false",
                     "lang": c.lang, "region": c.region, "crumb": c.crumb or ""})
    j_inex = json.loads(r.corpo) if r.corpo.startswith("{") else {}
    chk("símbolo inexistente → 200 com result: [] (42 B)",
        r.status == 200 and (j_inex.get("optionChain") or {}).get("result") == [],
        f"{len(r.corpo)} B")

    # 17. sem cadeia pública (PETR4.SA) → 200 com expirationDates [] + quote completo
    pn = c.cadeia("PETR4.SA")
    rn = _result0(pn)
    chk("PETR4.SA (sem cadeia B3) → expirationDates [] + quote populado",
        rn.get("expirationDates") == [] and bool((rn.get("quote") or {}).get("symbol")))

    # 18. deslistado → quoteType NONE + options[0] = {}
    pd = c.cadeia("TWTR")
    rd = _result0(pd)
    chk("TWTR deslistado → quoteType NONE e options[0] vazio",
        (rd.get("quote") or {}).get("quoteType") == "NONE"
        and (rd.get("options") or [{}])[0] == {})

    # 19. POST → 405
    r = c.consultar(simbolo, {"lang": c.lang, "region": c.region,
                              "crumb": c.crumb or ""}, metodo="POST")
    chk("POST → 405 Method Not Allowed", r.status == 405, f"status={r.status}")

    # 20. HEAD com crumb → 200 CL=0 · barra final → 404 texto puro
    r = c.consultar(simbolo, {"lang": c.lang, "region": c.region,
                              "crumb": c.crumb or ""}, metodo="HEAD")
    cl = r.headers.get("content-length", "-1")
    chk("HEAD → 200 com Content-Length 0", r.status == 200 and cl == "0", f"CL={cl}")

    r = c.consultar(simbolo + "/", {"date": "-1", "formatted": "true",
                                    "straddle": "false", "lang": c.lang,
                                    "region": c.region, "crumb": c.crumb or ""})
    chk("barra final → 404 'Not Found' em texto puro",
        r.status == 404 and r.corpo.strip() == "Not Found", f"status={r.status}")

    # 21. cache do GET 200 = public, max-age=1 + SWR=9 (janela de borda de ~10 s;
    #     o HEAD vem com private, no-cache, no-store — nunca cacheável)
    r = c.consultar(simbolo, {"date": "-1", "formatted": "true", "straddle": "false",
                              "lang": c.lang, "region": c.region, "crumb": c.crumb or ""})
    cc = r.headers.get("cache-control", "")
    chk("cache-control do GET 200 = 'public, max-age=1, stale-while-revalidate=9'",
        cc == "public, max-age=1, stale-while-revalidate=9", f"cache-control={cc!r}")

    # 22. query2 espelho idêntico
    c2q = Cliente("query2", c.timeout, c.lang, c.region)
    c2q.jar = c.jar  # mesma sessão
    try:
        p2q = c2q.cadeia(simbolo)
        chk("query2 responde idêntico (200 + mesmo symbol)",
            Cadeia(p2q).simbolo == simbolo.upper())
    except ErroEndpoint as e:
        chk("query2 responde idêntico (200 + mesmo symbol)", False, str(e))

    print()
    npass = sum(resultados)
    print(caixa([f"{npass} PASS · {len(resultados) - npass} FAIL"], titulo="RESULTADO"))
    return all(resultados)


# ───────────────────────── Menu principal + modos CLI ────────────────────── #

MENU_PRINCIPAL = [
    ("Consultar cadeia de um símbolo",
     "canônica date=-1 · grades completas estilo página oficial"),
    ("Comparar múltiplos símbolos",
     "uma requisição por símbolo — a API não tem lote"),
    ("Console de requisição bruta",
     "params, método (GET/POST/HEAD/OPTIONS) e headers"),
    ("Suíte de verificação ao vivo",
     "24 checagens do contrato contra o servidor"),
    ("Auditoria de invariantes (offline)",
     "estrutura de uma fixture optionChain sem rede"),
    ("Autenticação A3 + crumb",
     "status, renovação e testes de 401/x-crumb/429"),
    ("Configurações",
     "host, lang/region, timeout, cores, ascii"),
    ("Ajuda — o que a API oferece",
     "contrato resumido: campos, unidades, erros"),
]


def modo_interativo(est: Estado) -> int:
    banner()
    despacho = {1: acao_consultar, 2: acao_comparar, 3: acao_console,
                4: acao_verificacao, 5: acao_auditoria, 6: acao_autenticacao,
                7: acao_config, 8: acao_ajuda}
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


def _grade_cli(c: Cliente, est: Estado, args) -> int:
    """Modo CLI não-interativo: uma consulta + a visão pedida."""
    payload = c.cadeia(args.simbolo, date=str(args.venc), formatted=not args.no_format,
                       straddle=args.straddle, strike=args.strike)
    est.ultimo_payload = payload
    est.ultimo_simbolo = args.simbolo
    cadeia = Cadeia(payload)
    print()
    _mostrar_requisicao(c)
    if args.raw:
        exibir_json(payload)
        return 0
    if args.json_out:
        r = c.ultimo_resp
        corpo = r.corpo.encode("utf-8") if r is not None and r.corpo else \
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with open(args.json_out, "wb") as fh:
            fh.write(corpo)
        print(cor(f"[fixture] corpo cru salvo em {args.json_out} ({len(corpo)} bytes)", "dim"))
        return 0
    if args.avenue:
        exibir_avenue(cadeia, "puts" if args.puts else "calls")
        return 0
    if args.detalhe is not None:
        exibir_detalhe_avenue(cadeia, "puts" if args.puts else "calls", args.detalhe)
        return 0
    if args.strike is not None:
        exibir_strike_todos_vencimentos(cadeia, args.strike, payload)
        return 0
    if args.straddle:
        exibir_straddle(cadeia)
        return 0
    if args.combinada:
        exibir_combinada(cadeia)
        return 0
    if args.puts:
        exibir_grade(cadeia, "puts", f"GRADE DE PUTS — {cadeia.simbolo}")
        return 0
    exibir_resumo(cadeia)
    exibir_grade(cadeia, "calls", f"GRADE DE CALLS — {cadeia.simbolo}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="App interativo + cliente do GET /v7/finance/options/{symbol} "
                    "(Yahoo Finance — cadeia de opções). Sem argumentos abre o menu; "
                    "o console só fecha no Sair.",
        epilog="exemplos:  %(prog)s AAPL   |   %(prog)s AAPL --strike 160   |   "
               "%(prog)s AAPL --straddle --venc 1793923200   |   %(prog)s --verifica")
    ap.add_argument("simbolo", nargs="?", default=None,
                    help="símbolo do subjacente (default: abre o menu interativo)")
    ap.add_argument("--venc", default="-1",
                    help="expiração: epoch em segundos ou -1 (primeira futura; default)")
    ap.add_argument("--straddle", action="store_true",
                    help="visão straddle=true (pares {strike, call, put})")
    ap.add_argument("--strike", type=float, default=None,
                    help="visão de um strike em TODOS os vencimentos (getAllData, sem date)")
    ap.add_argument("--combinada", action="store_true",
                    help="cadeia combinada call|strike|put")
    ap.add_argument("--puts", action="store_true",
                    help="mostra a grade de PUTS em vez de CALLS")
    ap.add_argument("--no-format", action="store_true",
                    help="formatted=false (números crus no fio)")
    ap.add_argument("--avenue", action="store_true",
                    help="ladder de cartões Strike/Breakeven/Prêmio (visão Avenue)")
    ap.add_argument("--detalhe", type=float, default=None, metavar="STRIKE",
                    help="ficha do contrato + gráfico de payoff (estilo Avenue)")
    ap.add_argument("--raw", action="store_true", help="imprime o envelope JSON indentado")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="salva o corpo cru da consulta em arquivo")
    ap.add_argument("--comparar", metavar="S1,S2,...",
                    help="compara múltiplos símbolos (uma requisição cada)")
    ap.add_argument("--verifica", action="store_true",
                    help="suíte de 24 checagens ao vivo do contrato")
    ap.add_argument("--auditar", default=None, metavar="ARQ",
                    help="audita invariantes de uma fixture optionChain (offline)")
    ap.add_argument("--host", choices=list(HOSTS_EP), default=DEFAULT_HOST,
                    help="host do serviço (default: query1)")
    ap.add_argument("--lang", default="en-US", help="query lang do transporte (default: en-US)")
    ap.add_argument("--region", default="US", help="query region do transporte (default: US)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help="timeout HTTP em segundos (default: 15)")
    ap.add_argument("--sem-cores", "--no-color", dest="sem_cores", action="store_true",
                    help="desliga cores e efeitos ANSI")
    ap.add_argument("--ascii", action="store_true",
                    help="caracteres ASCII puros (compatibilidade)")
    ap.add_argument("--no-pause", action="store_true",
                    help="não aguarda ENTER no fim (uso em scripts)")
    args = ap.parse_args(argv)

    ini_ui(cores=not args.sem_cores, ascii_=args.ascii)
    est = Estado(args.host, args.timeout, args.lang, args.region)

    quer_interativo = args.simbolo is None and not (
        args.comparar or args.verifica or args.auditar or args.raw
        or args.json_out or args.strike or args.straddle or args.combinada
        or args.puts or args.avenue or args.detalhe is not None)

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
            est_ = est
            bruto = args.comparar
            simbolos = [s.strip() for s in bruto.split(",") if s.strip()][:8]
            c = obter_cliente(est_)
            resultados = []
            for s in simbolos:
                try:
                    resultados.append((s, Cadeia(c.cadeia(s)), None))
                except Exception as e:  # noqa: BLE001
                    resultados.append((s, None, str(e)))
                time.sleep(0.6)
            headers = ["SÍMBOLO", "VENC. ATIVO", "DTE", "EXP.", "STRIKES",
                       "VOL C", "VOL P", "P/C", "OI C", "OI P", "P/C", "IVm C", "IVm P"]
            rows = []
            for simb, cadeia, err in resultados:
                if err or cadeia is None:
                    rows.append([simb, cor(f"erro: {err}", "vermelho")] + ["—"] * 11)
                    continue
                rc = cadeia.resumo_lados("calls")
                rp = cadeia.resumo_lados("puts")
                rows.append([
                    cadeia.simbolo, fdata(cadeia.vencimento), dte(cadeia.vencimento),
                    len(cadeia.expiracoes), len(cadeia.strikes),
                    fnum(rc["volume"]), fnum(rp["volume"]),
                    fdec(rp["volume"] / rc["volume"]) if rc["volume"] else "—",
                    fnum(rc["oi"]), fnum(rp["oi"]),
                    fdec(rp["oi"] / rc["oi"]) if rc["oi"] else "—",
                    fiv(rc["iv_media"]), fiv(rp["iv_media"])])
            print("\n" + cor(" COMPARAÇÃO — uma requisição por símbolo (a API não tem lote)",
                             "negrito", "ambar"))
            imprimir_tabela(headers, rows)
            return 0
        if args.verifica:
            c = obter_cliente(est)
            return 0 if verificacao(c, (args.simbolo or "AAPL").upper()) else 1
        if quer_interativo:
            return modo_interativo(est)
        c = obter_cliente(est)
        return _grade_cli(c, est, args)
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
