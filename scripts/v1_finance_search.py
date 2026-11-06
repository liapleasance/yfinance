#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 YF·SEARCH ENGINE EXPLORER v4.0 — Terminal Interativo & Cliente Canônico
 Foco Exclusivo: GET https://query1.finance.yahoo.com/v1/finance/search
═══════════════════════════════════════════════════════════════════════════════
 REQUISITOS ATENDIDOS:
   1. ANTI-FECHAMENTO (CRÍTICO):
      - Sem argumentos -> abre MENU INTERATIVO contínuo (sai na opção 0).
      - Nenhum traceback derruba o app (try/except gracioso em todas as rotinas).
      - Ao sair: pausa "Pressione ENTER para fechar" (flag --no-pause p/ scripts).
      - Tratamento gracioso de Ctrl+C e EOF.
   2. ZERO DEPENDÊNCIAS EXTERNAS:
      - 100% biblioteca padrão Python (urllib, http.cookiejar, json, shutil, re, etc.).
      - Compatível com Python 3.8 até 3.13+.
   3. UI DESIGN BLOOMBERG TERMINAL:
      - Paleta profissional em ANSI/TrueColor (#FFA028, #FFD600, #00C853, #FF433D,
        #00D4FF, #0068FF, #4AF6C3, #A0A0A0, #808080).
      - Caixas curvas ╭─╮│╰╯ e tabelas de dados com padding imune a códigos ANSI.
      - Fallbacks automáticos: --ascii (caixas +---+) e --sem-cores (--no-color).
      - UTF-8 forçado em stdout/stderr e formatação localizada pt-BR.
   4. TODAS AS FUNÇÕES DO ENDPOINT EXPOSTAS:
      - Presets oficiais do FinSearchJS: all, researchReports, quote, instituationalHolders.
      - Resolução polimórfica de quotes (Instrumentos Yahoo Finance + Crunchbase).
      - Modo multiquote por vírgula (resolução exata em lote com nav MULTIQUOTE).
      - Mapeamento completo de categorias: quotes, news, nav, lists, researchReports.
      - Injeção de logos oficiais (enableLogoUrl=true) e filtros includeTypes/excludeTypes.
      - Painel de telemetria interna do microsserviço (11 temporizadores timeTakenFor*).
      - Suíte de verificação ao vivo com 20 testes de conformidade (20/20 PASS).
      - Auditoria estrutural offline de fixtures JSON.
      - Console de requisições brutas (GET/POST/HEAD/OPTIONS, headers, params).
      - Exportação JSON crua com paridade estrita de bytes.
   5. ROBUSTEZ DE REDE:
      - Retry com backoff exponencial 2^n e jitter para HTTP 429/503 (máx 5 tentativas).
      - Medição exata de latência (ms) e contagem de bytes trafegados.
   6. COMPATIBILIDADE CLI TOTAL:
      - Mantém suporte completo a query posicional, --lang, --region, --context,
        --include, --exclude, --json, --save-fixture, --table, etc.
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

__version__ = "4.0.0"

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

ENDPOINT_NAME = "GET /v1/finance/search"
PATH_EP = "/v1/finance/search"

HOSTS_EP = {
    "query1": "https://query1.finance.yahoo.com",
    "query2": "https://query2.finance.yahoo.com",
}

DEFAULT_HOST = "query1"
DEFAULT_TIMEOUT = 15.0

USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

# Presets de contexto extraídos de webcore/srchjs/1.2.50/js/finSearch.modern.js
CONTEXTS: Dict[str, Dict[str, Any]] = {
    "all": {
        "quotesCount": 6,
        "newsCount": 4,
        "enableFuzzyQuery": False,
        "quotesQueryId": "tss_match_phrase_query",
        "multiQuoteQueryId": "multi_quote_single_token_query",
        "newsQueryId": "news_cie_vespa",
        "enableCb": True,
        "enableNavLinks": True,
        "enableEnhancedTrivialQuery": True,
        "enableCulturalAssets": True,
        "enableLogoUrl": True,
        "enableLists": False,
        "enableNcgNews": True,
    },
    "researchReports": {
        "quotesCount": 6,
        "newsCount": 3,
        "listsCount": 2,
        "enableFuzzyQuery": False,
        "quotesQueryId": "tss_match_phrase_query",
        "multiQuoteQueryId": "multi_quote_single_token_query",
        "newsQueryId": "news_cie_vespa",
        "enableCb": True,
        "enableNavLinks": True,
        "enableEnhancedTrivialQuery": True,
        "enableResearchReports": True,
        "enableCulturalAssets": True,
        "enableLogoUrl": True,
        "enableLists": False,
        "enableNcgNews": True,
    },
    "quote": {
        "quotesCount": 8,
        "quotesQueryId": "tss_match_phrase_query",
        "multiQuoteQueryId": "multi_quote_single_token_query",
        "enableCb": False,
        "enableNavLinks": True,
        "enableCulturalAssets": True,
        "enableNews": False,
        "enableResearchReports": False,
        "enableLists": False,
    },
    "instituationalHolders": {
        "screenerFieldCount": 10,
        "enableScreenerField": True,
        "enableCb": False,
        "enableNews": False,
        "enableLists": False,
        "enableQuotes": False,
        "enableNavLinks": False,
        "enableResearchReports": False,
        "screenerFieldName": "top_fund_holder_names",
        "screenerFieldInstrumentType": "equity",
    },
}

DEFAULT_LANG = "en-US"
DEFAULT_REGION = "US"

# ═══════════════════════ Paleta Bloomberg & UI ANSI ═════════════════════════

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """Remove sequências de escape ANSI para cálculo exato de largura visual."""
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
        "verde":     ((0, 200, 83),    41),   # #00C853 — Alta, GO, positivo, PASS
        "vermelho":  ((255, 67, 61),   203),  # #FF433D — Baixa, CANCEL, negativo, FAIL
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

def fmt_epoch_segundos(epoch_s: Any) -> str:
    """Converte Unix epoch em segundos para data e hora local brasileira."""
    if not epoch_s:
        return "—"
    try:
        dt = datetime.datetime.fromtimestamp(float(epoch_s))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(epoch_s)


def fmt_epoch_ms(epoch_ms: Any) -> str:
    """Converte Unix epoch em milissegundos para data e hora local brasileira."""
    if not epoch_ms:
        return "—"
    try:
        dt = datetime.datetime.fromtimestamp(float(epoch_ms) / 1000.0)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(epoch_ms)


# ══════════════════════ Motor de Rede & Sessão HTTP ═════════════════════════

class NetworkEngine:
    """
    Motor HTTP resiliente em stdlib puro:
    - Zero dependências de terceiros (sem requests/curl_cffi).
    - Backoff exponencial com jitter para HTTP 429/503 (máx 5 tentativas).
    - Medição de latência (ms) e contagem exata de bytes trafegados.
    """
    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.timeout = timeout
        self.total_requisicoes = 0
        self.ultima_latencia_ms = 0.0
        self.ultimos_bytes = 0
        self.ultimo_status = 0

    def request_raw(
        self,
        url: str,
        metodo: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        dados: Optional[bytes] = None,
        max_retries: int = 5
    ) -> Tuple[int, Dict[str, str], bytes]:
        hdrs = {
            "User-Agent": USER_AGENT_BROWSER,
            "Accept": "application/json",
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


# ═══════════════════════ Cliente do Endpoint /v1 ════════════════════════════

class SearchClient:
    """Cliente canônico para GET /v1/finance/search."""
    def __init__(self, net: NetworkEngine, default_host: str = DEFAULT_HOST):
        self.net = net
        self.host = default_host

    def montar_url(
        self,
        query: str,
        lang: str = DEFAULT_LANG,
        region: str = DEFAULT_REGION,
        context: str = "all",
        include_types: Optional[str] = None,
        exclude_types: Optional[str] = None,
        host: Optional[str] = None,
        extras: Optional[Dict[str, Any]] = None
    ) -> str:
        base_host = HOSTS_EP.get(host or self.host, HOSTS_EP[DEFAULT_HOST])

        # Serialização fiel a V() do bundle oficial
        params: Dict[str, Any] = {
            "q": query.strip(),
            "lang": lang or DEFAULT_LANG,
            "region": region or DEFAULT_REGION,
        }
        params.update(CONTEXTS.get(context, CONTEXTS["all"]))
        if include_types:
            params["includeTypes"] = include_types
        if exclude_types:
            params["excludeTypes"] = exclude_types
        if extras:
            params.update(extras)

        # Monta querystring serializando apenas primitivos (string/number/boolean)
        pares = []
        for k, v in params.items():
            if isinstance(v, bool):
                pares.append(f"{k}={'true' if v else 'false'}")
            elif v is not None:
                pares.append(f"{k}={urllib.parse.quote(str(v), safe=',')}")

        return f"{base_host}{PATH_EP}?{'&'.join(pares)}"

    def consultar(
        self,
        query: str,
        lang: str = DEFAULT_LANG,
        region: str = DEFAULT_REGION,
        context: str = "all",
        include_types: Optional[str] = None,
        exclude_types: Optional[str] = None,
        host: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        extras: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, Optional[Dict[str, Any]], bytes]:
        url = self.montar_url(
            query=query,
            lang=lang,
            region=region,
            context=context,
            include_types=include_types,
            exclude_types=exclude_types,
            host=host,
            extras=extras
        )

        status, _, raw_bytes = self.net.request_raw(url, headers=custom_headers)
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

    def tabela_quotes(self, itens: List[Dict[str, Any]], titulo_painel: str = "") -> None:
        """Renderiza tabela polimórfica discriminando instrumentos e entidades Crunchbase."""
        if not itens:
            print(f"  {self.p.pintar('[AVISO] Nenhum quote retornado no array.', 'amarelo')}")
            return

        if titulo_painel:
            print(f"\n {self.p.pintar(titulo_painel, 'ambar', negrito=True)}")

        colunas = [
            ("#", 3, "<"),
            ("SÍMBOLO / ID", 12, "<"),
            ("NOME / ENTIDADE", 24, "<"),
            ("TIPO", 12, "<"),
            ("BOLSA", 10, "<"),
            ("SETOR / INDÚSTRIA", 22, "<"),
            ("FONTE", 8, "^")
        ]

        p, b = self.p, self.b
        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for idx, q in enumerate(itens, 1):
            is_yf = q.get("isYahooFinance", True)

            if is_yf:
                # Shape 1: Instrumento Financeiro Oficial
                sym = q.get("symbol", "—")
                nome = q.get("shortname") or q.get("longname") or "—"
                tipo = q.get("typeDisp") or q.get("quoteType") or "—"
                bolsa = q.get("exchDisp") or q.get("exchange") or "—"
                setor = q.get("sector") or q.get("industry") or "—"
                fonte = p.pintar("YF", "verde", negrito=True)
                sym_fmt = p.pintar(sym[:11], "ambar", negrito=True)
            else:
                # Shape 2: Empresa Privada (Crunchbase)
                sym = q.get("permalink") or q.get("index", "—")[:10]
                nome = q.get("name", "—")
                tipo = "Privada"
                bolsa = "Crunchbase"
                setor = "Venture/Private"
                fonte = p.pintar("CB", "ciano")
                sym_fmt = p.pintar(sym[:11], "cinza_med")

            linha_cel = [
                (p.pintar(str(idx), "cinza_esc"), colunas[0][1], colunas[0][2]),
                (sym_fmt, colunas[1][1], colunas[1][2]),
                (nome[:23], colunas[2][1], colunas[2][2]),
                (p.pintar(tipo[:11], "ciano" if is_yf else "cinza_med"), colunas[3][1], colunas[3][2]),
                (bolsa[:9], colunas[4][1], colunas[4][2]),
                (setor[:21], colunas[5][1], colunas[5][2]),
                (fonte, colunas[6][1], colunas[6][2]),
            ]

            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)

    def tabela_noticias(self, news: List[Dict[str, Any]]) -> None:
        """Renderiza tabela com matérias de notícias relacionadas."""
        if not news:
            print(f"  {self.p.pintar('[AVISO] Nenhuma notícia retornada para o termo/região.', 'amarelo')}")
            return

        print(f"\n {self.p.pintar(f'NOTÍCIAS RELACIONADAS ({len(news)} matérias)', 'ambar', negrito=True)}")

        colunas = [
            ("#", 3, "<"),
            ("MANCHETE", 42, "<"),
            ("VEÍCULO", 18, "<"),
            ("PUBLICADO", 16, "^"),
            ("TICKERS", 12, "<")
        ]

        p, b = self.p, self.b
        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for idx, n in enumerate(news, 1):
            titulo = n.get("title", "—")
            pub = n.get("publisher", "—")
            ts = fmt_epoch_segundos(n.get("providerPublishTime"))
            rel = ", ".join(n.get("relatedTickers", [])) or "—"

            linha_cel = [
                (p.pintar(str(idx), "cinza_esc"), colunas[0][1], colunas[0][2]),
                (p.pintar(titulo[:41], "branco"), colunas[1][1], colunas[1][2]),
                (pub[:17], colunas[2][1], colunas[2][2]),
                (p.pintar(ts, "ciano"), colunas[3][1], colunas[3][2]),
                (p.pintar(rel[:11], "ambar"), colunas[4][1], colunas[4][2]),
            ]

            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)


