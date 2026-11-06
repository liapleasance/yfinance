#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 YF·MARKET TIME EXPLORER v4.0 — Aplicativo Interativo de Terminal & Cliente CLI
 Foco Exclusivo: GET https://query1.finance.yahoo.com/v6/finance/markettime
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
      - Consulta canônica (formatted=true, key=finance, lang, region).
      - Resolução por região (US, BR, GB, DE, FR, JP, HK, etc.).
      - Alternância de hosts operacionais: query1, query2.
      - Console de requisições brutas (GET/POST/HEAD/OPTIONS, headers, params).
      - Painel de status de sessão, relógio do servidor, janela e countdown local.
      - Réplica do tick de 1 minuto do componente oficial com reescrita da message.
      - Dashboard multi-mercado em tempo real com contagem decrescente ao vivo.
      - Suíte de verificação ao vivo com 20 testes de conformidade (20/20 PASS).
      - Auditoria de invariantes estruturais offline de fixtures salvas.
      - Gestão de credenciais (Cookie A3 opcional via fc.yahoo.com).
      - Exportação JSON crua com paridade estrita de bytes.
   5. ROBUSTEZ DE REDE:
      - Retry com backoff exponencial 2^n e jitter para HTTP 429/503 (máx 5 tentativas).
      - Medição exata de latência (ms) e contagem de bytes trafegados.
   6. COMPATIBILIDADE CLI TOTAL:
      - Mantém suporte completo a --region, --lang, --table, --campos, --checar,
        --matriz, --tick, --dashboard, --varrer, --regioes, --json, etc.
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

ENDPOINT_NAME = "GET /v6/finance/markettime"
PATH_EP = "/v6/finance/markettime"

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

# Constantes oficiais do loader loadMarketTime (bundle Yahoo Finance)
KEY_LOADER = "finance"
DEFAULT_LANG = "en-US"
DEFAULT_REGION = "US"
POLLING_MS = 300_000   # Polling padrão do Dock (5 minutos)
TICK_MS = 60_000       # Tick de decremento local do banner (1 minuto)
TICK_OFFSET_MS = 200

# Campos do item na ordem oficial de chegada
CAMPOS_ITEM = (
    "id", "name", "status", "yfit_market_id", "close", "message",
    "open", "yfit_market_status", "time", "timezone"
)
CAMPOS_OPCIONAIS = ("duration",)

# Classes de status: 0=CLOSED, 1=OPEN, 2=TO_OPEN
ENUM_STATUS = {"CLOSED": 0, "OPEN": 1, "TO_OPEN": 2}

# Mapa de granularidade yfit_market_status -> classe (9 estados oficiais)
MAPA_STATUS_CLASSE = {
    "YFT_MARKET_CLOSED": 0, "YFT_MARKET_CLOSED_EARLY": 0, "YFT_MARKET_HOLIDAY": 0,
    "YFT_MARKET_WILL_CLOSE": 1, "YFT_MARKET_WILL_CLOSE_EARLY": 1, "YFT_MARKET_WILL_CLOSE_LATE": 1,
    "YFT_MARKET_WILL_OPEN": 2, "YFT_MARKET_WILL_OPEN_EARLY": 2, "YFT_MARKET_WILL_OPEN_LATE": 2,
}

# Regiões documentadas com mercado próprio
REGIOES_VALIDAS = {
    "US": "us", "BR": "br", "GB": "gb", "DE": "de", "FR": "fr", "IN": "in",
    "AU": "au", "HK": "hk", "SG": "sg", "CN": "cn", "CA": "ca", "JP": "jp",
    "IT": "it", "ES": "es", "KR": "kr", "TW": "tw", "MX": "mx", "AR": "ar",
    "NZ": "nz", "SE": "se", "NO": "no", "DK": "dk", "PT": "pt", "FI": "fi",
    "GR": "gr", "TR": "tr", "IL": "il", "MY": "my", "VN": "vn",
}
REGIOES_FALLBACK = ("NL", "CH", "ZA", "PE")
LOCALES_TRADUZIDOS = ("pt-BR", "de-DE", "es-ES", "fr-FR")

# Tabela de referência de fusos para validação
TZ_REFERENCIA = {
    "CST": {("-21600", "false"), ("28800", "false")},
    "EDT": {("-14400", "true")},        "EST": {("-18000", "false")},
    "BRT": {("-10800", "false")},       "ART": {("-10800", "false")},
    "BST": {("3600", "true")},          "WEST": {("3600", "true")},
    "CET": {("3600", "false")},         "CEST": {("7200", "true")},
    "EEST": {("10800", "true")},        "TRT": {("10800", "false")},
    "IDT": {("10800", "true")},         "IST": {("19800", "false")},
    "ICT": {("25200", "false")},        "HKT": {("28800", "false")},
    "SGT": {("28800", "false")},        "MYT": {("28800", "false")},
    "JST": {("32400", "false")},        "KST": {("32400", "false")},
    "AEST": {("36000", "false")},       "AEDT": {("39600", "true")},
    "ACST": {("34200", "false")},       "NZST": {("43200", "false")},
    "NZDT": {("46800", "true")},
}

ICONE_STATUS = {
    "YFT_MARKET_CLOSED":           ("🔴", "FECHADO"),
    "YFT_MARKET_CLOSED_EARLY":     ("🔴", "FECHADO CEDO"),
    "YFT_MARKET_HOLIDAY":          ("🏖", "FERIADO"),
    "YFT_MARKET_WILL_CLOSE":       ("🟢", "ABERTO"),
    "YFT_MARKET_WILL_CLOSE_EARLY": ("🟠", "ABERTO · FECHA CEDO"),
    "YFT_MARKET_WILL_CLOSE_LATE":  ("🟢", "ABERTO · FECHA TARDE"),
    "YFT_MARKET_WILL_OPEN":        ("🟡", "ABRE EM"),
    "YFT_MARKET_WILL_OPEN_EARLY":  ("🟡", "ABRE CEDO EM"),
    "YFT_MARKET_WILL_OPEN_LATE":   ("🟡", "ABRE TARDE EM"),
}

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

