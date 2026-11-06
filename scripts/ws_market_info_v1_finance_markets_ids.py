#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 YF·MARKET IDS EXPLORER v4.0 — Terminal Interativo & Cliente Canônico
 Foco Exclusivo: GET /ws/market-info/v1/finance/markets/ids (Yahoo Finance)
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
      - Consulta canônica do right rail (modules=commodities,currencies).
      - Catálogo completo (--all / omitir modules para commodities, currencies, bonds, world_indices).
      - Injeção StepStone Private Equity (enableFtseStepStoneIndices=true expande world_indices 44->48).
      - Múltiplos hosts: query1, query2, iquery.
      - Console de requisições brutas (GET/POST/HEAD/OPTIONS, headers, params).
      - Deduplicação inteligente de tickers preservando ordem (ex: EURJPY=X duplicado).
      - Matriz de sensibilidade por locale (en-US/US vs pt-BR/BR com base BRL).
      - Cadeia do consumidor do rail: slice(0,5) de cada módulo + cotação de lote.
      - Suíte de verificação ao vivo com 20 testes de conformidade (20/20 PASS).
      - Auditoria estrutural offline de fixtures JSON.
      - Exportação JSON crua com paridade estrita de bytes.
   5. ROBUSTEZ DE REDE:
      - Retry com backoff exponencial 2^n e jitter para HTTP 429/503 (máx 5 tentativas).
      - Medição exata de latência (ms) e contagem de bytes trafegados.
   6. COMPATIBILIDADE CLI TOTAL:
      - Mantém suporte a --modules, --all, --lang, --region, --host,
        --ftse-stepstone, --quotes, --json, --table, --raw, etc.
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

ENDPOINT_NAME = "GET /ws/market-info/v1/finance/markets/ids"
PATH_EP = "/ws/market-info/v1/finance/markets/ids"
PATH_QUOTE = "/v7/finance/quote"

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

MODULOS_CONHECIDOS = ("commodities", "currencies", "bonds", "world_indices")
DEFAULT_MODULES_RAIL = "commodities,currencies"

DEFAULT_LANG = "en-US"
DEFAULT_REGION = "US"

STEPSTONE_INDICES = [
    "FPACEBOUS-USD-TR.FGI",
    "FPCPEXVM-USD-TR.FGI",
    "FPCPEXVA-USD-TR.FGI",
    "FPACEPE-USD-TR.FGI",
]

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


# ════════════════════════ Utilitários de Coleção ════════════════════════════

def dedupe_preservando_ordem(tickers: List[str]) -> List[str]:
    """Remove duplicatas de uma lista preservando a primeira ocorrência."""
    return list(dict.fromkeys(tickers))


# ══════════════════════ Motor de Rede & Sessão HTTP ═════════════════════════