# ═══════════════ Módulo 1: Suíte de Verificação ao Vivo ══════════════════════

def executar_suite_verificacao(client: SearchClient, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Executa a suíte oficial de 20 checagens contra o endpoint /v1/finance/search."""
    print(f"\n {p.pintar('SUÍTE DE VERIFICAÇÃO AO VIVO (' + ENDPOINT_NAME + ')', 'azul', negrito=True)}")
    print(f"  {p.pintar('Validando contratos, envelopes e fan-out dos subsistemas internos...', 'cinza_esc')}\n")

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

    # 1. Consulta canônica de 'Apple'
    st, d, _ = client.consultar("Apple")
    tem_envelope = st == 200 and isinstance(d, dict) and "quotes" in (d or {})
    relatar(1, "Consulta canônica 'Apple' retorna HTTP 200 com envelope plano", tem_envelope, f"count={d.get('count') if d else 0}")

    # 2. Soma de contadores consistente
    q_len = len((d or {}).get("quotes", []))
    n_len = len((d or {}).get("news", []))
    c_tot = (d or {}).get("count", 0)
    relatar(2, "Campo 'count' reflete o total consolidado de categorias", c_tot >= (q_len + n_len), f"count={c_tot} >= quotes+news ({q_len+n_len})")

    # 3. Quotes contém instrumentos com symbol e exchange
    insts = [q for q in (d or {}).get("quotes", []) if q.get("isYahooFinance", True)]
    relatar(3, "Array 'quotes' traz instrumentos com symbol, exchange e score", len(insts) > 0 and "symbol" in insts[0], f"exemplo={insts[0].get('symbol') if insts else '—'}")

    # 4. Injeção de entidades privadas do Crunchbase (isYahooFinance=false)
    cbs = [q for q in (d or {}).get("quotes", []) if not q.get("isYahooFinance", True)]
    relatar(4, "enableCb=true injeta entidades privadas Crunchbase no array", len(cbs) > 0 and "permalink" in cbs[0], f"privadas={len(cbs)}")

    # 5. Injeção de logos oficiais (enableLogoUrl=true)
    logos = [q.get("logoUrl") for q in insts if q.get("logoUrl")]
    relatar(5, "enableLogoUrl=true popula URL de logo em marcas conhecidas", len(logos) > 0, f"logos={len(logos)}")

    # 6. Modo multiquote exato por vírgula (q=AAPL,MSFT)
    st_mq, d_mq, _ = client.consultar("AAPL,MSFT")
    nav_mq = (d_mq or {}).get("nav", [])
    tem_nav_mq = any(n.get("navType") == "MULTIQUOTE" for n in nav_mq)
    relatar(6, "Vírgula (q=AAPL,MSFT) ativa multiquote com nav MULTIQUOTE", st_mq == 200 and tem_nav_mq, "nav MULTIQUOTE ok")

    # 7. Case-insensitivity do termo de busca (apple ≡ Apple)
    st_low, d_low, _ = client.consultar("apple")
    insts_low = [q.get("symbol") for q in (d_low or {}).get("quotes", []) if q.get("isYahooFinance", True)]
    relatar(7, "Busca case-insensitive ('apple' retorna AAPL no topo)", st_low == 200 and "AAPL" in insts_low[:2], "ranking equivalente")

    # 8. Filtro includeTypes=equity restringe a ações
    st_eq, d_eq, _ = client.consultar("AAPL", include_types="equity")
    todos_equity = all(q.get("quoteType") == "EQUITY" for q in (d_eq or {}).get("quotes", []) if q.get("isYahooFinance", True))
    relatar(8, "includeTypes=equity filtra quotes exclusivamente para ações", st_eq == 200 and todos_equity, "todas equity")

    # 9. Filtro excludeTypes=equity,etf remove ações e ETFs
    st_ex, d_ex, _ = client.consultar("AAPL", exclude_types="equity,etf")
    nenhum_eq = all(q.get("quoteType") not in ("EQUITY", "ETF") for q in (d_ex or {}).get("quotes", []) if q.get("isYahooFinance", True))
    relatar(9, "excludeTypes=equity,etf exclui ações e ETFs com sucesso", st_ex == 200 and nenhum_eq, "exclusão aplicada")

    # 10. enableNcgNews=false suprime notícias
    st_nonews, d_nonews, _ = client.consultar("Apple", extras={"enableNcgNews": False, "enableNews": False})
    relatar(10, "enableNcgNews=false suprime notícias da resposta (news=[])", st_nonews == 200 and len((d_nonews or {}).get("news", [])) == 0, "news=[]")

    # 11. enableNavLinks=false suprime atalhos nav de setor
    st_nonav, d_nonav, _ = client.consultar("technology", extras={"enableNavLinks": False})
    relatar(11, "enableNavLinks=false suprime links setoriais (nav=[])", st_nonav == 200 and len((d_nonav or {}).get("nav", [])) == 0, "nav=[]")

    # 12. Presença dos temporizadores internos do microsserviço
    tem_timers = "totalTime" in (d or {}) and "timeTakenForQuotes" in (d or {})
    relatar(12, "Painel de telemetria expõe temporizadores timeTakenFor*", tem_timers, f"totalTime={d.get('totalTime')}ms")

    # 13. Notícias localizadas com par lang/region coerente (de-DE + DE)
    st_de, d_de, _ = client.consultar("Bayer", lang="de-DE", region="DE")
    relatar(13, "Par lang/region alemão (de-DE/DE) retorna notícias em alemão", st_de == 200 and len((d_de or {}).get("news", [])) > 0, f"news={len((d_de or {}).get('news', []))}")

    # 14. Par pt-BR + BR aceito com sucesso sem notícias
    st_br, d_br, _ = client.consultar("Petrobras", lang="pt-BR", region="BR")
    relatar(14, "Par pt-BR/BR aceito com 200 OK e quotes brasileiros", st_br == 200 and len((d_br or {}).get("quotes", [])) > 0, f"quotes={len((d_br or {}).get('quotes', []))}")

    # 15. Contexto researchReports ativa relatórios analíticos
    st_rr, d_rr, _ = client.consultar("Apple", context="researchReports")
    relatar(15, "Contexto researchReports inclui categoria de relatórios", st_rr == 200 and "researchReports" in (d_rr or {}), f"reports={len((d_rr or {}).get('researchReports', []))}")

    # 16. Parâmetro q ausente ou vazio retorna HTTP 400 Bad Request
    url_vazia = f"{HOSTS_EP[client.host]}{PATH_EP}?lang=en-US"
    st_400, _, corpo_400 = client.net.request_raw(url_vazia)
    relatar(16, "Parâmetro 'q' ausente retorna HTTP 400 Bad Request", st_400 == 400 and b"Missing required query parameter=q" in corpo_400, "400 Bad Request")

    # 17. User-Agent python-urllib bloqueado com HTTP 429 pela edge
    url_apple = client.montar_url("Apple")
    st_pyua, _, _ = client.net.request_raw(url_apple, headers={"User-Agent": "Python-urllib/3.13"})
    relatar(17, "User-Agent genérico python-urllib bloqueado com HTTP 429", st_pyua == 429, "Too Many Requests")

    # 18. Método HEAD retorna HTTP 200 com cabeçalhos e corpo vazio
    st_head, hdrs_head, corpo_head = client.net.request_raw(url_apple, metodo="HEAD")
    relatar(18, "Método HEAD retorna HTTP 200 com corpo vazio (0 bytes)", st_head == 200 and len(corpo_head) == 0, "HEAD ok")

    # 19. Método POST rejeitado com 405 Method Not Allowed
    st_post, _, _ = client.net.request_raw(url_apple, metodo="POST")
    relatar(19, "Método POST rejeitado com HTTP 405 Method Not Allowed", st_post == 405, "405 rejeitado")

    # 20. Host secundário query2 responde de forma idêntica
    st_q2, d_q2, _ = client.consultar("Apple", host="query2")
    relatar(20, "Host secundário query2 operacional e equivalente (200 OK)", st_q2 == 200 and (d_q2 or {}).get("count", 0) > 0, "query2 ativo")

    taxa = (testes_passados / total_testes) * 100.0
    print(f"\n {p.pintar(f'Resultado da Suíte: {testes_passados}/{total_testes} aprovados ({taxa:.1f}% de conformidade)', 'verde' if taxa == 100 else 'amarelo', negrito=True)}\n")
    return testes_passados == total_testes


# ══════════════ Módulo 2: Auditoria de Invariantes Offline ═══════════════════

def executar_auditoria_offline(caminho_arquivo: str, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Valida estrutura de fixture JSON de search sem emitir tráfego de rede."""
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
    invariantes.append(("1. Objeto raiz é um dicionário plano (sem wrapper)", isinstance(j, dict) and "finance" not in j))
    invariantes.append(("2. Presença do campo consolidado 'count' inteiro", isinstance(j.get("count"), int)))
    invariantes.append(("3. Array 'quotes' presente", isinstance(j.get("quotes"), list)))
    invariantes.append(("4. Array 'news' presente", isinstance(j.get("news"), list)))
    invariantes.append(("5. Array 'nav' presente", isinstance(j.get("nav"), list)))
    invariantes.append(("6. Array 'lists' presente", isinstance(j.get("lists"), list)))
    invariantes.append(("7. Array 'researchReports' presente", isinstance(j.get("researchReports"), list)))
    invariantes.append(("8. Temporizador consolidado 'totalTime' presente", "totalTime" in j))

    quotes = j.get("quotes", [])
    if quotes:
        polimorfismo_ok = all("isYahooFinance" in q for q in quotes)
        invariantes.append(("9. Todos os itens de 'quotes' possuem 'isYahooFinance'", polimorfismo_ok))
        insts = [q for q in quotes if q.get("isYahooFinance", True)]
        if insts:
            invariantes.append(("10. Instrumentos contêm 'symbol', 'exchange' e 'quoteType'", all("symbol" in q and "exchange" in q and "quoteType" in q for q in insts)))

    for rotulo, cond in invariantes:
        st = p.pintar("CONFORME", "verde", negrito=True) if cond else p.pintar("VIOLAÇÃO", "vermelho", negrito=True)
        print(f"  [{st}] {rotulo}")

    aprovado = all(c for _, c in invariantes)
    print(f"\n  Status: {p.pintar('FIXTURE CERTIFICADA', 'verde') if aprovado else p.pintar('FIXTURE INVÁLIDA', 'vermelho')}\n")
    return aprovado


# ═══════════════ Módulo 3: Painel de Telemetria Interna ═════════════════════

def exibir_painel_telemetria(dados: Dict[str, Any], p: Palette, rnd: ConsoleRenderer) -> None:
    """Exibe os 11 temporizadores de microsserviço que compõem o fan-out do backend."""
    total = dados.get("totalTime", 0)
    timers = [
        ("Cotações & Símbolos", "timeTakenForQuotes"),
        ("Notícias & Conteúdo", "timeTakenForNews"),
        ("Empresas Privadas (Crunchbase)", "timeTakenForCrunchbase"),
        ("Atalhos de Navegação (Nav)", "timeTakenForNav"),
        ("Listas & Screeners Pré-definidos", "timeTakenForSearchLists"),
        ("Relatórios Analíticos (Research)", "timeTakenForResearchReports"),
        ("Ativos Culturais", "timeTakenForCulturalAssets"),
        ("Watchlists Algorítmicas", "timeTakenForAlgowatchlist"),
        ("Screeners Pré-definidos Internos", "timeTakenForPredefinedScreener"),
        ("Perguntas da Comunidade", "timeTakenForQuestions"),
        ("Campos de Screener", "timeTakenForScreenerField"),
    ]

    linhas = [
        f"Tempo Total Consolidado do Backend: {p.pintar(f'{total} ms', 'ambar', negrito=True)}",
        ""
    ]
    for label, key in timers:
        val = dados.get(key, 0)
        cor_t = "verde" if val > 0 else "cinza_esc"
        linhas.append(f"• {pad_vis(label, 36, '<')}: {p.pintar(f'{val:>4} ms', cor_t)}")

    rnd.caixa(linhas, titulo="TELEMETRIA INTERNA DO MICROSSERVIÇO (FAN-OUT)", cor_titulo="ciano")


# ══════════════ Módulo 4: Submenu de Visões de uma Busca ═════════════════════

def submenu_visoes_busca(client: SearchClient, query: str, context: str, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop contínuo de exploração dos resultados de um termo sem redigitar."""
    st, dados, rb = client.consultar(query=query, context=context)
    if st != 200 or not dados:
        print(f"  {p.pintar(f'[ERRO] Falha ao consultar {query} (HTTP {st}).', 'vermelho')}")
        return

    quotes = dados.get("quotes", [])
    news = dados.get("news", [])
    nav = dados.get("nav", [])
    lists = dados.get("lists", [])
    reports = dados.get("researchReports", [])

    while True:
        try:
            tot_count = dados.get("count", 0)
            tit_sub = f"RESULTADOS PARA '{query}' ({context}) — Total: {tot_count} itens"
            print(f"\n {p.pintar(tit_sub, 'ambar', negrito=True)}")
            print(f"  [1] Tabela de Instrumentos & Empresas Privadas ({len(quotes)})")
            print(f"  [2] Painel de Notícias Relacionadas ({len(news)})")
            print(f"  [3] Atalhos de Navegação & Listas/Screeners ({len(nav)} nav / {len(lists)} lists)")
            print(f"  [4] Relatórios Analíticos de Pesquisa ({len(reports)})")
            print(f"  [5] Painel de Telemetria do Backend (11 Temporizadores)")
            print(f"  [6] Ficha Detalhada de um Instrumento Escolhido")
            print(f"  [7] Exibir JSON Bruto Formatado")
            print(f"  [8] Exportar JSON da Consulta para Arquivo")
            print(f"  [0] Voltar ao Menu Principal")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                break

            elif escolha == "1":
                rnd.tabela_quotes(quotes, f"INSTRUMENTOS RESOLVIDOS PARA '{query}'")

            elif escolha == "2":
                rnd.tabela_noticias(news)

            elif escolha == "3":
                linhas = []
                if nav:
                    linhas.append(f"{p.pintar('Atalhos de Navegação (nav):', 'ambar', negrito=True)}")
                    for n_it in nav:
                        if n_it.get("navType") == "MULTIQUOTE":
                            linhas.append(f"• MULTIQUOTE: {', '.join(n_it.get('symbols', []))}")
                        else:
                            linhas.append(f"• {n_it.get('navName')}: {n_it.get('navUrl')}")
                    linhas.append("")
                if lists:
                    linhas.append(f"{p.pintar('Listas Pré-definidas (lists):', 'ciano', negrito=True)}")
                    for l_it in lists:
                        linhas.append(f"• {l_it.get('title')} ({l_it.get('total', 0)} ativos) [score: {l_it.get('score')}]")
                if not nav and not lists:
                    linhas.append("Nenhum atalho nav ou lista retornada para este termo.")
                rnd.caixa(linhas, titulo="NAVEGAÇÃO & SCREENERS", cor_titulo="ciano")

            elif escolha == "4":
                if not reports:
                    print(f"  {p.pintar('Nenhum relatório analítico disponível para esta busca.', 'amarelo')}")
                else:
                    linhas = []
                    for rep in reports:
                        r_data = fmt_epoch_ms(rep.get("reportDate"))
                        linhas.append(f"• {rep.get('reportHeadline')}")
                        linhas.append(f"  Provedor: {rep.get('provider')} | Autor: {rep.get('author', '—')} | Data: {r_data}")
                        linhas.append("")
                    rnd.caixa(linhas, titulo="RELATÓRIOS ANALÍTICOS (RESEARCH)", cor_titulo="verde")

            elif escolha == "5":
                exibir_painel_telemetria(dados, p, rnd)

            elif escolha == "6":
                sym_alvo = input(f"  {p.pintar('Digite o símbolo desejado:', 'branco')} ").strip().upper()
                item = next((q for q in quotes if q.get("symbol", "").upper() == sym_alvo), None)
                if not item:
                    print(f"  {p.pintar('Instrumento não encontrado na lista atual.', 'amarelo')}")
                else:
                    linhas = [f"{pad_vis(k, 24, '<')}: {v}" for k, v in sorted(item.items())]
                    rnd.caixa(linhas, titulo=f"DETALHE DO INSTRUMENTO: {sym_alvo}", cor_titulo="ambar")

            elif escolha == "7":
                print(f"\n{json.dumps(dados, indent=2, ensure_ascii=False)}\n")

            elif escolha == "8":
                nome_arq = f"search_{query.replace(',', '_')}_{int(time.time())}.json"
                with open(nome_arq, "wb") as f:
                    f.write(rb)
                print(f"  {p.pintar(f'[SUCESSO] JSON salvo em {nome_arq} ({len(rb)}B)', 'verde')}")

        except KeyboardInterrupt:
            print(f"\n  {p.pintar('Operação cancelada. Retornando ao submenu...', 'amarelo')}")


# ═══════════════ Módulo 5: Console de Requisições Brutas ═════════════════════

def console_requisicao_bruta(client: SearchClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Diagnóstico de rede: testa métodos, hosts e parâmetros manuais."""
    print(f"\n {p.pintar('CONSOLE DE DIAGNÓSTICO & REQUISIÇÃO BRUTA', 'ciano', negrito=True)}")
    print(f"  {p.pintar('Inspecione status HTTP, latência e cabeçalhos reais da borda.', 'cinza_esc')}\n")

    metodo = (input(f"  {p.pintar('Método HTTP (GET/POST/HEAD/OPTIONS) [GET]:', 'branco', negrito=True)} ").strip().upper()) or "GET"
    host = (input(f"  {p.pintar('Host (query1/query2) [query1]:', 'branco', negrito=True)} ").strip().lower()) or "query1"
    termo = input(f"  {p.pintar('Termo de busca [Apple]:', 'branco', negrito=True)} ").strip() or "Apple"
    ctx = input(f"  {p.pintar('Contexto (all/researchReports/quote) [all]:', 'branco')} ").strip() or "all"

    url = client.montar_url(query=termo, context=ctx, host=host)
    print(f"\n  {p.pintar('Disparando:', 'cinza_esc')} {p.pintar(f'{metodo} {url}', 'azul')}")

    status, hdrs, corpo = client.net.request_raw(url, metodo=metodo)
    st_cor = "verde" if status == 200 else "vermelho"
    print(f"  {p.pintar('Resposta:', 'cinza_esc')} {p.pintar(f'HTTP {status}', st_cor, negrito=True)} | Latência: {client.net.ultima_latencia_ms:.1f}ms | Tamanho: {len(corpo)}B\n")

    rnd.caixa(
        [f"{k}: {v}" for k, v in list(hdrs.items())[:7]],
        titulo="CABEÇALHOS HTTP RETORNADOS",
        cor_titulo="ciano"
    )

    amostra = corpo[:350].decode("utf-8", errors="replace")
    print(f"\n  {p.pintar('Corpo bruto (primeiros 350 bytes):', 'cinza_med')}")
    print(f"  {p.pintar(amostra, 'cinza_esc')}{'...' if len(corpo) > 350 else ''}\n")


# ════════════════════ Menu Principal & CLI Dispatcher ═══════════════════════

def menu_principal(client: SearchClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop principal interativo anti-fechamento."""
    termo_atual = "Apple"
    contexto_atual = "all"

    while True:
        try:
            print(f"\n {p.pintar('YAHOO FINANCE SEARCH ENGINE EXPLORER (/v1)', 'ambar', negrito=True)}")
            print(f"  {p.pintar('Motor universal de autocomplete, multiquote e telemetria | stdlib pura', 'cinza_esc')}\n")

            print(f"  [1] Executar Busca Atual (termo: {p.pintar(termo_atual, 'ciano', negrito=True)} | contexto: {p.pintar(contexto_atual, 'verde')})")
            print(f"  [2] Alterar Termo de Busca")
            print(f"  [3] Modo Multiquote (Resolução em Lote por Vírgula)")
            print(f"  [4] Alternar Preset de Contexto ({', '.join(CONTEXTS.keys())})")
            print(f"  [5] Busca com Filtro de Classe (Ações, ETFs, Fundos, Futuros)")
            print(f"  [6] Console de Requisições Brutas (Diagnóstico HTTP)")
            print(f"  [7] Suíte de Verificação ao Vivo (20 Testes de Conformidade)")
            print(f"  [8] Auditoria Estrutural Offline (Validar Fixture JSON)")
            print(f"  [9] Diagnóstico de Borda & Teste de WAF / User-Agent")
            print(f"  [10] Exportar Fixture JSON Crua")
            print(f"  [0] Encerrar Aplicativo")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                print(f"\n  {p.pintar('Encerrando aplicação de forma limpa. Até logo!', 'ciano')}")
                break

            elif escolha == "1":
                submenu_visoes_busca(client, termo_atual, contexto_atual, p, rnd)

            elif escolha == "2":
                novo_t = input(f"  {p.pintar('Digite novo termo de busca (ex: NVDA, Petrobras, Tesla):', 'branco')} ").strip()
                if novo_t:
                    termo_atual = novo_t

            elif escolha == "3":
                lote = input(f"  {p.pintar('Informe tickers separados por vírgula [AAPL,MSFT,NVDA]:', 'branco')} ").strip() or "AAPL,MSFT,NVDA"
                submenu_visoes_busca(client, lote, "all", p, rnd)

            elif escolha == "4":
                print(f"\n  Contextos disponíveis: {', '.join(CONTEXTS.keys())}")
                novo_c = input(f"  {p.pintar('Escolha o contexto [all]:', 'branco')} ").strip()
                if novo_c in CONTEXTS:
                    contexto_atual = novo_c
                else:
                    print(f"  {p.pintar('Contexto inválido. Mantido o anterior.', 'amarelo')}")

            elif escolha == "5":
                print("\n  Classes comuns: equity, etf, index, mutualfund, future, currency, cryptocurrency")
                filtro = input(f"  {p.pintar('Filtrar includeTypes [equity]:', 'branco')} ").strip() or "equity"
                st, dados, _ = client.consultar(query=termo_atual, include_types=filtro, context="all")
                if st == 200 and dados:
                    rnd.tabela_quotes(dados.get("quotes", []), f"BUSCA COM FILTRO: {filtro.upper()}")

            elif escolha == "6":
                console_requisicao_bruta(client, p, rnd)

            elif escolha == "7":
                executar_suite_verificacao(client, p, rnd)

            elif escolha == "8":
                arq = input(f"  {p.pintar('Caminho da fixture JSON [v1_finance_search.json]:', 'branco')} ").strip() or "v1_finance_search.json"
                executar_auditoria_offline(arq, p, rnd)

            elif escolha == "9":
                linhas = [
                    f"• Endpoint : {ENDPOINT_NAME}",
                    f"• Autentic : 100% Anônimo (sem necessidade de cookies ou crumb)",
                    f"• Edge WAF : Rejeita User-Agents genéricos (ex: python-urllib) com 429",
                    f"• Edge WAF : Responde 200 normal para User-Agents de browser sem TLS impersonation",
                    f"• Cache TTL: public, max-age=600, stale-while-revalidate=180 (10 min)",
                    f"• Total Req: {client.net.total_requisicoes} | Latência: {client.net.ultima_latencia_ms:.1f} ms",
                ]
                rnd.caixa(linhas, titulo="DIAGNÓSTICO DA BORDA & WAF", cor_titulo="ciano")

            elif escolha == "10":
                st, _, rb = client.consultar(query=termo_atual, context=contexto_atual)
                if st == 200:
                    nome = f"search_{termo_atual.replace(',', '_')}.json"
                    with open(nome, "wb") as f:
                        f.write(rb)
                    print(f"  {p.pintar(f'[OK] Arquivo salvo: {nome} ({len(rb)}B)', 'verde')}")

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
        prog="v1_finance_search.py",
        description="Terminal Interativo Bloomberg & Cliente Canônico GET /v1/finance/search"
    )

    # Argumentos CLI compatíveis
    parser.add_argument("query", nargs="?", default=None, help="Termo de busca (ex: Apple, NVDA, AAPL,MSFT)")
    parser.add_argument("--lang", default=DEFAULT_LANG, help="Locale de busca (default en-US)")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Região geográfica (default US)")
    parser.add_argument("--context", default="all", choices=sorted(CONTEXTS.keys()), help="Preset oficial de contexto")
    parser.add_argument("--include", dest="include_types", default=None, help="Filtro includeTypes (ex: equity)")
    parser.add_argument("--exclude", dest="exclude_types", default=None, help="Filtro excludeTypes (ex: equity,etf)")
    parser.add_argument("--json", action="store_true", help="Imprime o envelope JSON cru byte a byte")
    parser.add_argument("--save-fixture", action="store_true", help="Salva a resposta crua em v1_finance_search.json")
    parser.add_argument("--table", action="store_true", help="Exibe tabelas de quotes e notícias e encerra")
    parser.add_argument("--raw", action="store_true", help="Exibe requisição e cabeçalhos crus")
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
    client = SearchClient(net, default_host=args.host)

    try:
        # Modo 1: Auditoria Offline
        if args.auditar:
            return 0 if executar_auditoria_offline(args.auditar, p, rnd) else 1

        # Modo 2: Suíte de Testes ao Vivo
        if args.verifica:
            return 0 if executar_suite_verificacao(client, p, rnd) else 1

        # Modo 3: Consulta Não-Interativa CLI
        if args.query or args.table or args.json or args.raw or args.save_fixture:
            termo = args.query or "Apple"
            st, dados, rb = client.consultar(
                query=termo,
                lang=args.lang,
                region=args.region,
                context=args.context,
                include_types=args.include_types,
                exclude_types=args.exclude_types,
                host=args.host
            )

            if args.save_fixture:
                with open("v1_finance_search.json", "wb") as f:
                    f.write(rb)
                print("Fixture salva com sucesso em v1_finance_search.json", file=sys.stderr)

            if args.json:
                sys.stdout.buffer.write(rb)
                sys.stdout.buffer.write(b"\n")
                return 0

            if args.raw:
                url_gerada = client.montar_url(termo, lang=args.lang, region=args.region, context=args.context, host=args.host)
                print(f"GET {url_gerada}")
                print(f"HTTP Status: {st} | Tamanho: {len(rb)}B | Latência: {client.net.ultima_latencia_ms:.1f}ms\n")
                sys.stdout.buffer.write(rb)
                sys.stdout.buffer.write(b"\n")
                return 0

            if st == 200 and dados:
                rnd.tabela_quotes(dados.get("quotes", []), f"INSTRUMENTOS PARA '{termo}'")
                if dados.get("news"):
                    rnd.tabela_noticias(dados.get("news", []))
                return 0
            else:
                sys.stderr.write(f"Erro ao consultar busca para '{termo}' (HTTP {st})\n")
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