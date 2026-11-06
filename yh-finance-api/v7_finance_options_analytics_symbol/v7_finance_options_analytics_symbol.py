#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v7_finance_options_analytics_symbol.py — v2.0 · aplicativo interativo
=======================================================================
Implementação de referência EXECUTÁVEL do endpoint
GET /v7/finance/options/analytics/{symbol} (Yahoo Finance),
agora com interface de terminal em menu, painéis formatados com
cores/barras, retry automático e TODAS as funções da API expostas.

COMO USAR
    python v7_finance_options_analytics_symbol.py            → menu interativo
    python v7_finance_options_analytics_symbol.py AAPL       → consulta única
    python v7_finance_options_analytics_symbol.py AAPL --painel
    python v7_finance_options_analytics_symbol.py AAPL --lista todas
    python v7_finance_options_analytics_symbol.py AAPL --raw
    python v7_finance_options_analytics_symbol.py AAPL --json saida.json
    python v7_finance_options_analytics_symbol.py --comparar AAPL,MSFT,SPY
    python v7_finance_options_analytics_symbol.py AAPL --verifica
    python v7_finance_options_analytics_symbol.py --host query2 AAPL
    Flags: --interativo · --sem-cores · --ascii · --no-pause

O QUE A v2 CORRIGE (a v1 era CLI puro: imprimia e o console fechava)
  * Sem argumentos abre MENU — o console só fecha quando você escolher Sair
  * Erros nunca derrubam o app: caixa de erro legível + dica + ENTER p/ seguir
  * Retry: 401 → renova o par A3+crumb e repete; 429/5xx → backoff exponencial
  * Interface: caixas, barras de composição call/put, tabelas alinhadas,
    datas humanas, números no padrão pt-BR, cores (verde=call/positivo,
    magenta=put, vermelho=erro/negativo, ciano=títulos)

FUNÇÕES DA API EXPOSTAS PELO APP
  1. Consulta canônica (crumb + lang + region — como o app oficial chama)
  2. Comparação multi-símbolo (uma requisição por símbolo — a API não tem lote)
  3. Console de requisição bruta (params extras, método GET/POST/HEAD/OPTIONS,
     headers — incluindo o vetor duplo do crumb via header x-crumb)
  4. Suíte de verificação ao vivo do contrato (22 checagens)
  5. Auditoria de invariantes aritméticas do payload
  6. Gestão da autenticação A3+crumb (status, renovação, testes 401)
  7. Exportação JSON, JSON bruto, configurações e ajuda do contrato