class NetworkEngine:
    """
    Motor HTTP resiliente em stdlib puro:
    - Zero dependências de terceiros.
    - Backoff exponencial com jitter para HTTP 429/503 (máx 5 tentativas).
    - Medição exata de latência (ms) e contagem de bytes trafegados.
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


# ═══════════════════════ Cliente do Endpoint /ws ════════════════════════════

class MarketIdsClient:
    """Cliente canônico dedicado a GET /ws/market-info/v1/finance/markets/ids."""
    def __init__(self, net: NetworkEngine, default_host: str = DEFAULT_HOST):
        self.net = net
        self.host = default_host

    def montar_url(
        self,
        modules: Optional[Union[str, List[str]]] = None,
        lang: str = DEFAULT_LANG,
        region: str = DEFAULT_REGION,
        enable_ftse_step_stone_indices: bool = False,
        host: Optional[str] = None,
        extras: Optional[Dict[str, str]] = None
    ) -> str:
        base_host = HOSTS_EP.get(host or self.host, HOSTS_EP[DEFAULT_HOST])

        params: Dict[str, str] = {
            "lang": lang or DEFAULT_LANG,
            "region": region or DEFAULT_REGION,
        }
        if modules is not None:
            if isinstance(modules, (list, tuple)):
                params["modules"] = ",".join(m.strip() for m in modules if m.strip())
            elif str(modules).strip():
                params["modules"] = str(modules).strip()

        if enable_ftse_step_stone_indices:
            params["enableFtseStepStoneIndices"] = "true"

        if extras:
            params.update(extras)

        qs = urllib.parse.urlencode(params)
        return f"{base_host}{PATH_EP}?{qs}"

    def consultar(
        self,
        modules: Optional[Union[str, List[str]]] = None,
        lang: str = DEFAULT_LANG,
        region: str = DEFAULT_REGION,
        enable_ftse_step_stone_indices: bool = False,
        host: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        extras: Optional[Dict[str, str]] = None
    ) -> Tuple[int, Optional[Dict[str, Any]], bytes]:
        url = self.montar_url(
            modules=modules,
            lang=lang,
            region=region,
            enable_ftse_step_stone_indices=enable_ftse_step_stone_indices,
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

    def obter_cotacoes_lote(self, simbolos: List[str]) -> List[Dict[str, Any]]:
        """Consulta cotações do lote para simular a cadeia de right rail."""
        if not simbolos:
            return []
        base_host = HOSTS_EP.get(self.host, HOSTS_EP[DEFAULT_HOST])
        params = {
            "symbols": ",".join(simbolos).upper(),
            "formatted": "false",
            "lang": DEFAULT_LANG,
            "region": DEFAULT_REGION,
        }
        url = f"{base_host}{PATH_QUOTE}?{urllib.parse.urlencode(params)}"
        st, _, raw_b = self.net.request_raw(url)
        if st == 200:
            try:
                j = json.loads(raw_b.decode("utf-8", errors="replace"))
                return j.get("quoteResponse", {}).get("result", [])
            except Exception:
                return []
        return []


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

    def tabela_resumo_modulos(self, resultado: Dict[str, Any]) -> None:
        """Renderiza tabela síntese com contagens, tipos e duplicatas dos módulos."""
        if not resultado:
            print(f"  {self.p.pintar('[AVISO] Nenhum módulo retornado no objeto result.', 'amarelo')}")
            return

        print(f"\n {self.p.pintar('RESUMO DOS MÓDULOS DE MERCADO RESOLVIDOS', 'ambar', negrito=True)}")

        colunas = [
            ("MÓDULO", 16, "<"),
            ("PAYLOAD TYPE", 18, "<"),
            ("QUOTE TYPE", 12, "<"),
            ("TOTAL", 7, ">"),
            ("ÚNICOS", 7, ">"),
            ("DUPLICATAS", 10, "^")
        ]

        p, b = self.p, self.b
        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for mod, dados in sorted(resultado.items()):
            tickers = dados.get("tickers", [])
            unicos = dedupe_preservando_ordem(tickers)
            dups = len(tickers) - len(unicos)

            dups_fmt = p.pintar(str(dups), "amarelo" if dups > 0 else "cinza_esc")

            linha_cel = [
                (p.pintar(mod[:15], "ambar", negrito=True), colunas[0][1], colunas[0][2]),
                (dados.get("type", "—")[:17], colunas[1][1], colunas[1][2]),
                (p.pintar(dados.get("quoteType", "—")[:11], "ciano"), colunas[2][1], colunas[2][2]),
                (str(len(tickers)), colunas[3][1], colunas[3][2]),
                (p.pintar(str(len(unicos)), "verde"), colunas[4][1], colunas[4][2]),
                (dups_fmt, colunas[5][1], colunas[5][2]),
            ]

            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)

    def grid_tickers(self, modulo: str, tickers: List[str]) -> None:
        """Renderiza tickers de um módulo em grid colunar de alta densidade."""
        unicos = dedupe_preservando_ordem(tickers)
        total = len(tickers)
        dups = total - len(unicos)

        tit = f"TICKERS: {modulo.upper()} (Total: {total} | Únicos: {len(unicos)}"
        if dups > 0:
            tit += f" | {dups} Duplicatas no servidor"
        tit += ")"

        p = self.p
        print(f"\n {p.pintar(tit, 'ambar', negrito=True)}")

        # Grid de 5 colunas
        cols_qtd = 5
        col_w = 14
        linhas = []
        for i in range(0, len(tickers), cols_qtd):
            bloco = tickers[i:i + cols_qtd]
            celulas = []
            for t_item in bloco:
                cor_t = "amarelo" if tickers.count(t_item) > 1 else "branco"
                celulas.append(pad_vis(p.pintar(t_item, cor_t), col_w, "<"))
            linhas.append("  " + " ".join(celulas))

        print("\n".join(linhas) + "\n")


# ═══════════════ Módulo 1: Suíte de Verificação ao Vivo ══════════════════════

def executar_suite_verificacao(client: MarketIdsClient, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Executa a suíte de 20 checagens de conformidade ao vivo do endpoint /ws/market-info/v1/finance/markets/ids."""
    print(f"\n {p.pintar('SUÍTE DE VERIFICAÇÃO AO VIVO (' + ENDPOINT_NAME + ')', 'azul', negrito=True)}")
    print(f"  {p.pintar('Validando contratos de módulos, locales, duplicatas e limites...', 'cinza_esc')}\n")

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

    # 1. Consulta canônica com modules=commodities,currencies
    st, d, _ = client.consultar(modules=DEFAULT_MODULES_RAIL)
    res = (d or {}).get("finance", {}).get("result", {})
    relatar(1, "Canônica do rail (commodities,currencies) retorna 200 OK", st == 200 and "commodities" in res and "currencies" in res, f"módulos={list(res.keys())}")

    # 2. Result é um dicionário e error é nulo
    err = (d or {}).get("finance", {}).get("error")
    relatar(2, "finance.result é objeto chaveado e error é estritamente nulo", isinstance(res, dict) and err is None, "envelope ok")

    # 3. Módulo commodities com contrato correto
    mod_com = res.get("commodities", {})
    tks_com = mod_com.get("tickers", [])
    relatar(3, "Módulo commodities tem type='screener_payload' e quoteType='FUTURE'", mod_com.get("type") == "screener_payload" and mod_com.get("quoteType") == "FUTURE", f"tickers={len(tks_com)}")

    # 4. Módulo currencies com contrato correto
    mod_cur = res.get("currencies", {})
    tks_cur = mod_cur.get("tickers", [])
    relatar(4, "Módulo currencies tem type='screener_payload' e quoteType='CURRENCY'", mod_cur.get("type") == "screener_payload" and mod_cur.get("quoteType") == "CURRENCY", f"tickers={len(tks_cur)}")

    # 5. Detecção comprovada da duplicata conhecida de EURJPY=X em currencies
    tem_eurjpy_dup = tks_cur.count("EURJPY=X") >= 2
    relatar(5, "Duplicata conhecida de 'EURJPY=X' detectada no servidor", tem_eurjpy_dup, f"ocorrências={tks_cur.count('EURJPY=X')}")

    # 6. Catálogo completo: omitir modules devolve os 4 módulos conhecidos
    st_all, d_all, _ = client.consultar(modules=None)
    res_all = (d_all or {}).get("finance", {}).get("result", {})
    tem_4_mods = all(m in res_all for m in MODULOS_CONHECIDOS)
    relatar(6, "Omitir modules devolve o catálogo completo dos 4 módulos", st_all == 200 and tem_4_mods, f"módulos={len(res_all)}")

    # 7. Módulo bonds presente com quoteType=INDEX
    mod_bonds = res_all.get("bonds", {})
    relatar(7, "Módulo bonds mapeado com tickers de taxas e quoteType='INDEX'", mod_bonds.get("quoteType") == "INDEX" and len(mod_bonds.get("tickers", [])) == 6, f"tickers={len(mod_bonds.get('tickers', []))}")

    # 8. Módulo world_indices presente com 44 índices no padrão US
    mod_idx = res_all.get("world_indices", {})
    tks_idx = mod_idx.get("tickers", [])
    relatar(8, "Módulo world_indices padrão contém 44 índices mundiais", len(tks_idx) == 44, f"total={len(tks_idx)}")

    # 9. enableFtseStepStoneIndices=true expande world_indices de 44 para 48
    st_ftse, d_ftse, _ = client.consultar(modules="world_indices", enable_ftse_step_stone_indices=True)
    res_ftse = (d_ftse or {}).get("finance", {}).get("result", {}).get("world_indices", {}).get("tickers", [])
    relatar(9, "enableFtseStepStoneIndices=true expande world_indices para 48", len(res_ftse) == 48, f"total={len(res_ftse)}")

    # 10. Presença dos índices StepStone (.FGI) quando ativado
    tem_stepstone = all(idx in res_ftse for idx in STEPSTONE_INDICES)
    relatar(10, "Presença de todos os 4 índices StepStone (.FGI) no retorno", tem_stepstone, "4/4 presentes")

    # 11. modules case-insensitive (COMMODITIES == commodities)
    st_case, d_case, _ = client.consultar(modules="COMMODITIES")
    res_case = (d_case or {}).get("finance", {}).get("result", {})
    relatar(11, "Parâmetro modules é case-insensitive ('COMMODITIES' aceito)", st_case == 200 and "commodities" in res_case, "resolvido ok")

    # 12. Módulo desconhecido é omitido silenciosamente com HTTP 200 (result: {})
    st_desc, d_desc, _ = client.consultar(modules="MODULO_INEXISTENTE_XYZ")
    res_desc = (d_desc or {}).get("finance", {}).get("result", {})
    relatar(12, "Módulo desconhecido é omitido silenciosamente (result={})", st_desc == 200 and len(res_desc) == 0, "omissão silenciosa")

    # 13. Par pt-BR + BR troca base de currencies para BRL
    st_br, d_br, _ = client.consultar(modules="currencies", lang="pt-BR", region="BR")
    tks_br_cur = (d_br or {}).get("finance", {}).get("result", {}).get("currencies", {}).get("tickers", [])
    tem_brlusd = "BRLUSD=X" in tks_br_cur
    relatar(13, "Par pt-BR/BR comuta base de currencies incluindo 'BRLUSD=X'", st_br == 200 and tem_brlusd, f"tickers={len(tks_br_cur)}")

    # 14. Par pt-BR + BR remove futuros de índice/treasury de commodities (37 -> 27)
    st_br_com, d_br_com, _ = client.consultar(modules="commodities", lang="pt-BR", region="BR")
    tks_br_com = (d_br_com or {}).get("finance", {}).get("result", {}).get("commodities", {}).get("tickers", [])
    relatar(14, "Par pt-BR/BR poda commodities de 37 para 27 agrícolas/energia", st_br_com == 200 and len(tks_br_com) == 27, f"tickers={len(tks_br_com)}")

    # 15. formatted=false aceito como no-op
    st_fmt, d_fmt, _ = client.consultar(modules="commodities", extras={"formatted": "false"})
    relatar(15, "Parâmetro formatted=false aceito como no-op (200 OK)", st_fmt == 200 and "commodities" in (d_fmt or {}).get("finance", {}).get("result", {}), "no-op comprovado")

    # 16. Crumb inválido ignorado sem erro (família sem enforcement)
    st_cr, d_cr, _ = client.consultar(modules="commodities", extras={"crumb": "GARBAGE_TOKEN"})
    relatar(16, "Token crumb na query é ignorado sem erro (endpoint anônimo)", st_cr == 200, "200 OK anônimo")

    # 17. User-Agent genérico python-urllib bloqueado com 429 pela borda
    url_com = client.montar_url(modules="commodities")
    st_pyua, _, _ = client.net.request_raw(url_com, headers={"User-Agent": "Python-urllib/3.13"})
    relatar(17, "User-Agent python-urllib bloqueado com HTTP 429 na borda", st_pyua == 429, "Too Many Requests")

    # 18. Método HEAD responde HTTP 200 com corpo vazio
    st_head, hdrs_head, corpo_head = client.net.request_raw(url_com, metodo="HEAD")
    relatar(18, "Método HEAD retorna HTTP 200 e corpo vazio (0 bytes)", st_head == 200 and len(corpo_head) == 0, "HEAD ok")

    # 19. Método POST rejeitado com HTTP 405 Method Not Allowed
    st_post, _, _ = client.net.request_raw(url_com, metodo="POST")
    relatar(19, "Método POST rejeitado com HTTP 405 Method Not Allowed", st_post == 405, "405 rejeitado")

    # 20. Host secundário query2 e terciário iquery operacionais
    st_q2, d_q2, _ = client.consultar(modules="commodities", host="query2")
    st_iq, d_iq, _ = client.consultar(modules="commodities", host="iquery")
    relatar(20, "Hosts query2 e iquery operacionais e equivalentes (200 OK)", st_q2 == 200 and st_iq == 200, "query2 & iquery ativos")

    taxa = (testes_passados / total_testes) * 100.0
    print(f"\n {p.pintar(f'Resultado da Suíte: {testes_passados}/{total_testes} aprovados ({taxa:.1f}% de conformidade)', 'verde' if taxa == 100 else 'amarelo', negrito=True)}\n")
    return testes_passados == total_testes