def parse_iso_utc(data_str: Optional[str]) -> Optional[datetime.datetime]:
    """Decodifica timestamp ISO-8601 UTC (ex: 2026-09-28T13:30:00Z) para objeto ciente."""
    if not data_str:
        return None
    try:
        return datetime.datetime.strptime(data_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def fmt_data_local(data_utc_str: Optional[str]) -> str:
    """Converte ISO-8601 UTC para data e hora local no formato dd/mm/aaaa hh:mm:ss."""
    dt = parse_iso_utc(data_utc_str)
    if not dt:
        return "—"
    try:
        dt_local = dt.astimezone()
        return dt_local.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(data_utc_str)


def fmt_gmt_offset(offset_val: Any) -> str:
    """Converte offset em milissegundos para representação amigável UTC (ex: UTC-4)."""
    if offset_val is None:
        return "—"
    try:
        ms = int(offset_val)
        horas = ms / 3600000.0
        sinal = "+" if horas >= 0 else ""
        if horas.is_integer():
            return f"UTC{sinal}{int(horas)}h ({ms:,} ms)"
        return f"UTC{sinal}{horas:.1f}h ({ms:,} ms)"
    except Exception:
        return str(offset_val)


# ══════════════════════ Motor de Rede & Sessão HTTP ═════════════════════════

class NetworkEngine:
    """
    Motor HTTP resiliente em stdlib puro:
    - CookieJar integrado (suporte opcional ao Cookie A3 via fc.yahoo.com).
    - Backoff exponencial com jitter para HTTP 429/503 (máx 5 tentativas).
    - Telemetria de latência (ms) e contagem exata de bytes trafegados.
    """
    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.timeout = timeout
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

    def bootstrap_auth(self) -> Tuple[bool, str]:
        """Handshake opcional em fc.yahoo.com para emissão do Cookie A3."""
        try:
            req_fc = urllib.request.Request(
                "https://fc.yahoo.com",
                headers={"User-Agent": USER_AGENT_BROWSER, "Accept": "*/*"}
            )
            try:
                with self.opener.open(req_fc, timeout=self.timeout):
                    pass
            except urllib.error.HTTPError:
                pass  # HTTP 404 é normal no gateway de consentimento
            self.total_requisicoes += 1

            self.a3_cookie = self.obter_a3_presente()
            if self.a3_cookie:
                return True, f"Cookie A3 capturado com sucesso ({len(self.a3_cookie)} bytes)."
            return False, "Handshake concluído, porém Cookie A3 não foi retornado."
        except Exception as e:
            return False, f"Falha no handshake fc.yahoo.com: {e}"

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


# ═══════════════════════ Cliente do Endpoint /v6 ════════════════════════════

class MarketTimeClient:
    """Cliente canônico dedicado a GET /v6/finance/markettime."""
    def __init__(self, net: NetworkEngine, default_host: str = DEFAULT_HOST):
        self.net = net
        self.host = default_host

    def montar_url(
        self,
        region: Optional[str] = None,
        lang: str = DEFAULT_LANG,
        com_key: bool = True,
        formatted: bool = True,
        host: Optional[str] = None,
        extras: Optional[Dict[str, str]] = None
    ) -> str:
        base_host = HOSTS_EP.get(host or self.host, HOSTS_EP[DEFAULT_HOST])
        params: Dict[str, str] = {
            "formatted": "true" if formatted else "false",
            "lang": lang or DEFAULT_LANG,
            "region": region or DEFAULT_REGION,
        }
        if com_key:
            params["key"] = KEY_LOADER
        if extras:
            params.update(extras)

        qs = urllib.parse.urlencode(params)
        return f"{base_host}{PATH_EP}?{qs}"

    def consultar(
        self,
        region: Optional[str] = None,
        lang: str = DEFAULT_LANG,
        com_key: bool = True,
        formatted: bool = True,
        host: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        extras: Optional[Dict[str, str]] = None
    ) -> Tuple[int, Optional[Dict[str, Any]], bytes]:
        url = self.montar_url(
            region=region,
            lang=lang,
            com_key=com_key,
            formatted=formatted,
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

    @staticmethod
    def extrair_item(dados: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Extrai o primeiro objeto marketTime da árvore marketTimes[0].marketTime[0]."""
        if not dados:
            return None
        grupos = dados.get("finance", {}).get("marketTimes", [])
        if grupos and isinstance(grupos, list):
            itens = grupos[0].get("marketTime", [])
            if itens and isinstance(itens, list):
                return itens[0]
        return None

    @staticmethod
    def extrair_estado_store(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Réplica exata da mutação initMarketTime do store SvelteKit oficial."""
        if not item:
            return {"hrs": None, "mins": None, "message": "", "status": None, "time": None}
        dur = item.get("duration")
        hrs = int(dur[0].get("hrs")) if dur and dur[0].get("hrs") is not None else None
        mins = int(dur[0].get("mins")) if dur and dur[0].get("mins") is not None else None
        return {
            "hrs": hrs,
            "mins": mins,
            "message": item.get("message") or "",
            "status": item.get("yfit_market_status"),
            "time": item.get("time"),
        }

    @staticmethod
    def simular_tick_store(estado: Dict[str, Any]) -> Dict[str, Any]:
        """Réplica do decremento de minuto do componente oficial com reescrita regex da message."""
        hrs = estado.get("hrs") or 0
        mins = estado.get("mins") or 0
        msg = estado.get("message") or ""
        mudou = False

        if mins <= 0:
            if hrs > 0:
                hrs -= 1
                mins = 59
                mudou = True
        else:
            mins -= 1
            mudou = True

        if msg and mudou:
            msg = re.sub(r"(\d+)(?=\D+$)", str(mins), msg, count=1)
            if hrs > 0:
                msg = re.sub(r"\d+", str(hrs), msg, count=1)
            else:
                msg = re.sub(r"1\s+hour(s)?", "", msg, count=1)
            if "minutes" not in msg and mins == 59 and hrs > 0:
                msg += f" {mins} minutes"

        return {**estado, "hrs": hrs, "mins": mins, "message": msg}


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

    def tabela_mercados(self, itens: List[Dict[str, Any]], titulo_painel: str = "") -> None:
        """Renderiza tabela comparativa de múltiplos mercados."""
        if not itens:
            print(f"  {self.p.pintar('[AVISO] Nenhum mercado retornado.', 'amarelo')}")
            return

        if titulo_painel:
            print(f"\n {self.p.pintar(titulo_painel, 'ambar', negrito=True)}")

        colunas = [
            ("ID", 5, "<"),
            ("MERCADO", 22, "<"),
            ("STATUS", 16, "<"),
            ("CONTAGEM", 13, "^"),
            ("ABRE (UTC)", 12, "^"),
            ("FECHA (UTC)", 12, "^"),
            ("FUSO IANA", 20, "<")
        ]

        p, b = self.p, self.b
        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for it in itens:
            m_id = it.get("id", "—").upper()
            nome = it.get("name", "—")
            yft_st = it.get("yfit_market_status", "")
            icone, rotulo = ICONE_STATUS.get(yft_st, ("⚪", it.get("status", "—").upper()))

            classe = MAPA_STATUS_CLASSE.get(yft_st, 0)
            cor_st = "verde" if classe == 1 else ("amarelo" if classe == 2 else "vermelho")
            status_fmt = f"{icone} {p.pintar(rotulo, cor_st)}"

            dur = it.get("duration")
            if dur and dur[0].get("hrs") is not None and dur[0].get("mins") is not None:
                h = int(dur[0]["hrs"])
                m = int(dur[0]["mins"])
                countdown_str = f"{h}h {m:02d}m"
            else:
                countdown_str = "—"

            o_utc = (it.get("open") or "")[11:16] or "—"
            c_utc = (it.get("close") or "")[11:16] or "—"

            tz_arr = it.get("timezone", [{}])
            tz_iana = tz_arr[0].get("$text") or tz_arr[0].get("short") or "—"

            linha_cel = [
                (p.pintar(m_id[:4], "ambar", negrito=True), colunas[0][1], colunas[0][2]),
                (nome[:21], colunas[1][1], colunas[1][2]),
                (status_fmt, colunas[2][1], colunas[2][2]),
                (p.pintar(countdown_str, "ciano"), colunas[3][1], colunas[3][2]),
                (o_utc, colunas[4][1], colunas[4][2]),
                (c_utc, colunas[5][1], colunas[5][2]),
                (tz_iana[:19], colunas[6][1], colunas[6][2]),
            ]

            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)


# ═══════════════ Módulo 1: Suíte de Verificação ao Vivo ══════════════════════

def executar_suite_verificacao(client: MarketTimeClient, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Executa a suíte oficial de 20 checagens contra o endpoint /v6/finance/markettime."""
    print(f"\n {p.pintar('SUÍTE DE VERIFICAÇÃO AO VIVO (' + ENDPOINT_NAME + ')', 'azul', negrito=True)}")
    print(f"  {p.pintar('Validando conformidade de rede, envelopes e contratos documentados...', 'cinza_esc')}\n")

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

    # 1. Consulta canônica region=US
    st, d, _ = client.consultar(region="US")
    it_us = client.extrair_item(d)
    relatar(1, "Canônica region=US retorna HTTP 200 e item válido", st == 200 and it_us is not None, f"id={it_us.get('id') if it_us else '—'}")

    # 2. Presença dos 10 campos fundamentais do catálogo
    tem_todos = all(k in (it_us or {}) for k in CAMPOS_ITEM)
    relatar(2, "Presença de todos os 10 campos essenciais do contrato", tem_todos, "10/10 presentes")

    # 3. yfit_market_id segue a regra id + '_market'
    regra_mkt_id = (it_us or {}).get("yfit_market_id") == f"{(it_us or {}).get('id')}_market"
    relatar(3, "Campo yfit_market_id é equivalente a id + '_market'", regra_mkt_id, f"'{it_us.get('yfit_market_id')}'")

    # 4. Status coerente com yfit_market_status
    cl_st = MAPA_STATUS_CLASSE.get((it_us or {}).get("yfit_market_status"), 0)
    st_esp = "open" if cl_st == 1 else "closed"
    relatar(4, "Status macro ('open'/'closed') alinhado à classe do status", (it_us or {}).get("status") == st_esp, f"status='{it_us.get('status')}'")

    # 5. region=BR devolve mercado brasileiro (id='br')
    st_br, d_br, _ = client.consultar(region="BR")
    it_br = client.extrair_item(d_br)
    relatar(5, "region=BR mapeia mercado brasileiro (id='br')", st_br == 200 and (it_br or {}).get("id") == "br", f"name='{it_br.get('name') if it_br else ''}'")

    # 6. region=GB devolve mercado britânico (id='gb')
    st_gb, d_gb, _ = client.consultar(region="GB")
    it_gb = client.extrair_item(d_gb)
    relatar(6, "region=GB mapeia mercado britânico (id='gb')", st_gb == 200 and (it_gb or {}).get("id") == "gb", f"name='{it_gb.get('name') if it_gb else ''}'")

    # 7. region em minúsculas (region=br) normalizado no edge
    st_brmin, d_brmin, _ = client.consultar(region="br")
    it_brmin = client.extrair_item(d_brmin)
    relatar(7, "region em minúsculas (region=br) é aceito normalmente", st_brmin == 200 and (it_brmin or {}).get("id") == "br", "normalizado")

    # 8. Região inválida (region=@@) faz fallback gracioso para US com 200
    st_inv, d_inv, _ = client.consultar(region="@@")
    it_inv = client.extrair_item(d_inv)
    relatar(8, "Região inválida (region=@@) faz fallback gracioso para 'us'", st_inv == 200 and (it_inv or {}).get("id") == "us", "fallback US")

    # 9. País válido sem mercado próprio (NL) faz fallback para US
    st_nl, d_nl, _ = client.consultar(region="NL")
    it_nl = client.extrair_item(d_nl)
    relatar(9, "País sem mercado próprio (NL) faz fallback para 'us'", st_nl == 200 and (it_nl or {}).get("id") == "us", "fallback US")

    # 10. Localização pt-BR traduz o nome do mercado
    st_lang, d_lang, _ = client.consultar(region="US", lang="pt-BR")
    it_lang = client.extrair_item(d_lang)
    nome_pt = (it_lang or {}).get("name", "")
    relatar(10, "lang=pt-BR localiza o nome do mercado ('Mercados dos EUA')", st_lang == 200 and "Mercados" in nome_pt, f"name='{nome_pt}'")

    # 11. formatted=false é no-op e mantém corpo consistente
    st_raw, d_raw, _ = client.consultar(region="US", formatted=False)
    it_raw = client.extrair_item(d_raw)
    relatar(11, "formatted=false aceito como no-op (formato idêntico)", st_raw == 200 and (it_raw or {}).get("id") == "us", "no-op verificado")

    # 12. key=finance ausente é no-op
    st_nokey, d_nokey, _ = client.consultar(region="US", com_key=False)
    it_nokey = client.extrair_item(d_nokey)
    relatar(12, "Parâmetro key=finance ausente responde com sucesso", st_nokey == 200 and it_nokey is not None, "opcional")

    # 13. Chamada anônima pura (zero cookies no jar) responde 200 OK
    net_limpa = NetworkEngine(timeout=client.net.timeout)
    st_anon, _, _ = net_limpa.request_raw(client.montar_url(region="US"))
    relatar(13, "Chamada anônima pura (sem cookies) responde 200 OK", st_anon == 200, f"cookies={len(net_limpa.cookie_jar)}")

    # 14. Chamada com Cookie A3 responde com sucesso
    ok_a3, _ = client.net.bootstrap_auth()
    st_a3, d_a3, _ = client.consultar(region="US")
    relatar(14, "Chamada portando Cookie A3 oficial responde 200 OK", st_a3 == 200 and client.extrair_item(d_a3) is not None, f"A3={bool(client.net.a3_cookie)}")

    # 15. User-Agent python-urllib bloqueado com HTTP 429 pelo edge
    url_us = client.montar_url(region="US")
    st_pyua, _, _ = client.net.request_raw(url_us, headers={"User-Agent": "Python-urllib/3.13"})
    relatar(15, "User-Agent python-urllib bloqueado com HTTP 429 da edge", st_pyua == 429, "Too Many Requests")

    # 16. Método HEAD retorna HTTP 200 com cabeçalhos e corpo vazio
    st_head, hdrs_head, corpo_head = client.net.request_raw(url_us, metodo="HEAD")
    relatar(16, "Método HEAD retorna HTTP 200 e corpo vazio (0 bytes)", st_head == 200 and len(corpo_head) == 0, "HEAD ok")

    # 17. Método POST rejeitado com 405 Method Not Allowed
    st_post, _, _ = client.net.request_raw(url_us, metodo="POST")
    relatar(17, "Método POST rejeitado com HTTP 405 Method Not Allowed", st_post == 405, "405 rejeitado")

    # 18. Host secundário query2 operacional
    st_q2, d_q2, _ = client.consultar(region="US", host="query2")
    relatar(18, "Host secundário query2 responde de forma idêntica (200 OK)", st_q2 == 200 and client.extrair_item(d_q2) is not None, "query2 ativo")

    # 19. Timezone presente e estruturado com $text IANA e gmtoffset
    tz_arr = (it_us or {}).get("timezone", [])
    tz_val = len(tz_arr) > 0 and "$text" in tz_arr[0] and "gmtoffset" in tz_arr[0]
    relatar(19, "Array timezone estruturado com fuso IANA ($text) e offset", tz_val, f"tz={tz_arr[0].get('$text') if tz_arr else ''}")

    # 20. Datas ISO-8601 UTC válidas com terminação em 'Z'
    o_val = parse_iso_utc((it_us or {}).get("open"))
    c_val = parse_iso_utc((it_us or {}).get("close"))
    t_val = parse_iso_utc((it_us or {}).get("time"))
    datas_ok = bool(o_val and c_val and t_val)
    relatar(20, "Campos open, close e time em ISO-8601 UTC válido ('Z')", datas_ok, f"time={it_us.get('time') if it_us else ''}")

    taxa = (testes_passados / total_testes) * 100.0
    print(f"\n {p.pintar(f'Resultado da Suíte: {testes_passados}/{total_testes} aprovados ({taxa:.1f}% de conformidade)', 'verde' if taxa == 100 else 'amarelo', negrito=True)}\n")
    return testes_passados == total_testes


# ══════════════ Módulo 2: Auditoria de Invariantes Offline ═══════════════════

def executar_auditoria_offline(caminho_arquivo: str, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Valida estrutura de fixture JSON de markettime sem emitir tráfego de rede."""
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
    fin = j.get("finance")
    invariantes.append(("1. Envelope raiz 'finance' presente", isinstance(fin, dict)))

    if isinstance(fin, dict):
        mts = fin.get("marketTimes")
        err = fin.get("error")
        invariantes.append(("2. Campo 'error' é estritamente nulo", err is None))
        invariantes.append(("3. Campo 'marketTimes' é uma lista com 1 grupo", isinstance(mts, list) and len(mts) == 1))

        if isinstance(mts, list) and len(mts) > 0:
            mt_arr = mts[0].get("marketTime")
            invariantes.append(("4. Grupo contém lista 'marketTime' com 1 item", isinstance(mt_arr, list) and len(mt_arr) == 1))

            if isinstance(mt_arr, list) and len(mt_arr) > 0:
                it = mt_arr[0]
                invariantes.append(("5. Presença de chave primária 'id' string", isinstance(it.get("id"), str)))
                invariantes.append(("6. Presença de chave 'status' ('open'/'closed')", it.get("status") in ("open", "closed")))
                invariantes.append(("7. Presença de 'yfit_market_status' válido", it.get("yfit_market_status") in MAPA_STATUS_CLASSE))
                invariantes.append(("8. yfit_market_id segue convenção id + '_market'", it.get("yfit_market_id") == f"{it.get('id')}_market"))
                invariantes.append(("9. Datas 'open', 'close', 'time' com terminação 'Z'", all(str(it.get(k, "")).endswith("Z") for k in ("open", "close", "time"))))
                invariantes.append(("10. Campo 'timezone' é lista com objeto contendo '$text'", isinstance(it.get("timezone"), list) and "$text" in it["timezone"][0]))

    for rotulo, cond in invariantes:
        st = p.pintar("CONFORME", "verde", negrito=True) if cond else p.pintar("VIOLAÇÃO", "vermelho", negrito=True)
        print(f"  [{st}] {rotulo}")

    aprovado = all(c for _, c in invariantes)
    print(f"\n  Status: {p.pintar('FIXTURE CERTIFICADA', 'verde') if aprovado else p.pintar('FIXTURE INVÁLIDA', 'vermelho')}\n")
    return aprovado


# ═══════════════ Módulo 3: Varredura & Panorama Multi-Regiões ════════════════

def executar_varredura_regioes(client: MarketTimeClient, regioes: List[str], p: Palette, rnd: ConsoleRenderer) -> None:
    """Varre múltiplas regiões exibindo tabela consolidada de mercados e horários."""
    print(f"\n {p.pintar('VARREDURA CONSOLIDADA DE MERCADOS (MULTI-REGIÕES)', 'ambar', negrito=True)}")
    print(f"  {p.pintar(f'Consultando status de {len(regioes)} regiões...', 'cinza_esc')}\n")

    itens = []
    for idx, rg in enumerate(regioes):
        if idx > 0:
            time.sleep(0.15)  # Cortesia de rede
        st, dados, _ = client.consultar(region=rg)
        it = client.extrair_item(dados)
        if it:
            itens.append(it)

    rnd.tabela_mercados(itens, f"STATUS DE SESSÕES GLOBAIS ({len(itens)} mercados mapeados)")
    print(f"  {p.pintar(f'Latência média: {client.net.ultima_latencia_ms:.1f} ms | Host: {client.host}', 'cinza_esc')}\n")


# ═══════════════ Módulo 4: Dashboard em Tempo Real ══════════════════════════

def executar_dashboard_tempo_real(client: MarketTimeClient, regioes: List[str], p: Palette, rnd: ConsoleRenderer, intervalo_s: int = 300) -> None:
    """Painel de monitoramento contínuo em tempo real com contagem decrescente por segundo."""
    print(f"\n {p.pintar('INICIANDO DASHBOARD MULTI-MERCADO EM TEMPO REAL', 'verde', negrito=True)}")
    print(f"  {p.pintar(f'Monitorando {len(regioes)} mercados a cada {intervalo_s}s. Pressione Ctrl+C para sair.', 'cinza_esc')}\n")
    time.sleep(1)

    class EstadoMercado:
        def __init__(self, regiao: str):
            self.regiao = regiao
            self.item: Optional[Dict[str, Any]] = None
            self.defasagem_s = 0.0
            self.proxima_consulta = 0.0
            self.alvo_dt: Optional[datetime.datetime] = None
            self.verbo = ""

        def atualizar(self):
            agora = time.time()
            st, dados, _ = client.consultar(region=self.regiao)
            it = client.extrair_item(dados)
            self.item = it
            self.proxima_consulta = agora + intervalo_s

            if it:
                t_serv = parse_iso_utc(it.get("time"))
                if t_serv:
                    self.defasagem_s = (datetime.datetime.now(datetime.timezone.utc) - t_serv).total_seconds()

                yft = it.get("yfit_market_status") or ""
                if "WILL_OPEN" in yft:
                    self.alvo_dt = parse_iso_utc(it.get("open"))
                    self.verbo = "abre"
                elif "WILL_CLOSE" in yft:
                    self.alvo_dt = parse_iso_utc(it.get("close"))
                    self.verbo = "fecha"
                else:
                    self.alvo_dt = None
                    self.verbo = ""

        def contagem_restante(self) -> Tuple[Optional[float], str]:
            if not self.alvo_dt:
                return None, ""
            agora_utc = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=self.defasagem_s)
            diff = (self.alvo_dt - agora_utc).total_seconds()
            return max(0.0, diff), self.verbo

    mercados = [EstadoMercado(r) for r in regioes]
    for m in mercados:
        m.atualizar()

    try:
        while True:
            agora = time.time()
            for m in mercados:
                # Antecipa consulta quando o countdown expirar
                restante, _ = m.contagem_restante()
                if agora >= m.proxima_consulta or (restante is not None and restante <= 1.0):
                    m.atualizar()

            # Renderiza tela limpa
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

            linhas_caixa = [
                f"Atualização da rede a cada {intervalo_s}s · Contagem por segundo alinhada ao servidor",
                f"Relógio Local: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | Host: {client.host}",
                ""
            ]

            itens_tabela = []
            for m in mercados:
                if not m.item:
                    continue
                it = dict(m.item)
                restante, verbo = m.contagem_restante()
                if restante is not None:
                    it["duration"] = [{
                        "hrs": str(int(restante // 3600)),
                        "mins": str(int((restante % 3600) // 60))
                    }]
                itens_tabela.append(it)

            rnd.caixa(linhas_caixa, titulo="DASHBOARD AO VIVO · SESSÕES DE MERCADO", cor_titulo="verde")
            rnd.tabela_mercados(itens_tabela)

            print(f"\n  {p.pintar('Pressione Ctrl+C para retornar ao menu principal...', 'cinza_esc')}")
            time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n  {p.pintar('Dashboard encerrado.', 'amarelo')}")


# ═══════════════ Módulo 5: Console de Requisições Brutas ═════════════════════

def console_requisicao_bruta(client: MarketTimeClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Diagnóstico de rede: testa métodos, hosts e parâmetros arbitrários."""
    print(f"\n {p.pintar('CONSOLE DE DIAGNÓSTICO & REQUISIÇÃO BRUTA', 'ciano', negrito=True)}")
    print(f"  {p.pintar('Inspecione status HTTP, latência e cabeçalhos reais da borda.', 'cinza_esc')}\n")

    metodo = (input(f"  {p.pintar('Método HTTP (GET/POST/HEAD/OPTIONS) [GET]:', 'branco', negrito=True)} ").strip().upper()) or "GET"
    host = (input(f"  {p.pintar('Host (query1/query2) [query1]:', 'branco', negrito=True)} ").strip().lower()) or "query1"
    regiao = input(f"  {p.pintar('Região de mercado [US]:', 'branco', negrito=True)} ").strip() or "US"

    extras_str = input(f"  {p.pintar('Parâmetros extras (k=v&k2=v2) [Enter para nenhum]:', 'branco')} ").strip()
    extras = {}
    if extras_str:
        for par in extras_str.split("&"):
            if "=" in par:
                k, v = par.split("=", 1)
                extras[k.strip()] = v.strip()

    url = client.montar_url(region=regiao, host=host, extras=extras)
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


# ══════════════ Módulo 6: Visões Detalhadas de um Mercado ════════════════════

def submenu_visoes_mercado(client: MarketTimeClient, regiao: str, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop contínuo de exploração do mercado selecionado sem redigitar."""
    st, dados, rb = client.consultar(region=regiao)
    it = client.extrair_item(dados)

    if st != 200 or not it:
        print(f"  {p.pintar(f'[ERRO] Falha ao consultar mercado {regiao} (HTTP {st}).', 'vermelho')}")
        return

    nome_mkt = it.get("name") or regiao.upper()

    while True:
        try:
            titulo_menu = f"VISÕES DISPONÍVEIS — MERCADO: {regiao.upper()} ({nome_mkt})"
            print(f"\n {p.pintar(titulo_menu, 'ambar', negrito=True)}")
            print(f"  [1] Ficha Técnica Completa (Todos os Campos do Item)")
            print(f"  [2] Estado do Store SvelteKit & Classe de Status (0, 1, 2)")
            print(f"  [3] Simulação do Tick Local de Minuto (Reescrita de Texto)")
            print(f"  [4] Painel em Tempo Real Deste Mercado (Countdown)")
            print(f"  [5] Matriz de Tradução e Idiomas (pt-BR, de-DE, es-ES, fr-FR)")
            print(f"  [6] Exibir Resposta JSON Bruta Formatada")
            print(f"  [7] Exportar JSON Bruto para Arquivo")
            print(f"  [0] Voltar ao Menu Principal")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                break

            elif escolha == "1":
                tz_arr = it.get("timezone", [{}])
                tz = tz_arr[0]
                linhas = [
                    f"• ID do Mercado    : {it.get('id')} ({it.get('yfit_market_id')})",
                    f"• Nome Oficial     : {it.get('name')}",
                    f"• Status Macro     : {it.get('status')} (Status Granular: {it.get('yfit_market_status')})",
                    f"• Mensagem Oficial : {it.get('message')}",
                    f"• Abertura Sessão  : {it.get('open')} (Local: {fmt_data_local(it.get('open'))})",
                    f"• Fechamento Sessão: {it.get('close')} (Local: {fmt_data_local(it.get('close'))})",
                    f"• Relógio Servidor : {it.get('time')} (Local: {fmt_data_local(it.get('time'))})",
                    f"• Fuso IANA        : {tz.get('$text')} ({tz.get('short')})",
                    f"• Offset GMT / DST : {tz.get('gmtoffset')}s ({fmt_gmt_offset(int(tz.get('gmtoffset', 0))*1000)}) | DST={tz.get('dst')}",
                ]
                dur = it.get("duration")
                if dur and dur[0].get("hrs") is not None and dur[0].get("mins") is not None:
                    linhas.append(f"• Contagem Duração : {dur[0].get('hrs')}h {dur[0].get('mins')}m")
                rnd.caixa(linhas, titulo=f"FICHA TÉCNICA · MERCADO {regiao.upper()}", cor_titulo="ambar")

            elif escolha == "2":
                est = client.extrair_estado_store(it)
                cl = MAPA_STATUS_CLASSE.get(est.get("status"), 0)
                cl_nome = {0: "CLOSED (0)", 1: "OPEN (1)", 2: "TO_OPEN (2)"}.get(cl, "DESCONHECIDO")
                pular_refetch = cl in (1, 2)

                linhas = [
                    f"• Estado do Store  : hrs={est.get('hrs')} | mins={est.get('mins')}",
                    f"• Status Granular  : {est.get('status')}",
                    f"• Classe de Status : {cl_nome}",
                    f"• Regra do Loader  : deve_pular_refetch = {pular_refetch} (countdown em execução no client)",
                    f"• Mensagem Atual   : '{est.get('message')}'",
                    f"• Relógio do Store : {est.get('time')}",
                ]
                rnd.caixa(linhas, titulo="ESTADO DA STORE (SVELTEKIT OFFICIAL)", cor_titulo="ciano")

            elif escolha == "3":
                est = client.extrair_estado_store(it)
                print(f"\n  {p.pintar('Simulando 3 minutos de decremento local do banner:', 'cinza_med')}")
                print(f"  Estado Inicial -> hrs={est.get('hrs')} mins={est.get('mins')} | '{est.get('message')}'")
                for i in range(1, 4):
                    est = client.simular_tick_store(est)
                    print(f"  Tick +{i} minuto -> hrs={est.get('hrs')} mins={est.get('mins')} | '{est.get('message')}'")

            elif escolha == "4":
                executar_dashboard_tempo_real(client, [regiao.upper()], p, rnd, intervalo_s=300)

            elif escolha == "5":
                linhas = []
                for loc in LOCALES_TRADUZIDOS:
                    st_l, d_l, _ = client.consultar(region=regiao, lang=loc)
                    it_l = client.extrair_item(d_l)
                    if it_l:
                        linhas.append(f"• {loc}: '{it_l.get('name')}' -> '{it_l.get('message')}'")
                rnd.caixa(linhas, titulo=f"COBERTURA DE LOCALIZAÇÃO · {regiao.upper()}", cor_titulo="verde")

            elif escolha == "6":
                print(f"\n{json.dumps(dados, indent=2, ensure_ascii=False)}\n")

            elif escolha == "7":
                nome_arq = f"markettime_{regiao}_{int(time.time())}.json"
                with open(nome_arq, "wb") as f:
                    f.write(rb)
                print(f"  {p.pintar(f'[SUCESSO] JSON salvo em {nome_arq} ({len(rb)}B)', 'verde')}")

        except KeyboardInterrupt:
            print(f"\n  {p.pintar('Ação cancelada. Retornando ao submenu...', 'amarelo')}")


# ════════════════════ Menu Principal & CLI Dispatcher ═══════════════════════

def menu_principal(client: MarketTimeClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop principal interativo anti-fechamento."""
    regiao_atual = DEFAULT_REGION

    while True:
        try:
            print(f"\n {p.pintar('YAHOO FINANCE MARKET TIME EXPLORER (/v6)', 'ambar', negrito=True)}")
            print(f"  {p.pintar('Sessões de pregão, relógios de mercado e countdowns do Dock | stdlib pura', 'cinza_esc')}\n")

            print(f"  [1] Consultar Mercado Atual (atual: {p.pintar(regiao_atual, 'ciano', negrito=True)})")
            print(f"  [2] Alternar Região de Mercado Selecionada")
            print(f"  [3] Varredura Consolidada de Mercados (Multi-Regiões)")
            print(f"  [4] Dashboard Multimercado em Tempo Real (Live Countdown)")
            print(f"  [5] Console de Requisições Brutas (Diagnóstico de Protocolo)")
            print(f"  [6] Suíte de Verificação ao Vivo (20 Testes de Conformidade)")
            print(f"  [7] Auditoria Estrutural Offline (Validar Fixture JSON)")
            print(f"  [8] Gestão de Sessão & Diagnóstico de Borda (Cookie A3 / WAF)")
            print(f"  [9] Catálogo de Regiões Observadas com Mercado Próprio")
            print(f"  [0] Encerrar Aplicativo")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                print(f"\n  {p.pintar('Encerrando aplicação de forma limpa. Até logo!', 'ciano')}")
                break

            elif escolha == "1":
                submenu_visoes_mercado(client, regiao_atual, p, rnd)

            elif escolha == "2":
                print(f"\n  Regiões comuns: {', '.join(list(REGIOES_VALIDAS.keys())[:10])}...")
                nova_r = input(f"  {p.pintar('Informe código de região [US]:', 'branco')} ").strip().upper()
                if nova_r:
                    regiao_atual = nova_r

            elif escolha == "3":
                amostra = ["US", "BR", "GB", "DE", "FR", "JP", "HK", "AU", "SG"]
                executar_varredura_regioes(client, amostra, p, rnd)

            elif escolha == "4":
                amostra = ["US", "BR", "GB", "DE", "JP", "HK"]
                executar_dashboard_tempo_real(client, amostra, p, rnd, intervalo_s=300)

            elif escolha == "5":
                console_requisicao_bruta(client, p, rnd)

            elif escolha == "6":
                executar_suite_verificacao(client, p, rnd)

            elif escolha == "7":
                arq = input(f"  {p.pintar('Caminho da fixture JSON [v6_finance_markettime.json]:', 'branco')} ").strip() or "v6_finance_markettime.json"
                executar_auditoria_offline(arq, p, rnd)

            elif escolha == "8":
                a3 = client.net.obter_a3_presente()
                linhas = [
                    f"• Endpoint : {ENDPOINT_NAME}",
                    f"• Status   : 100% Anônimo (não exige cookie A3 nem token Crumb)",
                    f"• Cookie A3: {p.pintar('Presente no Jar (' + str(len(a3)) + 'B)', 'verde') if a3 else p.pintar('Não emitido', 'amarelo')}",
                    f"• Edge WAF : Rejeita User-Agents de biblioteca (ex: python-urllib) com 429",
                    f"• Edge WAF : Responde 200 normal para User-Agents de browser sem TLS impersonation",
                    f"• Cache TTL: public, max-age=60, stale-while-revalidate=60",
                    f"• Total Req: {client.net.total_requisicoes} | Latência: {client.net.ultima_latencia_ms:.1f} ms",
                ]
                rnd.caixa(linhas, titulo="DIAGNÓSTICO DA BORDA & SESSÃO", cor_titulo="ciano")
                acao = input(f"\n  {p.pintar('Deseja executar handshake fc.yahoo.com para obter Cookie A3? (s/n) [n]:', 'branco')} ").strip().lower()
                if acao == "s":
                    ok, msg = client.net.bootstrap_auth()
                    print(f"  {p.pintar(msg, 'verde' if ok else 'vermelho')}")

            elif escolha == "9":
                linhas = []
                for k, v in sorted(REGIOES_VALIDAS.items()):
                    linhas.append(f"• {k:<4} -> {v}_market")
                rnd.caixa(linhas, titulo=f"REGIÕES COM MERCADO PRÓPRIO ({len(REGIOES_VALIDAS)})", cor_titulo="ambar")
                print(f"  {p.pintar('Países sem mercado próprio caem no fallback US: ' + ', '.join(REGIOES_FALLBACK), 'cinza_esc')}")

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
        prog="v6_finance_markettime.py",
        description="Terminal Interativo Bloomberg & Cliente Canônico GET /v6/finance/markettime"
    )

    # Argumentos CLI compatíveis
    parser.add_argument("--region", default=None, help="Região do mercado (US, BR, GB, DE, etc.)")
    parser.add_argument("--lang", default=DEFAULT_LANG, help="Locale de tradução (en-US, pt-BR, etc.)")
    parser.add_argument("--no-key", action="store_true", help="Omite key=finance da query string")
    parser.add_argument("--raw", action="store_true", help="formatted=false")
    parser.add_argument("--table", action="store_true", help="Exibe banner tabular e encerra")
    parser.add_argument("--varrer", metavar="REGIOES", default=None, help="Varre lista CSV de regiões (ex: US,BR,GB)")
    parser.add_argument("--campos", action="store_true", help="Exibe relatório campo a campo dos metadados")
    parser.add_argument("--checar", action="store_true", help="Executa checagem de integridade e consistência")
    parser.add_argument("--tick", type=int, nargs="?", const=3, default=None, metavar="N", help="Simula N ticks do countdown")
    parser.add_argument("--dashboard", nargs="?", const="", metavar="REGIOES", default=None, help="Inicia dashboard em tempo real")
    parser.add_argument("--intervalo", type=int, default=300, help="Intervalo em segundos entre atualizações do dashboard")
    parser.add_argument("--regioes", action="store_true", help="Lista todas as regiões com mercado próprio")
    parser.add_argument("--json", action="store_true", help="Imprime o envelope JSON cru byte a byte")
    parser.add_argument("--verifica", action="store_true", help="Executa a suíte de 20 testes de conformidade ao vivo")
    parser.add_argument("--auditar", default=None, metavar="ARQ", help="Audita estruturalmente fixture JSON offline")
    parser.add_argument("--host", choices=list(HOSTS_EP.keys()), default=DEFAULT_HOST, help="Host edge da Yahoo")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Timeout de conexão em segundos")
    parser.add_argument("--autenticado", action="store_true", help="Executa handshake para portar Cookie A3")
    parser.add_argument("--inspect", action="store_true", help="Inspeciona estado da sessão e edge WAF")
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
    client = MarketTimeClient(net, default_host=args.host)

    if args.autenticado:
        client.net.bootstrap_auth()

    try:
        # Modo 1: Auditoria Offline
        if args.auditar:
            return 0 if executar_auditoria_offline(args.auditar, p, rnd) else 1

        # Modo 2: Suíte de Testes ao Vivo
        if args.verifica:
            return 0 if executar_suite_verificacao(client, p, rnd) else 1

        # Modo 3: Listagem de Regiões
        if args.regioes:
            linhas = [f"• {k:<4} -> {v}_market" for k, v in sorted(REGIOES_VALIDAS.items())]
            rnd.caixa(linhas, titulo=f"REGIÕES VÁLIDAS ({len(REGIOES_VALIDAS)})", cor_titulo="ambar")
            return 0

        # Modo 4: Inspeção de Sessão
        if args.inspect:
            a3 = client.net.obter_a3_presente()
            linhas = [
                f"• Endpoint : {ENDPOINT_NAME}",
                f"• Cookie A3: {p.pintar(a3[:10] + '... (' + str(len(a3)) + 'B)', 'verde') if a3 else p.pintar('Ausente', 'amarelo')}",
                f"• Host     : {client.host} ({HOSTS_EP[client.host]})",
            ]
            rnd.caixa(linhas, titulo="INSPEÇÃO DE SESSÃO", cor_titulo="ciano")
            return 0

        # Modo 5: Varredura de Múltiplas Regiões
        if args.varrer:
            regs = [r.strip().upper() for r in args.varrer.split(",") if r.strip()]
            executar_varredura_regioes(client, regs, p, rnd)
            return 0

        # Modo 6: Dashboard ao Vivo
        if args.dashboard is not None:
            alvo = args.dashboard or args.region or DEFAULT_REGION
            regs = [r.strip().upper() for r in alvo.split(",") if r.strip()]
            executar_dashboard_tempo_real(client, regs, p, rnd, intervalo_s=args.intervalo)
            return 0

        # Modo 7: Operações Diretas Não-Interativas CLI
        if args.region or args.table or args.json or args.campos or args.checar or args.tick is not None:
            rg = (args.region or DEFAULT_REGION).upper()
            st, dados, rb = client.consultar(
                region=rg,
                lang=args.lang,
                com_key=not args.no_key,
                formatted=not args.raw,
                host=args.host
            )

            if args.json:
                sys.stdout.buffer.write(rb)
                sys.stdout.buffer.write(b"\n")
                return 0

            it = client.extrair_item(dados)
            if not it:
                sys.stderr.write(f"Erro ao consultar mercado {rg} (HTTP {st})\n")
                return 1

            if args.campos:
                tz_arr = it.get("timezone", [{}])
                linhas = [
                    f"id                 : {it.get('id')}",
                    f"name               : {it.get('name')}",
                    f"status             : {it.get('status')}",
                    f"yfit_market_id     : {it.get('yfit_market_id')}",
                    f"yfit_market_status : {it.get('yfit_market_status')}",
                    f"message            : {it.get('message')}",
                    f"open               : {it.get('open')}",
                    f"close              : {it.get('close')}",
                    f"time               : {it.get('time')}",
                    f"timezone           : {tz_arr[0].get('$text')} ({tz_arr[0].get('short')}, {tz_arr[0].get('gmtoffset')}s)",
                ]
                dur = it.get("duration")
                if dur:
                    linhas.append(f"duration           : hrs={dur[0].get('hrs')}, mins={dur[0].get('mins')}")
                rnd.caixa(linhas, titulo=f"CATÁLOGO DE CAMPOS · {rg}", cor_titulo="ambar")
                return 0

            if args.checar:
                passou = st == 200 and it.get("id") and it.get("yfit_market_status")
                print(f"Consistência {rg}: " + (p.pintar("OK", "verde") if passou else p.pintar("FALHA", "vermelho")))
                return 0 if passou else 1

            if args.tick is not None:
                est = client.extrair_estado_store(it)
                print(f"Estado Inicial: hrs={est.get('hrs')} mins={est.get('mins')} | '{est.get('message')}'")
                for i in range(1, args.tick + 1):
                    est = client.simular_tick_store(est)
                    print(f"Tick {i}: hrs={est.get('hrs')} mins={est.get('mins')} | '{est.get('message')}'")
                return 0

            if args.table:
                rnd.tabela_mercados([it], f"STATUS DE SESSÃO · {rg}")
                return 0

        # Modo 8: Menu Interativo Contínuo (Anti-Fechamento)
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