AUTENTICAÇÃO (bootstrap em 2 passos, par atômico)
    1) GET https://fc.yahoo.com                     → 404 esperado, entrega o Cookie A3
    2) GET .../v1/test/getcrumb (Accept: */*, A3)   → crumb casado
    O par renova sempre JUNTO. UA de navegador é obrigatório (UA de
    biblioteca → 429 na edge). Fingerprint TLS não é exigida.

CONTRATO (verificado ao vivo — relatório .md companheiro)
  * Envelope {"optionsAnalytics":{"result":[...],"error":null}}; result[0]
    com exatamente 6 chaves: underlyingSymbol, volumeSummary,
    openInterestSummary, topVolumeContracts, topOpenInterestContracts,
    topVolumeOpenInterestRatioContracts.
  * Símbolo sem cadeia no feed (^GSPC, BTC-USD, EURUSD=X, PETR4.SA,
    inexistente, "AAPL,MSFT") → 200 com result[0] ZERADO ecoando o símbolo.
  * Sem o par A3+crumb → 401 envelope finance "Invalid Crumb".
  * POST/PUT → 405; HEAD → 200 com Content-Length 0; path sem símbolo →
    capturado pela rota-irmã da cadeia ({"optionChain":{...}}).
  * formatted/date/straddle/getAllData/strikeMin/strikeMax e params
    desconhecidos: no-op (comparação de corpo).
  * Unidades: épochs em SEGUNDOS (0 = sentinela); putCall*Ratio e
    impliedVolatility em FRAÇÃO; percentChange em unidades de %.

Autossuficiente: apenas stdlib (urllib + http.cookiejar + json).
Compatível com Python 3.8+. Interface em pt-BR.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from typing import Iterable

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HOSTS = {
    "query1": "https://query1.finance.yahoo.com",
    "query2": "https://query2.finance.yahoo.com",
    "iquery": "https://iquery.finance.yahoo.com",
}
PATH = "/v7/finance/options/analytics"
TIMEOUT = 15.0

CAMPOS_CONTRATO = (
    "contractSymbol", "strike", "currency", "lastPrice", "change",
    "percentChange", "volume", "openInterest", "bid", "ask", "contractSize",
    "expiration", "lastTradeDate", "impliedVolatility", "inTheMoney",
    "volumeOiRatio",
)
CAMPOS_VOLUME_SUMMARY = (
    "putCallVolumeRatio", "callVolume", "putVolume", "totalVolume",
    "lastUpdatedVolumeTimestamp",
)
CAMPOS_OI_SUMMARY = (
    "putCallOiRatio", "callOpenInterest", "putOpenInterest",
    "totalOpenInterest",
)
LISTAS = ("topVolumeContracts", "topOpenInterestContracts",
          "topVolumeOpenInterestRatioContracts")
ROTULOS_LISTAS = {
    "topVolumeContracts": "Top 10 — Volume",
    "topOpenInterestContracts": "Top 10 — Interesse Aberto",
    "topVolumeOpenInterestRatioContracts": "Top 10 — Razão Volume/OI",
}
METRICA_LISTA = {
    "topVolumeContracts": "volume",
    "topOpenInterestContracts": "openInterest",
    "topVolumeOpenInterestRatioContracts": "volumeOiRatio",
}

Resp = namedtuple("Resp", "status corpo headers ms url")

# --------------------------------------------------------------------------- #
# UI — camada de apresentação (cores, caixas, tabelas, prompts)               #
# --------------------------------------------------------------------------- #

_RESET = "\033[0m"
_CODIGOS = {
    "negrito": "\033[1m", "dim": "\033[2m",
    "vermelho": "\033[31m", "verde": "\033[32m", "amarelo": "\033[33m",
    "azul": "\033[34m", "magenta": "\033[35m", "ciano": "\033[36m",
    "branco": "\033[97m",
}
_CORES = True
_ASCII = False
_INTERRUPCOES = 0

_RE_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class SairLoop(Exception):
    """Pedido de saída (opção 0, EOF ou Ctrl+C repetido)."""


def ini_ui(cores: bool = True, ascii_: bool = False) -> None:
    """Prepara o terminal: ANSI no Windows, UTF-8 no stdout/stderr."""
    global _CORES, _ASCII
    _CORES = cores
    _ASCII = ascii_
    if os.name == "nt":
        os.system("")  # ativa sequências ANSI no console moderno do Windows
        try:
            os.system("title Yahoo Finance - Options Analytics")
        except Exception:
            pass
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cor(txt: str, *estilos: str) -> str:
    if not _CORES or not estilos:
        return txt
    ini = "".join(_CODIGOS[e] for e in estilos if e in _CODIGOS)
    return f"{ini}{txt}{_RESET}" if ini else txt


def _cs(nome: str) -> str:
    """Caractere gráfico com fallback ASCII (modo --ascii)."""
    if _ASCII:
        return {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-",
                "v": "|", "blk": "#", "lt": ".", "meio": "*"}[nome]
    return {"tl": "╭", "tr": "╮", "bl": "╰", "br": "╯", "h": "─",
            "v": "│", "blk": "█", "lt": "░", "meio": "·"}[nome]


def _vis(s: str) -> str:
    """Comprimento visível (sem os códigos ANSI)."""
    return _RE_ANSI.sub("", str(s))


def largura_tela() -> int:
    try:
        return shutil.get_terminal_size(fallback=(100, 30)).columns
    except Exception:
        return 100


def secao(titulo: str) -> None:
    pref = _cs("h") * 2 + " " + cor(titulo, "negrito", "ciano") + " "
    resto = max(0, largura_tela() - 1 - len(_vis(pref)))
    print(pref + _cs("h") * resto)


def caixa(linhas: Iterable[str], titulo: str = "") -> str:
    """Devolve o bloco pronto (uma string multi-linha) para impressão."""
    itens = [str(l) for l in linhas]
    w = max([len(_vis(l)) for l in itens] + [len(_vis(titulo)) + 1, 8])
    if titulo:
        t = f" {titulo} "
        topo = _cs("tl") + t + _cs("h") * (w + 2 - len(t)) + _cs("tr")
    else:
        topo = _cs("tl") + _cs("h") * (w + 2) + _cs("tr")
    meio = [_cs("v") + " " + l + " " * (w - len(_vis(l))) + " " + _cs("v")
            for l in itens]
    rod = _cs("bl") + _cs("h") * (w + 2) + _cs("br")
    return "\n".join([topo, *meio, rod])


def _alinh(cel: str, w: int, a: str) -> str:
    d = max(0, w - len(_vis(cel)))
    if a == ">":
        return " " * d + cel
    if a == "^":
        return " " * (d // 2) + cel + " " * (d - d // 2)
    return cel + " " * d


def imprimir_tabela(headers: list, rows: list, aligns: list = None) -> None:
    """Tabela alinhada; células podem conter cores (o padding ignora ANSI)."""
    ncol = len(headers)
    aligns = list(aligns or ["<"] * ncol)
    larg = [len(_vis(str(headers[i]))) for i in range(ncol)]
    for row in rows:
        for i in range(ncol):
            larg[i] = max(larg[i], len(_vis(str(row[i]))))
    cab = "  ".join(cor(_alinh(str(headers[i]), larg[i], aligns[i]),
                        "negrito") for i in range(ncol))
    print(cab)
    print(cor("  ".join(_cs("h") * larg[i] for i in range(ncol)), "dim"))
    for row in rows:
        print("  ".join(_alinh(str(row[i]), larg[i], aligns[i])
                        for i in range(ncol)))


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
    v = bruto.strip()
    if not v:
        if obrigatorio and default is None:
            print(cor("  valor obrigatório — digite algo (Ctrl+C duas vezes sai)",
                      "amarelo"))
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


def escolher(titulo: str, opcoes: list) -> int:
    """Menu numerado; devolve 1..n (0 = voltar/sair)."""
    def desenhar():
        print("\n" + cor(titulo, "negrito", "ciano"))
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
    print("\n" + caixa([str(e) or repr(e)],
                       titulo=cor("ERRO", "negrito")))
    texto = str(e)
    if "401" in texto:
        print(cor("  dica: par A3+crumb inválido — use Autenticação → Renovar o par",
                  "amarelo"))
    elif "429" in texto or "Too Many" in texto:
        print(cor("  dica: rate limit da edge — aguarde alguns segundos e repita",
                  "amarelo"))
    elif "rede" in texto or "timed out" in texto:
        print(cor("  dica: verifique internet/DNS/proxy e o timeout (Configurações)",
                  "amarelo"))


def mascarar(segredo: str | None) -> str:
    if not segredo:
        return "—"
    return f"{segredo[:2]}…({len(segredo)} chars)"


def banner() -> None:
    print("\n" + caixa([
        cor("  YAHOO FINANCE · OPTIONS ANALYTICS", "negrito", "branco"),
        cor("  GET /v7/finance/options/analytics/{symbol}", "ciano"),
        cor("  app de terminal · v2.0 · stdlib pura · Python 3.8+", "dim"),
    ]))
    print(cor("  sem argumentos = menu; a janela só fecha no Sair "
              "(Ctrl+C duas vezes também sai)", "dim"))


def status(est: "Estado") -> None:
    if est.cliente is None:
        auth = cor("sessão não iniciada (inicializa na 1ª consulta)", "amarelo")
        nreq = 0
    else:
        auth = cor(f"crumb ativo {mascarar(est.cliente.crumb)}", "verde")
        nreq = est.cliente.requisicoes
    print(cor(f"  host {est.host} · lang {est.lang} · region {est.region} · "
              f"{auth} · requisições {nreq}", "dim"))


# --------------------------------------------------------------------------- #
# Formatação de números, datas e barras (padrão pt-BR)                        #
# --------------------------------------------------------------------------- #

def fnum(n) -> str:
    """1234567.5 → '1.234.567,50'; inteiro → sem decimais."""
    if not isinstance(n, (int, float)):
        return "—"
    if isinstance(n, float) and n == int(n):
        n = int(n)
    if isinstance(n, int):
        return f"{n:,}".replace(",", ".")
    s = f"{n:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fdec(x, nd: int = 4) -> str:
    """Fração decimal com vírgula: 0.4192 → '0,4192'."""
    if not isinstance(x, (int, float)):
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def fpct(x, nd: int = 2, sinal: bool = False) -> str:
    """Percentual com vírgula: 13.39 → '13,39%' (sinal=True → '+13,39%')."""
    if not isinstance(x, (int, float)):
        return "—"
    s = f"{x:+.{nd}f}" if sinal else f"{x:.{nd}f}"
    return (s + "%").replace(".", ",")


def fepoch(ts, com_hora: bool = True) -> str:
    """Époch SEGUNDOS → data humana local; 0 = sentinela (não é data)."""
    try:
        ts = int(ts or 0)
    except (TypeError, ValueError):
        return "—"
    if ts <= 0:
        return "0 (sentinela)"
    fmt = "%Y-%m-%d %H:%M:%S" if com_hora else "%Y-%m-%d"
    try:
        return time.strftime(fmt, time.localtime(ts))
    except (OverflowError, ValueError):
        return str(ts)


def barra(frac: float, larg: int = 22) -> str:
    frac = min(1.0, max(0.0, float(frac or 0.0)))
    cheio = round(frac * larg)
    return _cs("blk") * cheio + _cs("lt") * (larg - cheio)


def lado_cp(contract_symbol: str) -> str:
    """'C' ou 'P' — 9ª casa do símbolo OCC a partir do fim (§5.4)."""
    try:
        return "C" if contract_symbol[-9].upper() == "C" else "P"
    except IndexError:
        return "?"


# --------------------------------------------------------------------------- #
# Cliente — transporte do GET /v7/finance/options/analytics/{symbol}         #
# --------------------------------------------------------------------------- #

class Cliente:
    """Bootstrap A3+crumb em 2 passos + requisições com retry.

    O crumb viaja como query param em GET (vetor do cliente oficial);
    o header x-crumb é o vetor alternativo aceito pelo servidor.
    """

    def __init__(self, host: str = "query1", timeout: float = TIMEOUT,
                 lang: str = "en-US", region: str = "US") -> None:
        self.base = HOSTS[host]
        self.host_nome = host
        self.timeout = timeout
        self.lang = lang
        self.region = region
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [
            ("User-Agent", UA), ("Accept", "*/*"),
            ("Referer", "https://finance.yahoo.com/")]
        self.crumb: str | None = None
        self.requisicoes = 0
        self.ultimo_resp: Resp | None = None

    # ------------------------------------------------------------------ #
    def bootstrap(self, tentativas: int = 4, pausa: float = 2.0,
                  silencioso: bool = False) -> str:
        """fc.yahoo.com (A3; 404 sem redirect é esperado) → getcrumb."""
        ultimo = ""
        for tent in range(tentativas):
            if not silencioso:
                print(cor(f"  [bootstrap] A3 (fc.yahoo.com) + crumb (getcrumb) "
                          f"— tentativa {tent + 1}/{tentativas}…", "dim"))
            try:
                self.opener.open("https://fc.yahoo.com", timeout=self.timeout)
            except urllib.error.HTTPError:
                pass  # 404 com Set-Cookie A3 — o cookie já está no jar
            except urllib.error.URLError as e:
                if not silencioso:
                    aviso(f"rede: {e.reason} — nova tentativa…")
                time.sleep(pausa)
                continue
            try:
                self.opener.open("https://finance.yahoo.com/",
                                 timeout=self.timeout)
            except urllib.error.URLError:
                pass
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
                time.sleep(pausa)
                continue
            self.requisicoes += 2
            if corpo:
                ultimo = corpo
                break
            time.sleep(pausa)
        if not ultimo:
            raise RuntimeError("bootstrap: getcrumb devolveu vazio "
                               "(rate limit? aguarde alguns segundos e repita)")
        self.crumb = ultimo
        return ultimo

    # ------------------------------------------------------------------ #
    def consultar(self, simbolo: str, params: dict = None, metodo: str = "GET",
                  headers: dict = None, sem_crumb: bool = False) -> Resp:
        """Requisição crua → Resp(status, corpo, headers, ms, url)."""
        params = dict(params or {})
        if self.crumb and metodo == "GET" and not sem_crumb:
            params.setdefault("crumb", self.crumb)
        q = urllib.parse.urlencode(params)
        url = f"{self.base}{PATH}/{urllib.parse.quote(simbolo)}" + (f"?{q}" if q else "")
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
            raise RuntimeError(
                f"falha de rede: {e.reason} (internet? DNS? proxy?)") from e
        ms = (time.perf_counter() - t0) * 1000
        resp = Resp(st, corpo, hdrs, ms, url)
        self.ultimo_resp = resp
        return resp

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse(status: int, corpo: str) -> dict:
        try:
            j = json.loads(corpo)
        except ValueError as e:
            raise RuntimeError(
                f"HTTP {status}: corpo não-JSON {corpo[:120]!r}") from e
        if status != 200:
            fin = j.get("finance") or {}
            err = fin.get("error") or {}
            raise RuntimeError(
                f"HTTP {status} {err.get('code')}: {err.get('description')}")
        if "optionsAnalytics" in j:
            return j
        if "optionChain" in j:
            raise RuntimeError("envelope optionChain: o path perdeu o símbolo "
                               "e a rota-irmã da cadeia capturou a requisição")
        raise RuntimeError(f"envelope inesperado: chaves {sorted(j)}")

    # ------------------------------------------------------------------ #
    def pedido(self, simbolo: str, params: dict = None, metodo: str = "GET",
               headers: dict = None, sem_crumb: bool = False) -> Resp:
        """Executa com retries: 401 → renova o par uma vez; 429/503 → backoff."""
        base_params = dict(params or {})
        r = None
        for tentativa in range(5):
            r = self.consultar(simbolo, base_params, metodo, headers, sem_crumb)
            if r.status == 401 and tentativa == 0:
                aviso("401 Invalid Crumb — renovando o par A3+crumb…")
                self.crumb = None
                self.bootstrap(silencioso=True)
                continue
            if r.status in (429, 503) and tentativa < 4:
                espera = 2 ** tentativa
                aviso(f"HTTP {r.status} — backoff de {espera}s "
                      f"({tentativa + 1}/5)…")
                time.sleep(espera)
                continue
            return r
        return r

    # ------------------------------------------------------------------ #
    def analytics(self, simbolo: str, extra: dict = None) -> dict:
        """Consulta canônica do app: crumb + lang + region, nada mais."""
        params = {"lang": self.lang, "region": self.region}
        params.update(extra or {})
        r = self.pedido(simbolo, params)
        return self._parse(r.status, r.corpo)

    # ------------------------------------------------------------------ #
    def info_auth(self) -> dict:
        return {
            "host": self.host_nome,
            "base": self.base,
            "crumb_mascarado": mascarar(self.crumb),
            "cookies": [c.name for c in self.jar],
            "a3": any(c.name == "A3" for c in self.jar),
            "requisicoes": self.requisicoes,
        }