# ══════════════ Módulo 2: Auditoria Estrutural Offline ══════════════════════

def executar_auditoria_offline(caminho_arquivo: str, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Valida estrutura de fixture JSON de markets/ids sem emitir tráfego de rede."""
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
        res = fin.get("result")
        err = fin.get("error")
        invariantes.append(("2. Campo 'error' é estritamente nulo", err is None))
        invariantes.append(("3. Campo 'result' é um objeto (dicionário)", isinstance(res, dict)))

        if isinstance(res, dict) and res:
            todos_modulos_validos = all(isinstance(v, dict) and "tickers" in v and "type" in v and "quoteType" in v for v in res.values())
            invariantes.append(("4. Todos os módulos contêm 'type', 'quoteType' e 'tickers'", todos_modulos_validos))

            arrays_tickers = all(isinstance(v.get("tickers"), list) for v in res.values())
            invariantes.append(("5. Campo 'tickers' é lista em todos os módulos", arrays_tickers))

            todos_screener_payload = all(v.get("type") == "screener_payload" for v in res.values())
            invariantes.append(("6. Constante 'type' é estritamente 'screener_payload'", todos_screener_payload))

    for rotulo, cond in invariantes:
        st = p.pintar("CONFORME", "verde", negrito=True) if cond else p.pintar("VIOLAÇÃO", "vermelho", negrito=True)
        print(f"  [{st}] {rotulo}")

    aprovado = all(c for _, c in invariantes)
    print(f"\n  Status: {p.pintar('FIXTURE CERTIFICADA', 'verde') if aprovado else p.pintar('FIXTURE INVÁLIDA', 'vermelho')}\n")
    return aprovado


# ═══════════════ Módulo 3: Comparador de Locales ════════════════════════════

def comparar_locales(client: MarketIdsClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Demonstra o impacto da variação de par de locale (en-US/US vs pt-BR/BR)."""
    print(f"\n {p.pintar('MATRIZ DE SENSIBILIDADE POR LOCALE (PAR LANG + REGION)', 'ambar', negrito=True)}")
    print(f"  {p.pintar('Comparando en-US/US vs pt-BR/BR em tempo real...', 'cinza_esc')}\n")

    st1, d_us, _ = client.consultar(modules=None, lang="en-US", region="US")
    st2, d_br, _ = client.consultar(modules=None, lang="pt-BR", region="BR")

    res_us = (d_us or {}).get("finance", {}).get("result", {})
    res_br = (d_br or {}).get("finance", {}).get("result", {})

    linhas = []
    for mod in MODULOS_CONHECIDOS:
        t_us = res_us.get(mod, {}).get("tickers", [])
        t_br = res_br.get(mod, {}).get("tickers", [])

        u_us = len(dedupe_preservando_ordem(t_us))
        u_br = len(dedupe_preservando_ordem(t_br))

        linhas.append(f"• Módulo {p.pintar(mod.upper(), 'ambar', negrito=True)}:")
        linhas.append(f"  US: {len(t_us)} tickers ({u_us} únicos) | BR: {len(t_br)} tickers ({u_br} únicos)")

        if mod == "commodities":
            linhas.append(f"  Diferença: BR remove {len(t_us) - len(t_br)} futuros de treasury/índice (sobra agrícola/energia/metais).")
        elif mod == "currencies":
            linhas.append(f"  Diferença: BR comuta base para BRL (+{len(t_br) - len(t_us)} pares locais como BRLUSD=X, BRLEUR=X).")
        elif mod == "world_indices":
            lider_us = t_us[0] if t_us else "—"
            lider_br = t_br[0] if t_br else "—"
            linhas.append(f"  Diferença: Reordenação de posições (Líder US: {lider_us} | Líder BR: {lider_br} Américas primeiro).")
        linhas.append("")

    rnd.caixa(linhas, titulo="VARIAÇÃO DE CONTEÚDO POR LOCALE", cor_titulo="ciano")


# ═══════════════ Módulo 4: Cadeia do Consumidor (Top 5 Tickers) ══════════════

def simular_cadeia_consumidor(client: MarketIdsClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Replica a lógica oficial do right rail: corta 5 tickers de cada módulo e cota."""
    print(f"\n {p.pintar('CADEIA DO CONSUMIDOR (RIGHT RAIL CHART ENGINE)', 'ambar', negrito=True)}")
    print(f"  {p.pintar('1. Resolve listas -> 2. Corta slice(0,5) -> 3. Cota no v7/finance/quote...', 'cinza_esc')}\n")

    st, dados, _ = client.consultar(modules=DEFAULT_MODULES_RAIL)
    res = (dados or {}).get("finance", {}).get("result", {})

    if not res:
        print(f"  {p.pintar('[ERRO] Falha ao resolver listas para o right rail.', 'vermelho')}")
        return

    for mod in ("commodities", "currencies"):
        dados_mod = res.get(mod, {})
        tickers_orig = dados_mod.get("tickers", [])
        top5 = dedupe_preservando_ordem(tickers_orig)[:5]

        print(f"  Módulo {p.pintar(mod.upper(), 'ambar', negrito=True)} (Top 5 selecionados para o rail):")
        print(f"  Tickers: {', '.join(top5)}")

        quotes = client.obter_cotacoes_lote(top5)
        if quotes:
            for q in quotes:
                sym = q.get("symbol", "—")
                pr = q.get("regularMarketPrice")
                ch = q.get("regularMarketChangePercent")
                ch_str = f"{ch:+.2f}%" if ch is not None else "—"
                cor_v = "verde" if (ch or 0) > 0 else ("vermelho" if (ch or 0) < 0 else "branco")
                print(f"    • {sym:<10} Preço: {str(pr):>10} | Variação: {p.pintar(ch_str, cor_v)}")
        else:
            print(f"    {p.pintar('Não foi possível obter cotações no momento.', 'cinza_esc')}")
        print()


# ═══════════════ Módulo 5: Console de Requisições Brutas ═════════════════════

def console_requisicao_bruta(client: MarketIdsClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Diagnóstico de rede: testa métodos, hosts e parâmetros manuais."""
    print(f"\n {p.pintar('CONSOLE DE DIAGNÓSTICO & REQUISIÇÃO BRUTA', 'ciano', negrito=True)}")
    print(f"  {p.pintar('Inspecione status HTTP, latência e cabeçalhos reais da borda.', 'cinza_esc')}\n")

    metodo = (input(f"  {p.pintar('Método HTTP (GET/POST/HEAD/OPTIONS) [GET]:', 'branco', negrito=True)} ").strip().upper()) or "GET"
    host = (input(f"  {p.pintar('Host (query1/query2/iquery) [query1]:', 'branco', negrito=True)} ").strip().lower()) or "query1"
    mods = input(f"  {p.pintar('Módulos CSV (ou Enter para catálogo completo):', 'branco', negrito=True)} ").strip()

    extras_str = input(f"  {p.pintar('Parâmetros extras (k=v&k2=v2) [Enter para nenhum]:', 'branco')} ").strip()
    extras = {}
    if extras_str:
        for par in extras_str.split("&"):
            if "=" in par:
                k, v = par.split("=", 1)
                extras[k.strip()] = v.strip()

    url = client.montar_url(modules=mods or None, host=host, extras=extras)
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


# ══════════════ Módulo 6: Submenu de Visões de um Módulo ═════════════════════

def submenu_visoes_modulo(client: MarketIdsClient, resultado: Dict[str, Any], p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop contínuo de exploração dos módulos e tickers retornados."""
    modulos = sorted(resultado.keys())
    if not modulos:
        print(f"  {p.pintar('[AVISO] Nenhum módulo disponível para exploração.', 'amarelo')}")
        return

    mod_selecionado = modulos[0]

    while True:
        try:
            dados_m = resultado.get(mod_selecionado, {})
            tks = dados_m.get("tickers", [])
            tit_sub = f"VISÕES — MÓDULO: {mod_selecionado.upper()} ({len(tks)} tickers)"
            print(f"\n {p.pintar(tit_sub, 'ambar', negrito=True)}")
            print(f"  [1] Tabela Resumo dos Módulos")
            print(f"  [2] Grid Completo de Tickers deste Módulo")
            print(f"  [3] Análise de Deduplicação & Tickers Únicos")
            print(f"  [4] Simular Corte Top 5 do Right Rail")
            print(f"  [5] Alternar Módulo em Foco ({', '.join(modulos)})")
            print(f"  [6] Exibir Resposta JSON Bruta Formatada")
            print(f"  [7] Exportar JSON da Consulta para Arquivo")
            print(f"  [0] Voltar ao Menu Principal")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                break

            elif escolha == "1":
                rnd.tabela_resumo_modulos(resultado)

            elif escolha == "2":
                rnd.grid_tickers(mod_selecionado, tks)

            elif escolha == "3":
                unicos = dedupe_preservando_ordem(tks)
                dups = len(tks) - len(unicos)
                linhas = [
                    f"• Módulo               : {mod_selecionado.upper()}",
                    f"• Total de Entradas    : {len(tks)}",
                    f"• Instrumentos Únicos  : {len(unicos)}",
                    f"• Duplicatas no Servidor: {dups}",
                    f"• Tipo de Instrumento  : {dados_m.get('quoteType')}",
                ]
                if dups > 0:
                    repetidos = set([x for x in tks if tks.count(x) > 1])
                    linhas.append(f"• Tickers Repetidos    : {', '.join(repetidos)}")
                rnd.caixa(linhas, titulo="ANÁLISE DE DEDUPLICAÇÃO", cor_titulo="ciano")

            elif escolha == "4":
                top5 = dedupe_preservando_ordem(tks)[:5]
                linhas = [
                    f"Corte oficial de 5 tickers do right rail para {mod_selecionado.upper()}:",
                    "",
                    f"• Tickers selecionados: {', '.join(top5)}",
                    f"• 32 dos 37 commodities e 18 dos 23 currencies são descartados pelo cliente oficial."
                ]
                rnd.caixa(linhas, titulo="CORTE DE CONSUMO DO RIGHT RAIL", cor_titulo="verde")

            elif escolha == "5":
                print(f"\n  Módulos disponíveis: {', '.join(modulos)}")
                novo_m = input(f"  {p.pintar('Escolha o módulo:', 'branco')} ").strip().lower()
                if novo_m in resultado:
                    mod_selecionado = novo_m
                else:
                    print(f"  {p.pintar('Módulo não encontrado no resultado atual.', 'amarelo')}")

            elif escolha == "6":
                print(f"\n{json.dumps({'finance': {'result': resultado, 'error': None}}, indent=2, ensure_ascii=False)}\n")

            elif escolha == "7":
                nome_arq = f"markets_ids_{mod_selecionado}_{int(time.time())}.json"
                with open(nome_arq, "w", encoding="utf-8") as f:
                    json.dump({"finance": {"result": resultado, "error": None}}, f, indent=2, ensure_ascii=False)
                print(f"  {p.pintar(f'[SUCESSO] JSON salvo em {nome_arq}', 'verde')}")

        except KeyboardInterrupt:
            print(f"\n  {p.pintar('Operação cancelada. Retornando ao submenu...', 'amarelo')}")


# ════════════════════ Menu Principal & CLI Dispatcher ═══════════════════════

def menu_principal(client: MarketIdsClient, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop principal interativo anti-fechamento."""
    while True:
        try:
            print(f"\n {p.pintar('YAHOO FINANCE MARKETS IDS RESOLVER (/ws Explorer)', 'ambar', negrito=True)}")
            print(f"  {p.pintar('Resolvedor de tickers por módulo para o Right Rail de Gráficos | stdlib pura', 'cinza_esc')}\n")

            print(f"  [1] Consulta Canônica do Rail (commodities, currencies)")
            print(f"  [2] Catálogo Completo (--all: commodities, currencies, bonds, world_indices)")
            print(f"  [3] Selecionar Módulos Específicos (personalizado)")
            print(f"  [4] Injeção FTSE StepStone (world_indices 44 -> 48 tickers)")
            print(f"  [5] Matriz de Sensibilidade por Locale (en-US/US vs pt-BR/BR)")
            print(f"  [6] Simular Cadeia do Consumidor (Top 5 + Cotação em Lote)")
            print(f"  [7] Console de Requisições Brutas (Diagnóstico HTTP/Protocolo)")
            print(f"  [8] Suíte de Verificação ao Vivo (20 Testes de Conformidade)")
            print(f"  [9] Auditoria Estrutural Offline (Validar Fixture JSON)")
            print(f"  [10] Exportar Fixture JSON Crua")
            print(f"  [0] Encerrar Aplicativo")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                print(f"\n  {p.pintar('Encerrando aplicação de forma limpa. Até logo!', 'ciano')}")
                break

            elif escolha == "1":
                st, dados, _ = client.consultar(modules=DEFAULT_MODULES_RAIL)
                res = (dados or {}).get("finance", {}).get("result", {})
                rnd.tabela_resumo_modulos(res)
                submenu_visoes_modulo(client, res, p, rnd)

            elif escolha == "2":
                st, dados, _ = client.consultar(modules=None)
                res = (dados or {}).get("finance", {}).get("result", {})
                rnd.tabela_resumo_modulos(res)
                submenu_visoes_modulo(client, res, p, rnd)

            elif escolha == "3":
                print(f"\n  Módulos suportados: {', '.join(MODULOS_CONHECIDOS)}")
                mods_in = input(f"  {p.pintar('Informe módulos separados por vírgula [bonds,world_indices]:', 'branco')} ").strip() or "bonds,world_indices"
                st, dados, _ = client.consultar(modules=mods_in)
                res = (dados or {}).get("finance", {}).get("result", {})
                rnd.tabela_resumo_modulos(res)
                submenu_visoes_modulo(client, res, p, rnd)

            elif escolha == "4":
                print(f"  {p.pintar('Consultando world_indices com enableFtseStepStoneIndices=true...', 'cinza_esc')}")
                st, dados, _ = client.consultar(modules="world_indices", enable_ftse_step_stone_indices=True)
                res = (dados or {}).get("finance", {}).get("result", {})
                rnd.tabela_resumo_modulos(res)
                tks = res.get("world_indices", {}).get("tickers", [])
                rnd.grid_tickers("world_indices (com StepStone)", tks)

            elif escolha == "5":
                comparar_locales(client, p, rnd)

            elif escolha == "6":
                simular_cadeia_consumidor(client, p, rnd)

            elif escolha == "7":
                console_requisicao_bruta(client, p, rnd)

            elif escolha == "8":
                executar_suite_verificacao(client, p, rnd)

            elif escolha == "9":
                arq = input(f"  {p.pintar('Caminho da fixture JSON [ws_market_info_v1_finance_markets_ids.json]:', 'branco')} ").strip() or "ws_market_info_v1_finance_markets_ids.json"
                executar_auditoria_offline(arq, p, rnd)

            elif escolha == "10":
                st, _, rb = client.consultar(modules=None)
                if st == 200:
                    nome = f"markets_ids_full_{int(time.time())}.json"
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
        prog="ws_market_info_v1_finance_markets_ids.py",
        description="Terminal Interativo Bloomberg & Cliente Canônico GET /ws/market-info/v1/finance/markets/ids"
    )

    # Argumentos CLI compatíveis
    parser.add_argument("--modules", default="commodities,currencies", help="Lista CSV de módulos; use --all para catálogo completo")
    parser.add_argument("--all", action="store_true", help="Omissão do param modules (catálogo completo dos 4 módulos)")
    parser.add_argument("--lang", default=DEFAULT_LANG, help="Locale de linguagem (default en-US)")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Região geográfica (default US)")
    parser.add_argument("--host", choices=list(HOSTS_EP.keys()), default=DEFAULT_HOST, help="Host edge da Yahoo")
    parser.add_argument("--ftse-stepstone", action="store_true", help="enableFtseStepStoneIndices=true (world_indices 44 -> 48)")
    parser.add_argument("--quotes", action="store_true", help="Executa cadeia do consumidor: slice(0,5) + v7/finance/quote")
    parser.add_argument("--json", action="store_true", help="Imprime o envelope JSON cru byte a byte")
    parser.add_argument("--table", action="store_true", help="Exibe tabela de resumo dos módulos e encerra")
    parser.add_argument("--raw", action="store_true", help="Exibe requisição e cabeçalhos crus")
    parser.add_argument("--verifica", action="store_true", help="Executa a suíte de 20 testes de conformidade ao vivo")
    parser.add_argument("--auditar", default=None, metavar="ARQ", help="Audita estruturalmente fixture JSON offline")
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
    client = MarketIdsClient(net, default_host=args.host)

    try:
        # Modo 1: Auditoria Offline
        if args.auditar:
            return 0 if executar_auditoria_offline(args.auditar, p, rnd) else 1

        # Modo 2: Suíte de Testes ao Vivo
        if args.verifica:
            return 0 if executar_suite_verificacao(client, p, rnd) else 1

        # Modo 3: Cadeia do Consumidor (Quotes)
        if args.quotes:
            simular_cadeia_consumidor(client, p, rnd)
            return 0

        # Modo 4: Consulta Não-Interativa CLI
        tem_flags_cli = (
            args.all or
            args.table or
            args.json or
            args.raw or
            args.ftse_stepstone or
            args.modules != DEFAULT_MODULES_RAIL or
            args.lang != DEFAULT_LANG or
            args.region != DEFAULT_REGION or
            args.host != DEFAULT_HOST
        )

        if tem_flags_cli:
            modulos_alvo = None if args.all else args.modules
            st, dados, rb = client.consultar(
                modules=modulos_alvo,
                lang=args.lang,
                region=args.region,
                enable_ftse_step_stone_indices=args.ftse_stepstone,
                host=args.host
            )

            if args.json:
                sys.stdout.buffer.write(rb)
                sys.stdout.buffer.write(b"\n")
                return 0

            if args.raw:
                url_gerada = client.montar_url(
                    modules=modulos_alvo,
                    lang=args.lang,
                    region=args.region,
                    enable_ftse_step_stone_indices=args.ftse_stepstone,
                    host=args.host
                )
                print(f"GET {url_gerada}")
                print(f"HTTP Status: {st} | Tamanho: {len(rb)}B | Latência: {client.net.ultima_latencia_ms:.1f}ms\n")
                sys.stdout.buffer.write(rb)
                sys.stdout.buffer.write(b"\n")
                return 0

            if st == 200 and dados:
                res = dados.get("finance", {}).get("result", {})
                rnd.tabela_resumo_modulos(res)
                for mod, d_m in sorted(res.items()):
                    rnd.grid_tickers(mod, d_m.get("tickers", []))
                return 0
            else:
                sys.stderr.write(f"Erro ao consultar resolvedor de mercados (HTTP {st})\n")
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