# --------------------------------------------------------------------------- #
# Exibição — resumo com barras, tabelas top-10, detalhe, comparação          #
# --------------------------------------------------------------------------- #

def _result0(payload: dict) -> dict:
    res = (payload.get("optionsAnalytics") or {}).get("result") or []
    if not res:
        raise RuntimeError("envelope sem result (inesperado neste endpoint)")
    return res[0]


def e_zerado(r0: dict) -> bool:
    """Forma zerada: ativo sem cadeia no feed (eco + zeros + listas vazias)."""
    vs = r0.get("volumeSummary") or {}
    return not (vs.get("totalVolume") or 0) and not (r0.get("topVolumeContracts") or [])


def _bloco_lado(callv, putv, razao, extra: str = "") -> list:
    tot = (callv or 0) + (putv or 0)
    pc = (callv or 0) / tot if tot else 0.0
    pp = (putv or 0) / tot if tot else 0.0
    linhas = []
    for rot, v, corv, frac in (("CALLS", callv, "verde", pc),
                               ("PUTS", putv, "magenta", pp)):
        linhas.append(f"  {rot:<6}{fnum(v):>12}  {cor(barra(frac), corv)}"
                      f"  {fpct(frac * 100, 1):>7}")
    pe = f"  {cor(extra, 'dim')}" if extra else ""
    linhas.append(f"  {'TOTAL':<6}{fnum(tot):>12}   razão P/C "
                  f"{fdec(razao if razao is not None else 0.0)}{pe}")
    return linhas


def exibir_resumo(payload: dict) -> None:
    r0 = _result0(payload)
    vs = r0.get("volumeSummary") or {}
    os_ = r0.get("openInterestSummary") or {}
    linhas = [
        f"{r0.get('underlyingSymbol', '?')} — Options Analytics",
        "",
        cor("VOLUME do dia", "negrito")
        + cor("  (snapshot loteado — dado retardado)", "dim"),
        *_bloco_lado(vs.get("callVolume"), vs.get("putVolume"),
                     vs.get("putCallVolumeRatio"),
                     extra=f"atualizado {fepoch(vs.get('lastUpdatedVolumeTimestamp'))}"),
        "",
        cor("INTERESSE ABERTO", "negrito")
        + cor("  (soma exata da cadeia completa)", "dim"),
        *_bloco_lado(os_.get("callOpenInterest"), os_.get("putOpenInterest"),
                     os_.get("putCallOiRatio")),
    ]
    for k in LISTAS:
        linhas.append(f"  {ROTULOS_LISTAS[k]}: "
                      f"{len(r0.get(k) or [])} contratos")
    if e_zerado(r0):
        linhas += ["",
                   cor("ativo sem cadeia de opções no feed — forma zerada com eco",
                       "amarelo"),
                   cor("(índices, cripto, câmbio, ações BR e símbolos inexistentes "
                       "respondem assim)", "dim")]
    print("\n" + caixa(linhas))


def exibir_tabela_lista(payload: dict, lista: str) -> None:
    r0 = _result0(payload)
    arr = r0.get(lista) or []
    print()
    print(cor(f" {ROTULOS_LISTAS[lista]}", "negrito", "branco"))
    print(cor(f"  ordenado desc. por {METRICA_LISTA[lista]} · contratos do "
              "vencimento do dia (0DTE) não entram nas listas top", "dim"))
    if not arr:
        aviso("lista vazia — ativo sem analytics")
        return
    headers = ["#", "CONTRATO", "C/P", "STRIKE", "ÚLTIMO",
               "VAR%", "VOL", "OI", "V/OI", "IV"]
    aligns = [">", "<", "^", ">", ">", ">", ">", ">", ">", ">"]
    rows = []
    for i, c in enumerate(arr, 1):
        cp = lado_cp(c["contractSymbol"])
        var = c.get("percentChange") or 0.0
        rows.append([
            str(i),
            c["contractSymbol"],
            cor("C", "verde") if cp == "C" else cor("P", "magenta"),
            fdec(c.get("strike"), 2),
            fdec(c.get("lastPrice") or 0.0, 2),
            cor(fpct(var, 2, sinal=True),
                "verde" if var >= 0 else "vermelho"),
            fnum(c.get("volume") or 0),
            fnum(c.get("openInterest") or 0),
            fdec(c.get("volumeOiRatio") or 0.0, 2),
            fpct((c.get("impliedVolatility") or 0.0) * 100, 2),
        ])
    imprimir_tabela(headers, rows, aligns)
    print(cor("  unidades: IV = vol. implícita em % · V/OI = razão sem unidade · "
             "VAR% em %", "dim"))


def detalhar_contrato(c: dict) -> None:
    cp = lado_cp(c["contractSymbol"])
    campos = [
        ("contrato", c["contractSymbol"]),
        ("lado", (cor("CALL", "verde") if cp == "C" else cor("PUT", "magenta"))
         + "  (9ª casa do símbolo OCC)"),
        ("strike", fdec(c.get("strike"), 2)),
        ("moeda", c.get("currency", "—")),
        ("último", fdec(c.get("lastPrice") or 0.0, 2)),
        ("variação", fdec(c.get("change") or 0.0, 2)),
        ("variação %", fpct(c.get("percentChange") or 0.0, 2, sinal=True)),
        ("volume", fnum(c.get("volume") or 0)),
        ("interesse aberto", fnum(c.get("openInterest") or 0)),
        ("melhor compra", fdec(c.get("bid") or 0.0, 2)),
        ("melhor venda", fdec(c.get("ask") or 0.0, 2)),
        ("tamanho", c.get("contractSize", "—")),
        ("vencimento", f"{fepoch(c.get('expiration'), com_hora=False)}"
         f"  (époch {c.get('expiration')})"),
        ("último negócio", f"{fepoch(c.get('lastTradeDate'))}"
         f"  (époch {c.get('lastTradeDate')})"),
        ("vol. implícita", f"{fpct((c.get('impliedVolatility') or 0.0) * 100, 2)}"
         f"  (fração {fdec(c.get('impliedVolatility') or 0.0)})"),
        ("dentro do dinheiro", "sim" if c.get("inTheMoney") else "não"),
        ("razão V/OI", f"{fdec(c.get('volumeOiRatio') or 0.0)}"
         "  (volume ÷ OI — campo exclusivo do analytics)"),
    ]
    linhas = [f"{nome:<20}{valor}" for nome, valor in campos]
    print("\n" + caixa(linhas, titulo="CONTRATO"))


def exibir_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def exibir_painel(payload: dict) -> None:
    exibir_resumo(payload)
    for lista in LISTAS:
        exibir_tabela_lista(payload, lista)


def exibir_comparacao(resultados: list) -> None:
    headers = ["SÍMBOLO", "VOL CALL", "VOL PUT", "VOL TOTAL", "P/C VOL",
               "OI CALL", "OI PUT", "OI TOTAL", "P/C OI"]
    aligns = ["<"] + [">"] * 8
    rows = []
    for simb, r0, err in resultados:
        if err:
            rows.append([simb, cor(f"erro: {err}", "vermelho")] + ["—"] * 7)
            continue
        vs = r0.get("volumeSummary") or {}
        os_ = r0.get("openInterestSummary") or {}
        rows.append([
            r0.get("underlyingSymbol", simb),
            fnum(vs.get("callVolume") or 0),
            fnum(vs.get("putVolume") or 0),
            fnum(vs.get("totalVolume") or 0),
            fdec(vs.get("putCallVolumeRatio") or 0.0),
            fnum(os_.get("callOpenInterest") or 0),
            fnum(os_.get("putOpenInterest") or 0),
            fnum(os_.get("totalOpenInterest") or 0),
            fdec(os_.get("putCallOiRatio") or 0.0),
        ])
    print("\n" + cor(" COMPARAÇÃO — uma requisição por símbolo "
                    "(a API não tem lote)", "negrito", "ciano"))
    imprimir_tabela(headers, rows, aligns)
    print(cor("  nota: zeros = ativo sem cadeia de opções no feed do endpoint "
              "(índices, cripto, câmbio, BR, inexistente)", "dim"))


# --------------------------------------------------------------------------- #
# Estado da sessão interativa + ações do menu                                 #
# --------------------------------------------------------------------------- #

class Estado:
    def __init__(self, host: str = "query1", timeout: float = TIMEOUT,
                 lang: str = "en-US", region: str = "US") -> None:
        self.host = host
        self.timeout = timeout
        self.lang = lang
        self.region = region
        self.cliente: Cliente | None = None
        self.ultimo_payload: dict | None = None
        self.ultimo_simbolo: str | None = None


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


def _mostrar_requisicao(c: Cliente) -> None:
    """Linha dim com a última requisição (crumb mascarado)."""
    r = c.ultimo_resp
    if r is None:
        return
    url = r.url.replace(c.crumb, "…") if c.crumb else r.url
    print(cor(f"  {url} · HTTP {r.status} · {len(r.corpo)} bytes · "
              f"{r.ms:.0f} ms", "dim"))


def salvar_ultimo_json(est: Estado) -> None:
    if not est.ultimo_payload:
        aviso("consulte um símbolo primeiro (opção 1 do menu)")
        return
    eco = (est.ultimo_payload.get("optionsAnalytics", {})
           .get("result", [{}])[0].get("underlyingSymbol", "x"))
    padrao = f"analytics_{eco}.json"
    nome = pedir("Arquivo de saída (JSON indentado)", default=padrao)
    if not nome:
        return
    with open(nome, "w", encoding="utf-8") as fh:
        json.dump(est.ultimo_payload, fh, ensure_ascii=False, indent=2)
    ok(f"payload salvo em {nome} ({os.path.getsize(nome)} bytes)")


def acao_detalhar_contrato(est: Estado) -> None:
    if not est.ultimo_payload:
        aviso("consulte um símbolo primeiro (opção 1 do menu)")
        return
    qual = pedir_int("Lista (1=volume 2=OI 3=razão V/OI)", 1, 3, 1)
    lista = LISTAS[qual - 1]
    arr = _result0(est.ultimo_payload).get(lista) or []
    if not arr:
        aviso("lista vazia — ativo sem analytics")
        return
    idx = pedir_int(f"Contrato (1..{len(arr)})", 1, len(arr), 1)
    detalhar_contrato(arr[idx - 1])


def acao_consultar(est: Estado) -> None:
    simbolo = pedir("Símbolo (ex.: AAPL, NVDA, SPY, BRK-B)", default="AAPL")
    if not simbolo:
        return
    c = obter_cliente(est)
    payload = c.analytics(simbolo)
    est.ultimo_payload = payload
    est.ultimo_simbolo = (_result0(payload)
                          .get("underlyingSymbol", simbolo.upper()))
    print()
    _mostrar_requisicao(c)
    exibir_resumo(payload)
    while True:
        op = escolher("Visões desta consulta", [
            ("Top 10 — Volume", "tabela ordenada por volume"),
            ("Top 10 — Interesse Aberto", "tabela ordenada por OI"),
            ("Top 10 — Razão V/OI", "campo exclusivo do analytics"),
            ("Painel completo", "resumo + as 3 tabelas"),
            ("Detalhar um contrato", "os 16 campos com datas e unidades"),
            ("JSON bruto", "envelope integral indentado"),
            ("Salvar JSON", "corpo em arquivo"),
        ])
        if op == 0:
            return
        if op == 1:
            exibir_tabela_lista(est.ultimo_payload, "topVolumeContracts")
        elif op == 2:
            exibir_tabela_lista(est.ultimo_payload, "topOpenInterestContracts")
        elif op == 3:
            exibir_tabela_lista(est.ultimo_payload,
                                "topVolumeOpenInterestRatioContracts")
        elif op == 4:
            exibir_painel(est.ultimo_payload)
        elif op == 5:
            acao_detalhar_contrato(est)
        elif op == 6:
            print()
            exibir_json(est.ultimo_payload)
        elif op == 7:
            salvar_ultimo_json(est)


def acao_comparar(est: Estado) -> None:
    bruto = pedir("Símbolos separados por vírgula (máx. 8)",
                  default="AAPL,MSFT,SPY,NVDA,TSLA")
    if not bruto:
        return
    simbolos = [s.strip() for s in bruto.split(",") if s.strip()][:8]
    c = obter_cliente(est)
    resultados = []
    for s in simbolos:
        try:
            p = c.analytics(s)
            resultados.append((s, _result0(p), None))
        except Exception as e:  # noqa: BLE001 — uma falha não derruba a tabela
            resultados.append((s, None, str(e)))
        time.sleep(0.6)  # respeita o cache/rate da edge
    exibir_comparacao(resultados)


def acao_console(est: Estado) -> None:
    print(cor("\n CONSOLE DE REQUISIÇÃO — monte e dispare a requisição bruta",
              "negrito", "ciano"))
    print(cor("  (GET canônica; params extras são no-op documentado; POST → 405;",
              "dim"))
    print(cor("   HEAD → 200 sem corpo; OPTIONS → preflight CORS)", "dim"))
    simbolo = pedir("Símbolo no path", default="AAPL")
    if not simbolo:
        return
    opm = escolher("Método", [
        ("GET (canônica)", "crumb no query param"),
        ("POST", "esperado 405 Method Not Allowed"),
        ("HEAD", "esperado 200 com Content-Length 0"),
        ("OPTIONS", "preflight CORS — informe o Origin adiante"),
    ])
    if opm == 0:
        return
    metodo = ["GET", "POST", "HEAD", "OPTIONS"][opm - 1]

    extras = pedir("Params extras k=v (separe com & — vazio = nenhum)",
                   default="") or ""
    params = {"lang": est.lang, "region": est.region}
    for par in extras.replace(";", "&").split("&"):
        if "=" in par:
            k, v = par.split("=", 1)
            params[k.strip()] = v.strip()

    headers = {}
    usar_x_crumb = False
    if metodo == "GET":
        r = pedir("Enviar o crumb via header x-crumb em vez do query param? "
                  "s/n", default="n")
        usar_x_crumb = bool(r) and r.lower().startswith("s")
    if metodo == "OPTIONS":
        headers["Origin"] = pedir("Origin do preflight",
                                   default="https://finance.yahoo.com")
        headers["Access-Control-Request-Method"] = "GET"
    extra_h = pedir("Headers extras 'Nome: valor' (separe com ; — vazio = "
                    "nenhum)", default="") or ""
    for par in extra_h.split(";"):
        if ":" in par:
            k, v = par.split(":", 1)
            headers[k.strip()] = v.strip()

    c = obter_cliente(est)
    if usar_x_crumb:
        headers["x-crumb"] = c.crumb
    elif metodo in ("GET", "HEAD"):
        params.setdefault("crumb", c.crumb)
    r = c.consultar(simbolo, params, metodo, headers or None,
                    sem_crumb=usar_x_crumb)

    print("\n" + caixa([
        f"método ....... {metodo}",
        f"url .......... {r.url.replace(c.crumb, '…') if c.crumb else r.url}",
        f"headers extras {headers or '—'}",
    ], titulo="REQUISIÇÃO"))
    linhas_resp = [
        f"status ....... {r.status}",
        f"tempo ........ {r.ms:.0f} ms",
        f"corpo ........ {len(r.corpo)} bytes",
        "",
    ] + [f"{k}: {v}" for k, v in sorted(r.headers.items())]
    print(caixa(linhas_resp, titulo="RESPOSTA"))

    if r.corpo:
        try:
            j = json.loads(r.corpo)
            txt = json.dumps(j, indent=2, ensure_ascii=False)
            print("\n" + cor(" CORPO (JSON indentado)", "negrito", "ciano"))
            if len(txt) > 6000:
                print(txt[:6000])
                print(cor("… (truncado — use 'salvar corpo' para o arquivo "
                         "integral)", "dim"))
            else:
                print(txt)
        except ValueError:
            print("\n" + cor(" CORPO (texto puro)", "negrito", "ciano"))
            print(r.corpo[:4000])
    else:
        aviso("corpo vazio (HEAD suprime o corpo — Content-Length 0)")
    if pedir("Salvar o corpo em arquivo? s/n", default="n").lower().startswith("s"):
        nome = pedir("Arquivo",
                     default=f"resposta_{metodo.lower()}_{simbolo[:8]}.txt")
        if nome:
            with open(nome, "w", encoding="utf-8") as fh:
                fh.write(r.corpo)
            ok(f"salvo em {nome}")


def acao_verificacao(est: Estado) -> None:
    simbolo = pedir("Símbolo base da suíte", default="AAPL") or "AAPL"
    c = obter_cliente(est)
    verificacao(c, simbolo.upper())


def acao_auditoria(est: Estado) -> None:
    if not est.ultimo_payload:
        aviso("sem payload em memória — consulte um símbolo primeiro (opção 1)")
        return
    audit = auditar_payload(est.ultimo_payload)
    print("\n" + cor(f" AUDITORIA DE INVARIANTES — payload de "
                    f"{est.ultimo_simbolo} (sem rede)", "negrito", "ciano"))
    for nome, passou, detalhe in audit:
        marca = cor("✔ PASS", "verde") if passou else cor("✖ FAIL", "vermelho")
        print(f"  {marca}  {nome}"
              + (cor(f" — {detalhe}", "dim") if detalhe else ""))
    npass = sum(1 for _, p, _ in audit if p)
    print(f"\n  {npass} PASS · {len(audit) - npass} FAIL")


def acao_autenticacao(est: Estado) -> None:
    while True:
        op = escolher("AUTENTICAÇÃO — par atômico Cookie A3 + Crumb", [
            ("Status da sessão", "crumb mascarado, cookies, contadores"),
            ("Renovar o par agora", "bootstrap 2 passos: fc.yahoo.com → getcrumb"),
            ("Teste anônimo (esperado 401)", "sem cookie e sem crumb"),
            ("Teste crumb garbage (esperado 401)", "cookie válido + crumb inválido"),
            ("Teste vetor duplo x-crumb (esperado 200)", "crumb no header em vez do query"),
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
                "fluxo ........... fc.yahoo.com (A3; 404 esperado) → "
                "v1/test/getcrumb",
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
            print(f"\n  status {r.status} · {len(r.corpo)} bytes · "
                  f"{r.corpo[:120]}")
            if r.status == 401 and "Invalid Crumb" in r.corpo:
                ok("401 Invalid Crumb, como esperado sem o par A3+crumb")
            else:
                erro(f"esperado 401 Invalid Crumb, veio {r.status}")
        elif op == 4:
            c = obter_cliente(est)
            r = c.consultar("AAPL", {"lang": est.lang, "region": est.region,
                                     "crumb": "garbage123XYZ"})
            print(f"\n  status {r.status} · {r.corpo[:120]}")
            if r.status == 401 and "Invalid Crumb" in r.corpo:
                ok("401 Invalid Crumb, como esperado com crumb desemparelhado")
            else:
                erro(f"esperado 401 Invalid Crumb, veio {r.status}")
        elif op == 5:
            c = obter_cliente(est)
            r = c.consultar("AAPL", {"lang": est.lang, "region": est.region},
                            headers={"x-crumb": c.crumb}, sem_crumb=True)
            if r.status == 200 and '"optionsAnalytics"' in r.corpo:
                ok("200 com envelope optionsAnalytics — o servidor aceita o "
                   "vetor x-crumb sozinho")
            else:
                erro(f"esperado 200 optionsAnalytics, veio {r.status}: "
                     f"{r.corpo[:120]}")


def _atualizar_cliente(est: Estado) -> None:
    if est.cliente:
        est.cliente.lang = est.lang
        est.cliente.region = est.region


def acao_config(est: Estado) -> None:
    while True:
        op = escolher("CONFIGURAÇÕES", [
            (f"Host: {est.host}",
             "query1 (produção) · query2 (espelho) · iquery (rota interna)"),
            (f"lang: {est.lang} (sem efeito no corpo)",
             "injetado pelo transporte oficial"),
            (f"region: {est.region} (sem efeito no corpo)", "idem"),
            (f"timeout: {est.timeout:g} s", "o cliente oficial usa 15 s"),
            ("cores: ligar/desligar",
             "verde=call · magenta=put · vermelho=erro"),
            ("caracteres: unicode/ascii",
             "se os desenhos saírem estranhos, use ASCII"),
        ])
        if op == 0:
            return
        if op == 1:
            h = escolher("Host", [(k, v) for k, v in HOSTS.items()])
            if h:
                est.host = list(HOSTS)[h - 1]
                est.cliente = None  # nova sessão no novo host
                aviso(f"host mudou para {est.host} — nova sessão na próxima "
                      "consulta")
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
                est.timeout = max(3.0, float(v))
                if est.cliente:
                    est.cliente.timeout = est.timeout
            except ValueError:
                aviso("valor inválido — mantido o anterior")
        elif op == 5:
            global _CORES
            _CORES = not _CORES
            aviso(f"cores {'ligadas' if _CORES else 'desligadas'} "
                  "(--sem-cores na linha de comando também desliga)")
        elif op == 6:
            global _ASCII
            _ASCII = not _ASCII


# --------------------------------------------------------------------------- #
# Ajuda — o que a API oferece (contrato resumido)                             #
# --------------------------------------------------------------------------- #

def acao_ajuda(est: Estado) -> None:
    print()
    secao("O QUE A CONSULTA DEVOLVE")
    print('  envelope: {"optionsAnalytics": {"result": [...], "error": null}}')
    print()
    print("  result[0] — exatamente 6 chaves, sempre:")
    print("    underlyingSymbol ................ símbolo ecoado em caixa alta (aapl → AAPL)")
    print("    volumeSummary ................... callVolume, putVolume, totalVolume,")
    print("                                     putCallVolumeRatio, lastUpdatedVolumeTimestamp")
    print("    openInterestSummary ............ callOpenInterest, putOpenInterest,")
    print("                                     totalOpenInterest, putCallOiRatio")
    print("    topVolumeContracts ............. 10 contratos com maior volume")
    print("    topOpenInterestContracts ....... 10 contratos com maior interesse aberto")
    print("    topVolumeOpenInterestRatioContracts · 10 maiores razões volume/OI")
    print()
    print("  cada contrato tem 16 campos: contractSymbol, strike, currency,")
    print("  lastPrice, change, percentChange, volume, openInterest, bid, ask,")
    print("  contractSize, expiration, lastTradeDate, impliedVolatility,")
    print("  inTheMoney e o exclusivo volumeOiRatio.")
    print()
    secao("O QUE NÃO DEVOLVE (use o endpoint irmão /v7/finance/options/{symbol})")
    print("""  cadeia por strike, cotações do subjacente, lista de vencimentos,
  hasMiniOptions, envelope {raw, fmt} (formatted é no-op aqui).""")
    secao("PARÂMETROS")
    print("""  {symbol} (path) .. obrigatório; sem validação de formato; caixa alta
                  normalizada; SEM LOTE (AAPL,MSFT é um único símbolo)
  crumb (query) . obrigatório — casado com o Cookie A3; vetor duplo:
                  query param OU header x-crumb (em divergência, o query vence)
  lang .......... default en-US (injetado pelo transporte; sem efeito no corpo)
  region ........ default US (idem)
  no-op documentados: formatted, date, straddle, getAllData, strikeMin,
  strikeMax e qualquer parâmetro desconhecido — aceitos e ignorados.""")
    secao("UNIDADES")
    print("""  épochs em SEGUNDOS (lastUpdatedVolumeTimestamp, expiration,
  lastTradeDate); 0 é sentinela, não data.
  putCallVolumeRatio, putCallOiRatio e impliedVolatility em FRAÇÃO decimal.
  percentChange em unidades de % (13.39 = 13,39%).""")
    secao("ERROS")
    print("""  401 Unauthorized / Invalid Crumb .. par A3+crumb ausente ou desemparelhado
  404 Not Found ...................... subpath inexistente (ex.: '..' no path)
  405 Method Not Allowed ............ POST/PUT (endpoint é GET-only)
  429 texto puro 'Edge: Too Many Requests' .. rate limit OU WAF de traversal
  200 com result[0] zerado .......... ativo sem cadeia no feed (^GSPC, cripto,
                                      câmbio, PETR4.SA, símbolo inexistente)
  200 com envelope optionChain ...... path sem símbolo (captura da rota-irmã)""")
    secao("AUTENTICAÇÃO (2 PASSOS, PAR ATÔMICO)")
    print("""  1) GET https://fc.yahoo.com ............ 404 esperado, entrega o Cookie A3
  2) GET .../v1/test/getcrumb (Accept */*) . devolve o crumb casado
  UA de navegador é obrigatório (UA de biblioteca → 429 na edge);
  fingerprint TLS não é exigida.
  hosts: query1 (produção) · query2 (espelho) · iquery (rota interna).""")
    secao("CURIOSIDADES DE COMPORTAMENTO")
    print("""  · O somatório de OI confere com a soma exata da cadeia completa; o de
    volume vem de snapshot loteado e retardado (a UI oficial exibe aviso).
  · Contratos do vencimento do dia (0DTE) não entram nas listas top.
  · impliedVolatility aqui é de lote — difere do irmão da cadeia na 4ª casa.
  · cache de edge: max-age=1 + stale-while-revalidate=9 (não reconsulte em
    rajada; o app já pausa entre requisições).
  · comparação multi-símbolo = N requisições (não existe lote).

  relatório completo: v7_finance_options_analytics_symbol.md (nesta pasta)""")


# --------------------------------------------------------------------------- #
# Auditoria de invariantes (sem rede) sobre um payload                        #
# --------------------------------------------------------------------------- #

def auditar_payload(payload: dict) -> list:
    out = []

    def chk(nome, cond, det=""):
        out.append((nome, bool(cond), det))

    oa = payload.get("optionsAnalytics") or {}
    chk("envelope optionsAnalytics com error null",
        oa.get("error") is None and isinstance(oa.get("result"), list)
        and bool(oa.get("result")))
    if not oa.get("result"):
        return out
    r0 = oa["result"][0]
    chk("result[0] com exatamente as 6 chaves",
        set(r0) == {"underlyingSymbol", "volumeSummary",
                    "openInterestSummary", *LISTAS},
        f"keys={sorted(r0)}")
    vs = r0.get("volumeSummary") or {}
    os_ = r0.get("openInterestSummary") or {}
    if vs.get("callVolume") or vs.get("putVolume"):
        chk("callVolume + putVolume = totalVolume",
            vs.get("callVolume", 0) + vs.get("putVolume", 0)
            == vs.get("totalVolume"))
        if vs.get("callVolume"):
            chk("putCallVolumeRatio = putVolume / callVolume",
                abs(vs["putVolume"] / vs["callVolume"]
                    - vs["putCallVolumeRatio"]) < 1e-6)
    else:
        chk("forma zerada de volume (ativo sem cadeia)", True,
            "sem dados — invariantes triviais")
    if os_.get("callOpenInterest") or os_.get("putOpenInterest"):
        chk("callOI + putOI = totalOpenInterest",
            os_.get("callOpenInterest", 0) + os_.get("putOpenInterest", 0)
            == os_.get("totalOpenInterest"))
        if os_.get("callOpenInterest"):
            chk("putCallOiRatio = putOI / callOI",
                abs(os_["putOpenInterest"] / os_["callOpenInterest"]
                    - os_["putCallOiRatio"]) < 1e-6)
    else:
        chk("forma zerada de OI (ativo sem cadeia)", True,
            "sem dados — invariantes triviais")
    ncontr = 0
    for k in LISTAS:
        arr = r0.get(k) or []
        m = METRICA_LISTA[k]
        ncontr += len(arr)
        if arr:
            chk(f"{k} ordenada desc. por {m}",
                [x.get(m) for x in arr]
                == sorted((x.get(m) for x in arr), reverse=True))
    viol = [x["contractSymbol"] for k in LISTAS for x in (r0.get(k) or [])
            if x.get("openInterest")
            and abs(x["volumeOiRatio"] - x["volume"] / x["openInterest"]) > 1e-6]
    chk("volumeOiRatio = volume / openInterest (por contrato)",
        not viol, f"{ncontr} contratos verificados"
        + (f", violações: {viol[:3]}" if viol else ", nenhuma violação"))
    return out


# --------------------------------------------------------------------------- #
# Suíte de verificação ao vivo (19 checagens da v1 + 3 novas)                 #
# --------------------------------------------------------------------------- #

def verificacao(c: Cliente, simbolo: str = "AAPL") -> bool:
    print(cor(f"\n SUÍTE DE VERIFICAÇÃO AO VIVO — {simbolo}", "negrito", "ciano"))
    print(cor("  cada checagem faz requisição real; pausa curta para não "
             "tomar 429", "dim"))
    resultados = []

    def chk(nome, cond, detalhe=""):
        resultados.append(bool(cond))
        marca = cor("✔ PASS", "verde") if cond else cor("✖ FAIL", "vermelho")
        print(f"  {marca}  {nome}"
              + (cor(f" — {detalhe}", "dim") if detalhe else ""))
        time.sleep(0.9)

    # 1. anônimo → 401 Invalid Crumb
    c2 = Cliente(host=c.host_nome, timeout=c.timeout, lang=c.lang,
                 region=c.region)  # jar limpo
    r = c2.consultar(simbolo, {"lang": c.lang, "region": c.region})
    chk("anônimo → 401 Invalid Crumb",
        r.status == 401 and "Invalid Crumb" in r.corpo, f"status={r.status}")

    # 2. canônica: envelope e chaves
    p = c.analytics(simbolo)
    oa = p.get("optionsAnalytics") or {}
    chk("envelope optionsAnalytics.result + error null",
        oa.get("error") is None and isinstance(oa.get("result"), list))
    r0 = oa["result"][0]
    chk("result[0] com exatamente as 6 chaves",
        set(r0) == {"underlyingSymbol", "volumeSummary",
                    "openInterestSummary", *LISTAS},
        f"keys={sorted(r0)}")
    chk("underlyingSymbol ecoado em caixa alta",
        r0["underlyingSymbol"] == simbolo.upper())

    # 3. summaries
    chk("volumeSummary com as 5 chaves",
        set(r0["volumeSummary"]) == set(CAMPOS_VOLUME_SUMMARY))
    chk("openInterestSummary com as 4 chaves",
        set(r0["openInterestSummary"]) == set(CAMPOS_OI_SUMMARY))

    # 4. listas e contrato
    tv = r0["topVolumeContracts"]
    chk("listas top com 10 contratos",
        all(len(r0[k]) == 10 for k in LISTAS) if tv else True,
        "top-10 por métrica" if tv else "sem contratos")
    if tv:
        chk("contrato tem os 16 campos",
            set(tv[0]) == set(CAMPOS_CONTRATO), f"n={len(tv[0])}")

    # 5. invariantes
    vs, os_ = r0["volumeSummary"], r0["openInterestSummary"]
    chk("callVolume+putVolume=totalVolume",
        vs["callVolume"] + vs["putVolume"] == vs["totalVolume"])
    chk("callOI+putOI=totalOpenInterest",
        os_["callOpenInterest"] + os_["putOpenInterest"]
        == os_["totalOpenInterest"])
    if vs["callVolume"]:
        chk("putCallVolumeRatio=put/call",
            abs(vs["putVolume"] / vs["callVolume"] - vs["putCallVolumeRatio"])
            < 1e-6)
    if os_["callOpenInterest"]:
        chk("putCallOiRatio=put/call",
            abs(os_["putOpenInterest"] / os_["callOpenInterest"]
                - os_["putCallOiRatio"]) < 1e-6)
    if tv:
        chk("volumeOiRatio=volume/openInterest (todas as listas)",
            all(abs(x["volumeOiRatio"] - x["volume"] / x["openInterest"])
                < 1e-6 for k in LISTAS for x in r0[k] if x["openInterest"]))

    # 6. ordenação desc das listas
    if tv:
        ord_ok = all(
            [x[m] for x in r0[k]] == sorted((x[m] for x in r0[k]), reverse=True)
            for k, m in (("topVolumeContracts", "volume"),
                         ("topOpenInterestContracts", "openInterest"),
                         ("topVolumeOpenInterestRatioContracts",
                          "volumeOiRatio")))
        chk("listas ordenadas desc. pela métrica", ord_ok)

    # 7. no-op: params do irmão chain não alteram o corpo
    if tv:
        base_syms = sorted(x["contractSymbol"] for x in tv)
        p2 = c.analytics(simbolo, extra={"formatted": "true", "date": "1",
                                         "straddle": "true",
                                         "getAllData": "true"})
        syms2 = sorted(x["contractSymbol"] for x in
                       p2["optionsAnalytics"]["result"][0]
                       ["topVolumeContracts"])
        chk("formatted/date/straddle/getAllData são no-op", syms2 == base_syms)

    # 8. símbolo sem analytics → result[0] zerado com eco
    pz = c.analytics("NAOEXISTE123")
    rz = pz["optionsAnalytics"]["result"][0]
    chk("símbolo inexistente → zerado com eco",
        rz["underlyingSymbol"] == "NAOEXISTE123"
        and rz["volumeSummary"]["totalVolume"] == 0
        and rz["topVolumeContracts"] == [])

    # 9. case normalizado
    pl = c.analytics(simbolo.lower())
    chk("aapl → AAPL (normalização de case)",
        pl["optionsAnalytics"]["result"][0]["underlyingSymbol"]
        == simbolo.upper())

    # 10. path sem símbolo → envelope da rota-irmã
    c3 = Cliente(host=c.host_nome, timeout=c.timeout, lang=c.lang,
                 region=c.region)
    c3.bootstrap(silencioso=True)
    r3 = c3.consultar("", {"lang": c.lang, "region": c.region,
                           "crumb": c3.crumb})
    chk("path sem símbolo → optionChain (rota-irmã)",
        r3.status == 200 and '"optionChain"' in r3.corpo)

    # 11. POST → 405
    r4 = c.consultar(simbolo, {"lang": c.lang, "region": c.region,
                               "crumb": c.crumb or ""}, metodo="POST")
    chk("POST → 405 Method Not Allowed",
        r4.status == 405 and "Method Not Allowed" in r4.corpo,
        f"status={r4.status}")

    # 12. HEAD → 200 com Content-Length 0
    r5 = c.consultar(simbolo, {"lang": c.lang, "region": c.region,
                               "crumb": c.crumb or ""}, metodo="HEAD")
    cl = r5.headers.get("content-length", "-1")
    chk("HEAD → 200 com Content-Length 0",
        r5.status == 200 and cl == "0", f"CL={cl}")

    # 13. crumb no header x-crumb sozinho → 200
    r6 = c.consultar(simbolo, {"lang": c.lang, "region": c.region},
                     headers={"x-crumb": c.crumb}, sem_crumb=True)
    chk("crumb via header x-crumb (sem query) → 200",
        r6.status == 200 and '"optionsAnalytics"' in r6.corpo,
        f"status={r6.status}")

    # 14. preflight OPTIONS reflete o Origin confiável
    r7 = c.consultar(simbolo, metodo="OPTIONS",
                     headers={"Origin": "https://finance.yahoo.com",
                              "Access-Control-Request-Method": "GET"})
    acao_hdr = r7.headers.get("access-control-allow-origin", "")
    chk("preflight OPTIONS reflete o Origin (ACAO)",
        r7.status == 200 and acao_hdr == "https://finance.yahoo.com",
        f"ACAO={acao_hdr!r}")

    print()
    npass = sum(resultados)
    print(caixa([f"{npass} PASS · {len(resultados) - npass} FAIL"],
                titulo="RESULTADO"))
    return all(resultados)


# --------------------------------------------------------------------------- #
# Menu principal + modos CLI/interativo                                       #
# --------------------------------------------------------------------------- #

MENU_PRINCIPAL = [
    ("Consultar analytics de um símbolo",
     "canônica: crumb + lang + region (resumo com barras)"),
    ("Comparar múltiplos símbolos",
     "uma requisição por símbolo — a API não tem lote"),
    ("Console de requisição bruta",
     "params, método (GET/POST/HEAD/OPTIONS) e headers"),
    ("Suíte de verificação ao vivo",
     "22 checagens do contrato contra o servidor"),
    ("Auditoria de invariantes",
     "aritmética do payload em memória (sem rede)"),
    ("Autenticação A3 + crumb",
     "status, renovação e testes de 401/x-crumb"),
    ("Configurações",
     "host, lang/region, timeout, cores, ascii"),
    ("Ajuda — o que a API oferece",
     "contrato resumido: campos, unidades, erros"),
]


def modo_interativo(est: Estado) -> int:
    banner()
    despacho = {1: acao_consultar, 2: acao_comparar, 3: acao_console,
                4: acao_verificacao, 5: acao_auditoria,
                6: acao_autenticacao, 7: acao_config, 8: acao_ajuda}
    while True:
        print()
        status(est)
        op = escolher("MENU PRINCIPAL", MENU_PRINCIPAL)
        try:
            if op == 0:
                print(cor("\n  até a próxima consulta!", "dim"))
                return 0
            despacho[op](est)
            pausa()
        except SairLoop:
            return 0
        except Exception as e:  # noqa: BLE001 — o app nunca morre no menu
            imprimir_erro(e)
            pausa()


def modo_cli(args) -> int:
    est = Estado(args.host, args.timeout, args.lang, args.region)
    c = obter_cliente(est)
    if args.verifica:
        return 0 if verificacao(c, (args.simbolo or "AAPL").upper()) else 1
    if args.comparar:
        simbolos = [s.strip() for s in args.comparar.split(",") if s.strip()]
        resultados = []
        for s in simbolos:
            try:
                resultados.append((s, _result0(c.analytics(s)), None))
            except Exception as e:  # noqa: BLE001
                resultados.append((s, None, str(e)))
            time.sleep(0.5)
        exibir_comparacao(resultados)
        return 0
    simbolo = args.simbolo or "AAPL"
    payload = c.analytics(simbolo)
    print()
    _mostrar_requisicao(c)
    if args.raw:
        exibir_json(payload)
        return 0
    exibir_resumo(payload)
    mapa = {"volume": "topVolumeContracts",
            "oi": "topOpenInterestContracts",
            "voi": "topVolumeOpenInterestRatioContracts"}
    if args.painel:
        for lista in LISTAS:
            exibir_tabela_lista(payload, lista)
    elif args.lista == "todas":
        for lista in LISTAS:
            exibir_tabela_lista(payload, lista)
    elif args.lista:
        exibir_tabela_lista(payload, mapa[args.lista])
    if args.json_out:
        r = c.consultar(simbolo, {"lang": args.lang, "region": args.region})
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(r.corpo)
        print(cor(f"[fixture] corpo cru salvo em {args.json_out} "
                  f"({len(r.corpo)} bytes)", "dim"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="App interativo + cliente do "
                    "GET /v7/finance/options/analytics/{symbol} (Yahoo "
                    "Finance). Sem argumentos abre o menu; o console só "
                    "fecha no Sair.",
        epilog="exemplos:  %(prog)s AAPL --painel   |   %(prog)s "
               "--comparar AAPL,MSFT,SPY   |   %(prog)s AAPL --verifica")
    ap.add_argument("simbolo", nargs="?", default=None,
                    help="símbolo do ativo (default: abre o menu interativo)")
    ap.add_argument("--interativo", action="store_true",
                    help="força o menu interativo mesmo com outros argumentos")
    ap.add_argument("--lista", choices=["volume", "oi", "voi", "todas"],
                    default=None, help="exibe a tabela de uma das listas top")
    ap.add_argument("--painel", action="store_true",
                    help="resumo + as 3 tabelas top-10")
    ap.add_argument("--raw", action="store_true",
                    help="imprime o envelope JSON indentado")
    ap.add_argument("--verifica", action="store_true",
                    help="suíte de verificação ao vivo do contrato")
    ap.add_argument("--comparar", metavar="S1,S2,...",
                    help="compara múltiplos símbolos (uma requisição cada)")
    ap.add_argument("--host", choices=list(HOSTS), default="query1",
                    help="host do serviço (default: query1)")
    ap.add_argument("--lang", default="en-US",
                    help="query lang do transporte oficial (default: en-US)")
    ap.add_argument("--region", default="US",
                    help="query region do transporte oficial (default: US)")
    ap.add_argument("--timeout", type=float, default=TIMEOUT,
                    help="timeout HTTP em segundos (default: 15)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="salva o corpo cru da consulta em arquivo")
    ap.add_argument("--sem-cores", action="store_true",
                    help="desliga cores e efeitos ANSI")
    ap.add_argument("--ascii", action="store_true",
                    help="caracteres ASCII puros (compatibilidade)")
    ap.add_argument("--no-pause", action="store_true",
                    help="não aguarda ENTER no fim (uso em scripts)")
    args = ap.parse_args(argv)

    ini_ui(cores=not args.sem_cores, ascii_=args.ascii)
    quer_interativo = args.interativo or (
        args.simbolo is None
        and not (args.verifica or args.comparar or args.lista
                 or args.raw or args.painel or args.json_out))
    try:
        if quer_interativo:
            return modo_interativo(
                Estado(args.host, args.timeout, args.lang, args.region))
        return modo_cli(args)
    except KeyboardInterrupt:
        print(cor("\n[interruptado pelo usuário]", "amarelo"))
        return 130
    except Exception as e:  # noqa: BLE001 — última barreira: app não morre
        imprimir_erro(e)
        return 1
    finally:
        if not args.no_pause:
            try:
                input(cor("\nPressione ENTER para fechar...", "dim"))
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    sys.exit(main())
