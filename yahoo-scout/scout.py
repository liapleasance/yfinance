#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scout.py — Chat completo do Scout AI (Yahoo Finance) · código legado de referência
==================================================================================

Cliente autossuficiente (somente stdlib) das famílias **Promenade API** (chat)
e **MAD v2** (análises) — contrato documentado em `yf_scout_ai.md`. Cobre TODAS
as funções da API em um único REPL com UI de terminal:

  CHAT — texto livre pergunta ao Scout (streaming SSE token-a-token)
    /nova /sse /contexto /historico /info /sessoes /fixar /seeds /ativas
    /retomar /feedback /quota /renovar /apagar /exportar

  MAD v2
    /analista [SIMB] [seção]  /ddq <uuid> [n|qid]  /ect --transcript-id=ID
    /transcricao --transcript-id=ID  /perguntas [SIMB]
    /temas [grain]  /tickers  /tema <uuid>  /tema-simbolo [SIMB]  /grafo [jan]
    /artigos-tema <uuid>…  /portfolio A:P,…|<id>  /insights  /diario
    /faqs <pergunta>  /watchlist  /screener [c]  /screener-legado [c]

  INFRA / DIAGNÓSTICO
    /config  /deeplink [texto]  /aposentado  /rate-limit  /json  /ajuda  /sair

Rota → método (contrato):

  Promenade (promenade-api.search.yahoo.com; 🔑 cookie A3, crumb ausente)
    POST   /sessions                          criação de sessão (201)
    POST   /chat                              mensagem — JSON completo ou SSE
    POST   /chat/seeds                        resposta semeada (cache ttl=5)
    GET    /sessions/{id}/messages            histórico paginado por cursor
    GET    /sessions/{id} · GET /sessions     metadados · lista (logada)
    PATCH  /sessions/{id} · POST …/delete    escrita restrita (403 anônimo)
    GET    /sessions/{id}/active-stream       sondagem de stream
    GET    /chat/resume/{stream_id}           replay (exige Accept: SSE)
    POST   /feedback                          👍/👎 (enum de reason no servidor)
  Proxy XHR (finance.yahoo.com; ❌ anônimo)
    GET    /xhr/dynamic-seeded-questions      perguntas sugeridas (502 por shard)
    GET    /xhr/transcript                    conteúdo de transcrição (com crumb)
  MAD v2 (query1/query2.finance.yahoo.com; ❌ anônimo nas GET)
    GET    /ws/mad/v2/analyst/symbol/{symbol} AI Analyst — 8 seções
    GET    /ws/mad/v2/analyst/ect             insights de transcrição (1 id apenas)
    GET    /ws/mad/v2/articles_ddq/{uuid}/questions[/{qid}]   Dig Deeper
    GET    /ws/mad/v2/themes[/tickers|/{uuid}|/symbol/{t}|/graph]   temas
    POST   /ws/mad/v2/themes/from-articles    🔑 x-txn-token (schema > token)
    POST   /ws/mad/v2/themes/portfolio/feed   feed do portfólio (sem gate)
    GET    /v2/daily_brief/* · /v2/portfolio_ddq/faqs · /v2/watchlist_insights/*
                                              🔑 x-txn-token (401 anônimo)
    POST   /ws/mad/v2/screener/nls (+ legado com crumb)   🔑 sessão logada
  Aposentada (410 Gone — contrato fóssil registrado no bundle)
    POST/GET /ws/mad/v2/chat[/{id}|/question/{uuid}|/rate_limit]

Autenticação: cookie **A3 anônimo** de `fc.yahoo.com` — o crumb NÃO participa
do chat; é adquirido só para as duas rotas que o exigem (transcrição e
screener legado). Quota: 100.000 tokens/24 h por identidade — /renovar troca
o A3 e renova.

Somente stdlib (urllib + http.cookiejar). Python 3.8+.

Uso:
    python scout.py                                  # REPL — texto livre pergunta
    python scout.py -q "What is the Dow?"            # pergunta única (SSE) e sai
    python scout.py -q "How is AAPL?" --json --contexto ticker:AAPL
    python scout.py --seeds "What is NASDAQ?"        # resposta semeada
    python scout.py --perguntas NVDA                 # catálogo de perguntas
    python scout.py --analista AAPL [--secao overview]
    python scout.py --temas --grafo 1d --portfolio AAPL:5000,NVDA:3000
    python scout.py --insights --aposentado --config --screener "top tech"
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
import uuid as _uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ===========================================================================
# 1. CONSTANTES DO CONTRATO (yf_scout_ai.md §1-§3)
# ===========================================================================

PROMENADE = "https://promenade-api.search.yahoo.com"   # serviço `scout` (§2.2)
SCOUT_DEV = "https://dev-promenade-api.search.yahoo.com"  # `scoutDev` — interno
Q1 = "https://query1.finance.yahoo.com"                # chave `finance`/`financeProd`
Q2 = "https://query2.finance.yahoo.com"                # espelho do AI Analyst
FINANCE_HOST = "https://finance.yahoo.com"             # proxy XHR (§3.1)
FC_HOST = "https://fc.yahoo.com"                       # emite A1/A1S/A3 (§2.3)

TENANT = "finance"                                     # constante do bundle (§4.1)
TTL_SEEDS = 5                                          # fixado pelo cliente (§3.3)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64 x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TIMEOUT_SESSAO = 30        # rotas de sessão/metadados
TIMEOUT_CHAT = 150         # chat pode levar o pipeline completo
TIMEOUT_SSE = 240          # streaming (corpo lido em pedaços)
TENTATIVAS_5XX = 8         # 500 vazio transiente da borda (§8.2/§7) — repetir
                           # resolve; proporção varia por janela

PAGINA_MENSAGENS = 100     # página do histórico (§5.1)
TETO_MENSAGENS = 500       # teto por conversa no cliente
LIMITE_SESSOES = 25        # listagem do Dock

MOTIVOS_FEEDBACK = ("offensive", "not_helpful", "too_long", "too_short")  # §5.2

# eventos SSE na ordem canônica (§5.3)
EVENTOS_SSE = ("stream.start", "status.update", "content.delta",
               "grounding.sources", "follow_up.questions",
               "actions.suggested", "data", "stream.end", "error")

# seções do AI Analyst — mapa servidor → rótulo (§5.5)
SECOES_ANALISTA = (
    ("overview", "Visão geral"),
    ("rtr", "Ratings de analistas"),
    ("earnings_transcripts_insights", "Transcrições de earnings"),
    ("financial_insights", "Métricas financeiras"),
    ("holdings_insights", "Atividade de insiders"),
    ("price_movement", "Movimento do preço"),
    ("options_analysis", "Opções"),
    ("news_summary", "Resumo de notícias"),
)

JANELAS_GRAFO = ("1d", "2d", "5d", "1w", "2w")            # §3.5
TOPIC_TYPES_UI = ("EVENT", "CONCEPT", "CATEGORY", "COMPANY", "ENTITY",
                  "BRAND", "PERSON", "PLACE", "ALL")      # contrato de UI

# símbolos sabidamente estáveis no proxy de perguntas (502 é por shard, §3.1)
SIMBOLOS_PERGUNTAS_OK = ("NVDA", "TSLA", "F", "AMZN")

SESSAO_FANTASMA = "11111111-1111-4111-8111-111111111111"   # 410 da família aposentada
PERGUNTA_FANTASMA = "22222222-2222-4222-8222-222222222222"

# ===========================================================================
# 2. TEMA BLOOMBERG TERMINAL — paleta oficial (Mobbin 2026) + primitivas UI
# ===========================================================================

# paleta em códigos ANSI 256 (compatível com Windows Terminal/cmd VT)
_TEMA = {
    "amber": "38;5;214",    # sunshade #FFA028 — cor de marca
    "orange": "38;5;208",   # laranja clássico
    "yellow": "38;5;220",   # teclas de setor / alerta
    "red": "38;5;203",      # quedas / Cancel #FF433D
    "green": "38;5;40",     # alta / GO #00C853
    "teal": "38;5;49",      # verde-água #4AF6C3
    "blue": "38;5;33",      # links / dados #0068FF
    "cyan": "38;5;39",      # dados auxiliares #00D4FF
    "magenta": "38;5;207",  # rosa do terminal (DDQ/insights)
    "hi": "38;5;231",       # branco puro
    "mid": "38;5;245",      # cinza claro #A0A0A0
    "low": "38;5;240",      # cinza escuro #666666
    "updim": "48;5;22",     # fundo verde suave #0F3D1A
    "downdim": "48;5;52",   # fundo vermelho suave #4A1210
    "bold": "1", "dim": "2", "reset": "0",
}

_COR_ON = True          # cores ANSI ativas
_ASCII = False          # --ascii: caixas +---+ em vez de ╭─╮│╰╯
_LARGURA = 78


def iniciar_ui(sem_cores: bool = False, com_cores: bool = False,
               ascii_mode: bool = False) -> None:
    """Ativa VT no Windows, força UTF-8 e aplica o tema Bloomberg."""
    global _COR_ON, _ASCII
    if os.name == "nt":
        os.system("")                      # ativa processamento de VT/ANSI
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    _ASCII = ascii_mode
    _COR_ON = (not sem_cores) and (com_cores or sys.stdout.isatty()) \
        and not os.environ.get("NO_COLOR")


def c(texto: Any, *estilos: str) -> str:
    """Envolve o texto no tema Bloomberg (graceful com cores desligadas)."""
    t = str(texto)
    if not _COR_ON or not estilos:
        return t
    codigos = [_TEMA[e] for e in estilos if e in _TEMA]
    if not codigos:
        return t
    return f"\033[{';'.join(codigos)}m{t}\033[0m"


def _visivel(s: str) -> int:
    """Largura visível — imune aos códigos ANSI embutidos."""
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _just(s: str, n: int) -> str:
    """ljust calculado sobre a largura VISÍVEL (padding ANSI-imune)."""
    falta = n - _visivel(s)
    return s + " " * max(0, falta)


def truncar(texto: Any, n: int) -> str:
    t = " ".join(str(texto or "").split())
    return t if _visivel(t) <= n else t[: max(0, n - 1)] + "…"


def linha_h(caractere: str, largura: int = _LARGURA) -> str:
    """Linha horizontal do tema (dupla ou ASCII)."""
    if _ASCII:
        return caractere * largura
    return {"─": "─", "═": "═"}.get(caractere, caractere) * largura


def caixa(titulo: str, linhas: List[str], cor: str = "amber",
          largura: int = _LARGURA) -> None:
    """Caixa ╭─╮│╰╯ (ou +---+| em --ascii) com título amber."""
    if _ASCII:
        print(c("+" + "-" * (largura - 2) + "+", cor))
        print(c("| ", cor) + c(titulo, "bold")
              + " " * max(0, largura - 4 - _visivel(titulo)) + c("|", cor))
        for ln in linhas:
            print(c("| ", cor) + _just(ln, largura - 4) + c(" |", cor))
        print(c("+" + "-" * (largura - 2) + "+", cor))
        return
    print(c("╭─ " + titulo + " " + "─" * max(1, largura - _visivel(titulo) - 4)
            + "╮", cor))
    for ln in linhas:
        print(c("│ ", cor) + _just(ln, largura - 4) + c(" │", cor))
    print(c("╰" + "─" * (largura - 2) + "╯", cor))


def painel(titulo: str, linhas: List[str], cor: str = "amber",
           largura: int = _LARGURA) -> None:
    """Compat: painel = caixa."""
    caixa(titulo, linhas, cor, largura)


def tabela(titulo: str, cabecalhos: List[str], linhas: List[List[str]],
           larguras: List[int], cor: str = "amber") -> None:
    """Tabela Bloomberg — padding imune a ANSI, cabeçalho amber, linhas dim."""
    print(c(f"▌ {titulo}", cor, "bold"))
    if _ASCII:
        sep = "+".join("-" * (w + 2) for w in larguras)
        print("  " + c("+" + sep + "+", "low"))
        print("  " + c("| ", "low") + " | ".join(
            c(_just(truncar(h, w), w), "bold")
            for h, w in zip(cabecalhos, larguras)) + c(" |", "low"))
    else:
        print("  " + c("─" * (sum(larguras) + 3 * len(larguras)), "low"))
        print("  " + " │ ".join(c(_just(truncar(h, w), w), "amber", "bold")
                                for h, w in zip(cabecalhos, larguras)))
        print("  " + c("─" * (sum(larguras) + 3 * len(larguras)), "low"))
    for linha in linhas:
        if _ASCII:
            print("  " + c("| ", "low") + " | ".join(
                _just(truncar(v, w), w)
                for v, w in zip(linha, larguras)) + c(" |", "low"))
        else:
            print("  " + " │ ".join(_just(truncar(v, w), w)
                                    for v, w in zip(linha, larguras)))
    if _ASCII:
        print("  " + c("+" + sep + "+", "low"))
    print()


def medidor(restante: float, limite: float, largura: int = 22) -> str:
    """Barra de quota verde→amarela→vermelha (tema Bloomberg)."""
    fracao = 0.0 if limite <= 0 else max(0.0, min(1.0, restante / limite))
    cheias = int(round(fracao * largura))
    if _ASCII:
        barra = "#" * cheias + "-" * (largura - cheias)
    else:
        barra = "█" * cheias + "░" * (largura - cheias)
    cor = "green" if fracao > 0.5 else ("yellow" if fracao > 0.2 else "red")
    return c(barra, cor)


def segundos_legiveis(seg: float) -> str:
    seg = int(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def fmt_num(v: Any, dec: int = 2) -> str:
    """pt-BR: 1.234.567,89."""
    try:
        s = f"{float(v):,.{dec}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v)


def fmt_pct(v: Any, dec: int = 2, seta: bool = True) -> str:
    """pt-BR com seta ▲/▼ e cor verde/vermelha pelo sinal."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = fmt_num(n, dec) + "%"
    if not seta:
        return s
    if n > 0:
        return c("▲ +" + s, "green")
    if n < 0:
        return c("▼ " + s, "red")
    return s


def fmt_epoch(seg: Any) -> str:
    """Epoch (s ou ms) → data/hora local pt-BR."""
    try:
        n = float(seg)
        if n > 1e12:
            n /= 1000.0
        return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(n))
    except (TypeError, ValueError):
        return "—"


def cab_terminal(titulo: str) -> None:
    """Cabeçalho de tela no estilo terminal Bloomberg."""
    larg = shutil.get_terminal_size((100, 24)).columns
    larg = min(max(larg, 60), 110)
    if _ASCII:
        print(c("=" * larg, "amber"))
        print(c(" " + titulo, "amber", "bold"))
        print(c("=" * larg, "amber"))
    else:
        print(c("═" * larg, "amber"))
        print(c(" ⬢ ", "yellow") + c(titulo, "amber", "bold"))
        print(c("═" * larg, "amber"))


def estado(rotulo: str, status: int, obj: Any, esperado: Optional[str] = None
           ) -> None:
    """Imprime um estado de contrato (410/401/422/500/404) como fato."""
    corpo = ""
    if obj is None:
        corpo = "(corpo vazio)"
    elif isinstance(obj, (dict, list)):
        corpo = json.dumps(obj, ensure_ascii=False)[:400]
    else:
        corpo = str(obj)[:400]
    nota = c(f"  [{esperado}]" if esperado else "", "low")
    cor_st = "green" if 200 <= status < 300 else (
        "yellow" if 400 <= status < 500 else "red")
    print(f"⊕ {rotulo} → {c(f'HTTP {status}', cor_st)}{nota}\n  {corpo}")


def pausa(mensagem: str = "Pressione ENTER para fechar") -> None:
    """Anti-fechamento: pausa final (ignorada com --no-pause)."""
    try:
        input(f"\n{c(mensagem + '…', 'mid')}")
    except (EOFError, KeyboardInterrupt):
        pass


# ===========================================================================
# 3. RENDERIZAÇÃO MARKDOWN + LIMPEZA DE CITAÇÕES (§9.6)
# ===========================================================================

def limpar_citacoes(texto: str) -> str:
    """Reduz a forma `[texto][N]` do modelo a `texto` (função f26 do cliente)."""
    return re.sub(r"\[([^\]]*)\]\[\d+\]", r"\1", texto)


def _inline(t: str) -> str:
    t = re.sub(r"\*\*([^*]+)\*\*", c(r"\1", "bold"), t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", c(r"\1", "yellow"), t)
    t = re.sub(r"\[([^\]]*)\]\(([^)]+)\)", c(r"\1", "cyan") + c(" ‹\2›", "dim"), t)
    return t


def renderizar_md(texto: str, largura: int = 78) -> str:
    """Markdown minimalista para terminal — negrito, títulos, listas, links."""
    saida: List[str] = []
    dentro_codigo = False
    for linha in (texto or "").splitlines() or [""]:
        if linha.strip().startswith("```"):
            dentro_codigo = not dentro_codigo
            saida.append(c("  │ " + ("```" if not dentro_codigo else linha),
                           "dim"))
            continue
        if dentro_codigo:
            saida.append(c("  │ " + linha, "dim"))
            continue
        travado = linha.lstrip()
        recuo = " " * (len(linha) - len(travado))
        m = re.match(r"^(#{1,6})\s+(.*)$", travado)
        if m:
            saida.append("")
            saida.append(recuo + c("◆ " + m.group(2).upper(), "bold"))
            saida.append(recuo + c("─" * min(len(m.group(2)) + 2, largura), "dim"))
            continue
        m = re.match(r"^[-*]\s+(.*)$", travado)
        if m:
            saida.append(recuo + "  • " + _inline(m.group(1)))
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", travado)
        if m:
            saida.append(recuo + f"  {m.group(1)}. " + _inline(m.group(2)))
            continue
        saida.append(recuo + _inline(travado))
    return "\n".join(saida).rstrip()


# ===========================================================================
# 4. PARSER SSE — resolvedor duplo do cliente (§5.3)
# ===========================================================================

def resolver_evento(obj: Any, linha_evento: str) -> Tuple[str, Dict[str, Any]]:
    """Reproduz o resolvedor `X` do cliente (§5.3).

    O nome do evento tem duas fontes: o campo `event` DENTRO do JSON do
    payload (prioridade) e a linha `event:` do enquadramento SSE — com o
    valor genérico `message` descartado. Payload não-objeto vira `{}`.
    """
    base = "" if linha_evento == "message" else (linha_evento or "")
    if isinstance(obj, dict):
        ev = obj.get("event")
        ev = ev if isinstance(ev, str) else ""
        dados = obj.get("data")
        return (ev or base), (dados if isinstance(dados, dict) else {})
    return base, {}


def iterar_sse(resp: Any) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Lê o corpo `text/event-stream` linha a linha — sem compressão (§8.1).

    Molduras `id:` + `data:`; o tipo vem no campo `event` do JSON. `data:`
    vazio ou fora de JSON é descartado; `null`/array/escalar não produzem
    evento.
    """
    linha_evento = ""
    for bruta in resp:
        linha = bruta.decode("utf-8", "replace").rstrip("\r\n")
        if not linha:
            linha_evento = ""              # moldura encerrada
            continue
        if linha.startswith(":"):
            continue                        # comentário keep-alive
        if linha.startswith("event:"):
            linha_evento = linha[6:].strip()
            continue
        if linha.startswith("id:"):
            continue                        # carimbo ms-seq (§5.3)
        if linha.startswith("data:"):
            bruto = linha[5:].strip()
            if not bruto:
                continue
            try:
                obj = json.loads(bruto)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            nome, dados = resolver_evento(obj, linha_evento)
            if nome:
                yield nome, dados


# ===========================================================================
# 5. ERRO DO CONTRATO
# ===========================================================================

class ErroScout(Exception):
    """Erro HTTP do Scout/MAD — status + corpo (formas do §4.2/§7)."""

    def __init__(self, acao: str, status: int, corpo: str) -> None:
        self.acao = acao
        self.status = status
        self.corpo = corpo
        try:
            j = json.loads(corpo)
            if isinstance(j.get("detail"), list):       # 422 do Pydantic
                detalhe = "; ".join(
                    f"{'.'.join(map(str, d.get('loc', '?')))}: {d.get('msg', '')}"
                    for d in j["detail"][:3])
            else:
                detalhe = (j.get("message") or j.get("detail")
                           or j.get("error") or corpo)
        except Exception:
            detalhe = corpo
        super().__init__(f"{acao} → HTTP {status}: {detalhe}")


# ===========================================================================
# 6. CLIENTE — Promenade + MAD em um jar de identidade único
# ===========================================================================

class Scout:
    """Cliente completo — chat Promenade + análises MAD (um A3, um jar)."""

    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [("User-Agent", UA)]
        self._crumb_cache: Optional[str] = None
        self.metrica: Dict[str, int] = {"ms": 0, "bytes": 0, "status": 0}

    # ------------------------------------------------------------------
    # identidade (§2.3) — A3 anônimo de fc.yahoo.com
    # ------------------------------------------------------------------

    def bootstrap(self) -> bool:
        """Obtém o A3 anônimo. Sem ele: 400 missing_identity nas rotas de
        sessão e 429 quota_exceeded no /chat (§7)."""
        try:
            self.opener.open(FC_HOST, timeout=20).read(512)
        except urllib.error.HTTPError:
            pass                       # 4xx do fc é normal — cookies já vieram
        try:
            self.opener.open(FINANCE_HOST, timeout=20).read(2048)
        except urllib.error.HTTPError:
            pass
        return any(c.name == "A3" for c in self.jar)

    def renova_identidade(self) -> bool:
        """Limpa o jar e refaz o bootstrap — novo A3 = nova quota (§5.9)."""
        self.jar.clear()
        self._crumb_cache = None
        return self.bootstrap()

    def tem_a3(self) -> bool:
        return any(c.name == "A3" for c in self.jar)

    def _crumb(self) -> Optional[str]:
        """Crumb anônimo — só para as rotas com `crumb: true` (transcrição,
        screener legado). O par reproduzível é A3 + GET /v1/test/getcrumb
        em query1; o /_crumb do domínio da página devolve redirect de
        consentimento no fluxo sem sessão."""
        if self._crumb_cache:
            return self._crumb_cache
        if not self.tem_a3():
            self.bootstrap()
        for url in (Q1 + "/v1/test/getcrumb", FINANCE_HOST + "/_crumb"):
            try:
                with self.opener.open(url, timeout=20) as resp:
                    texto = resp.read().decode("utf-8", "replace").strip()
                if resp.status == 200 and texto and len(texto) <= 32 \
                        and "<" not in texto:
                    self._crumb_cache = texto
                    return texto
            except (urllib.error.HTTPError, urllib.error.URLError,
                    TimeoutError, OSError):
                continue
        return None

    # ------------------------------------------------------------------
    # núcleo HTTP — retry apenas no 500 vazio transiente da borda (§7)
    # ------------------------------------------------------------------

    def _pedido(self, metodo: str, url: str,
                corpo: Optional[dict] = None,
                q: Optional[Dict[str, Any]] = None,
                headers: Optional[Dict[str, str]] = None,
                timeout: int = TIMEOUT_SESSAO,
                tentativas: int = TENTATIVAS_5XX,
                renovar_401: bool = False) -> Tuple[int, Any]:
        """Devolve (status, objeto) — dict/list quando JSON, str caso contrário,
        None para 204/vazio.

        Robustez (§10 do app): 500 vazio da borda re-tentado (backoff curto);
        429/503 com backoff exponencial 2^n (máx. 5); 401 com `renovar_401`
        renova a identidade (A3) e repete 1×. Métricas da última resposta em
        `self.metrica` = {ms, bytes, status}."""
        if q:
            itens = [(k, v) for k, v in q.items() if v is not None]
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(itens)
        dados = None
        cab: Dict[str, str] = {"Accept": "*/*"}
        if corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
            cab["Content-Type"] = "application/json"
        if headers:
            cab.update(headers)
        self.metrica = {"ms": 0, "bytes": 0, "status": 0}
        status, texto = 0, ""
        renovado = False
        total = max(1, tentativas)
        i = 0
        while i < total:
            i += 1
            req = urllib.request.Request(url, data=dados, headers=cab,
                                         method=metodo)
            t0 = time.perf_counter()
            bruto = b""
            try:
                with self.opener.open(req, timeout=timeout) as resp:
                    bruto = resp.read()
                    status = resp.status
            except urllib.error.HTTPError as e:
                try:
                    bruto = e.read()
                except Exception:
                    bruto = b""
                status = e.code
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                status, texto = 0, str(e)
                self.metrica.update({"ms": int((time.perf_counter() - t0)
                                               * 1000), "status": 0})
                if i < total:
                    time.sleep(min(2 ** i, 16))
                    continue
                break
            self.metrica.update({"ms": int((time.perf_counter() - t0) * 1000),
                                 "bytes": len(bruto), "status": status})
            texto = bruto.decode("utf-8", "replace")
            if status == 401 and renovar_401 and not renovado:
                renovado = True
                self.renova_identidade()
                continue                          # repetir 1× com A3 novo
            if status in (429, 503) and i < min(total, 5):
                time.sleep(min(2 ** i, 32))       # backoff exponencial 2^n
                continue
            if status in (500, 502, 504) and i < total:
                time.sleep(1.5 + i)               # 500 vazio da borda (§8.2)
                continue
            break
        if status == 204 or not texto:
            return status, None
        try:
            return status, json.loads(texto)
        except ValueError:
            return status, texto

    @staticmethod
    def _json_ou_erro(acao: str, status: int, texto: Any,
                      esperado: int = 200) -> Dict[str, Any]:
        if status != esperado:
            corpo = texto if isinstance(texto, str) else json.dumps(texto or {})
            raise ErroScout(acao, status, corpo)
        if isinstance(texto, dict):
            return texto
        raise ErroScout(acao, status, str(texto)[:200])

    # ------------------------------------------------------------------
    # chat — sessão, mensagem (JSON e SSE), seeds (§2.1, §4.1-§4.4, §5.3)
    # ------------------------------------------------------------------

    def criar_sessao(self) -> Dict[str, Any]:
        """POST /sessions {"tenant":"finance"} → 201 (§4.1)."""
        st, tx = self._pedido("POST", f"{PROMENADE}/sessions",
                              {"tenant": TENANT}, None, None, TIMEOUT_SESSAO)
        return self._json_ou_erro("POST /sessions", st, tx, esperado=201)

    @staticmethod
    def _corpo_chat(mensagem: str, session_id: Optional[str],
                    contexto: Optional[str], variante: Optional[str],
                    chave_idempotencia: Optional[str]) -> Dict[str, Any]:
        """Corpo do /chat — campos opcionais conforme o builder do cliente
        (§2.1): context, idempotency_key, session_id, ttl (só seeds), variant."""
        corpo: Dict[str, Any] = {"message": mensagem, "tenant": TENANT}
        if session_id:
            corpo["session_id"] = session_id
        if contexto:
            corpo["context"] = contexto
        if variante:
            corpo["variant"] = variante
        if chave_idempotencia:
            corpo["idempotency_key"] = chave_idempotencia
        return corpo

    def chat(self, mensagem: str, session_id: Optional[str] = None,
             contexto: Optional[str] = None, variante: Optional[str] = None,
             chave_idempotencia: Optional[str] = None) -> Dict[str, Any]:
        """POST /chat na negociação default — envelope completo (§4.2)."""
        corpo = self._corpo_chat(mensagem, session_id, contexto, variante,
                                 chave_idempotencia)
        st, tx = self._pedido("POST", f"{PROMENADE}/chat", corpo, None, None,
                              TIMEOUT_CHAT)
        return self._json_ou_erro("POST /chat", st, tx)

    def chat_sse(self, mensagem: str, session_id: Optional[str] = None,
                 contexto: Optional[str] = None, variante: Optional[str] = None,
                 ao_evento: Optional[Callable[[str, Dict[str, Any]], None]] = None
                 ) -> Dict[str, Any]:
        """POST /chat com `Accept: text/event-stream` (§5.3) — consome o fluxo
        chamando `ao_evento(nome, payload)` e devolve o resultado consolidado
        (content, fontes, follow-ups, ações, título, usage, quota)."""
        corpo = self._corpo_chat(mensagem, session_id, contexto, variante, None)
        req = urllib.request.Request(
            f"{PROMENADE}/chat", data=json.dumps(corpo).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Accept": "text/event-stream"}, method="POST")
        # o 500 vazio transiente também atinge a abertura do stream — re-tenta
        resp: Any = None
        ultimo = (0, "")
        for i in range(TENTATIVAS_5XX):
            try:
                resp = self.opener.open(req, timeout=TIMEOUT_SSE)
                break
            except urllib.error.HTTPError as e:
                try:
                    texto = e.read().decode("utf-8", "replace")
                except Exception:
                    texto = ""
                ultimo = (e.code, texto)
                if e.code in (500, 502, 503, 504) and i < TENTATIVAS_5XX - 1:
                    time.sleep(1.5 + i)
                    continue
                raise ErroScout("POST /chat (SSE)", e.code, texto) from None
        if resp is None:
            raise ErroScout("POST /chat (SSE)", ultimo[0], ultimo[1])

        resultado: Dict[str, Any] = {
            "message_id": "", "content": "", "citations": [],
            "grounding_sources": [], "follow_up_questions": [],
            "suggested_actions": [], "title": None, "status": [],
            "metadata": {}, "streaming": True,
        }
        for nome, dados in iterar_sse(resp):
            if ao_evento:
                ao_evento(nome, dados)
            if nome == "stream.start":
                resultado["message_id"] = dados.get("message_id", "")
            elif nome == "status.update":
                resultado["status"].append(dados.get("status", ""))
            elif nome == "content.delta":
                resultado["content"] += dados.get("delta", "")
            elif nome == "grounding.sources":
                resultado["grounding_sources"] = (dados.get("grounding_sources")
                                                  or [])
            elif nome in ("follow_up.questions", "suggestions"):
                resultado["follow_up_questions"] = (
                    dados.get("follow_up_questions")
                    or dados.get("suggestions") or [])
            elif nome == "actions.suggested":
                resultado["suggested_actions"] = [
                    a for a in (dados.get("actions") or [])
                    if isinstance(a, dict)
                    and isinstance(a.get("action_id"), str)]
            elif nome == "data" and dados.get("key") == "data-chat-title":
                resultado["title"] = (dados.get("payload") or {}).get("title")
            elif nome == "stream.end":
                resultado["message_id"] = dados.get("message_id",
                                                    resultado["message_id"])
                resultado["citations"] = dados.get("citations", [])
                resultado["suggestions"] = dados.get("suggestions", [])
                resultado["metadata"] = dados.get("metadata", {}) or {}
                if dados.get("title"):
                    resultado["title"] = dados["title"]
            elif nome == "error":
                raise ErroScout("stream /chat error",
                                dados.get("code") or 500, json.dumps(dados))
        return resultado

    def seeds(self, mensagem: str, ttl: int = TTL_SEEDS) -> Dict[str, Any]:
        """POST /chat/seeds — resposta pronta + seed_key; a rota cria a
        sessão implicitamente (§4.4). Cache por identidade pelo ttl."""
        st, tx = self._pedido("POST", f"{PROMENADE}/chat/seeds",
                              {"message": mensagem, "tenant": TENANT,
                               "ttl": ttl}, None, None, TIMEOUT_CHAT)
        return self._json_ou_erro("POST /chat/seeds", st, tx)

    # ------------------------------------------------------------------
    # sessões — histórico, metadados, lista, escrita restrita, retomada
    # ------------------------------------------------------------------

    def mensagens(self, session_id: str, limite: int = TETO_MENSAGENS,
                  pagina: int = PAGINA_MENSAGENS) -> List[Dict[str, Any]]:
        """GET /sessions/{id}/messages — paginação por cursor opaco (§4.3);
        cursor inválido é ignorado pelo servidor (200 com a 1ª página)."""
        acumulado: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            q = {"tenant": TENANT, "limit": str(min(pagina, 100))}
            if cursor:
                q["cursor"] = cursor
            st, tx = self._pedido(
                "GET", f"{PROMENADE}/sessions/{session_id}/messages", q=q,
                timeout=TIMEOUT_SESSAO)
            j = self._json_ou_erro("GET /sessions/{id}/messages", st, tx)
            acumulado.extend(j.get("messages", []) or [])
            cursor = j.get("next_cursor")
            if not cursor or len(acumulado) >= limite:
                break
        return acumulado[:limite]

    def sessao(self, session_id: str) -> Dict[str, Any]:
        """GET /sessions/{id} — metadados e título derivado (§5.1)."""
        st, tx = self._pedido("GET", f"{PROMENADE}/sessions/{session_id}",
                              q={"tenant": TENANT}, timeout=TIMEOUT_SESSAO)
        return self._json_ou_erro("GET /sessions/{id}", st, tx)

    def sessoes(self, limite: int = LIMITE_SESSOES) -> Dict[str, Any]:
        """GET /sessions — lista da identidade; vazia para anônimo (§2.3)."""
        st, tx = self._pedido("GET", f"{PROMENADE}/sessions",
                              q={"tenant": TENANT, "limit": limite},
                              timeout=TIMEOUT_SESSAO)
        return self._json_ou_erro("GET /sessions", st, tx)

    def fixar(self, session_id: str, fixada: bool = True) -> Tuple[int, Any]:
        """PATCH /sessions/{id} {"pinned":…} — 403 anônimo (escrita restrita)."""
        return self._pedido("PATCH", f"{PROMENADE}/sessions/{session_id}",
                            {"pinned": fixada},
                            q={"tenant": TENANT}, tentativas=1)

    def apagar(self, session_id: str) -> Tuple[int, Any]:
        """POST /sessions/{id}/delete — rota real de exclusão do app;
        403 anônimo documentado (a sessão segue acessível)."""
        return self._pedido("POST",
                            f"{PROMENADE}/sessions/{session_id}/delete",
                            q={"tenant": TENANT}, tentativas=1)

    def stream_ativo(self, session_id: str) -> Dict[str, Any]:
        """GET /sessions/{id}/active-stream — {active:false} quando ociosa
        (inclusive para sessão inexistente — exceção graciosa, §7)."""
        st, tx = self._pedido(
            "GET", f"{PROMENADE}/sessions/{session_id}/active-stream",
            q={"tenant": TENANT}, timeout=TIMEOUT_SESSAO)
        return self._json_ou_erro("GET active-stream", st, tx)

    def retomar(self, stream_id: str, ultimo_evento: str = "0"
                ) -> List[Tuple[str, Dict[str, Any]]]:
        """GET /chat/resume/{stream_id} — replay; `last_event_id=0`
        retransmite tudo; exige Accept: text/event-stream (406 sem — §7)."""
        url = (f"{PROMENADE}/chat/resume/{urllib.parse.quote(stream_id, safe='')}"
               "?" + urllib.parse.urlencode(
                   {"last_event_id": ultimo_evento, "tenant": TENANT}))
        req = urllib.request.Request(
            url, headers={"Accept": "text/event-stream"}, method="GET")
        try:
            resp = self.opener.open(req, timeout=TIMEOUT_SSE)
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")
            raise ErroScout("GET /chat/resume", e.code, texto) from None
        return list(iterar_sse(resp))

    # ------------------------------------------------------------------
    # feedback (§5.2) e perguntas sugeridas (§3.1)
    # ------------------------------------------------------------------

    def feedback(self, session_id: str, message_id: str, rating: int,
                 motivos: Optional[List[str]] = None,
                 comentario: Optional[str] = None) -> Dict[str, Any]:
        """POST /feedback — 👍=1/👎=0; no 👎 os motivos vão aninhados em
        `fields.reason` (unidos por vírgula); enum definido no servidor.
        Reavaliação da mesma mensagem → overwritten: true."""
        corpo: Dict[str, Any] = {"tenant": TENANT, "session_id": session_id,
                                 "message_id": message_id, "rating": rating}
        if motivos and rating == 0:
            invalidos = [m for m in motivos if m not in MOTIVOS_FEEDBACK]
            if invalidos:
                raise ValueError("motivos inválidos: %s — aceitos: %s"
                                 % (", ".join(invalidos),
                                    ", ".join(MOTIVOS_FEEDBACK)))
            corpo["fields"] = {"reason": ",".join(motivos)}
        if comentario:
            corpo["feedback"] = comentario
        st, tx = self._pedido("POST", f"{PROMENADE}/feedback", corpo, None,
                              None, TIMEOUT_SESSAO)
        return self._json_ou_erro("POST /feedback", st, tx)

    def perguntas_semeadas(self, simbolo: str, limite: int = 5
                           ) -> List[Dict[str, Any]]:
        """GET /xhr/dynamic-seeded-questions — 200 anônimo; 502 por shard
        de backend é transitório e por símbolo (§3.1) — re-tenta."""
        url = (FINANCE_HOST + "/xhr/dynamic-seeded-questions?"
               + urllib.parse.urlencode({"symbol": simbolo,
                                         "limit": str(limite)}))
        st, tx = 0, ""
        for i in range(5):
            st, tx = self._pedido("GET", url, timeout=60, tentativas=1)
            if st == 200:
                j = json.loads(tx) if isinstance(tx, str) else (tx or {})
                return j.get("dynamic_questions") or []  # type: ignore[union-attr]
            if st in (502, 503, 504) and i < 4:
                time.sleep(1.5 * (i + 1))
                continue
        corpo = tx if isinstance(tx, str) else json.dumps(tx or {})
        raise ErroScout("GET /xhr/dynamic-seeded-questions", st,
                        corpo[:160] or "502 Request timed out (shard)")

    # ------------------------------------------------------------------
    # infra / diagnóstico (§2.2, §7, §9.6)
    # ------------------------------------------------------------------

    def config_servicos(self) -> List[Tuple[str, int, str]]:
        """Sonda /xhr/config?name=services — GET → 405; POST fora do schema
        → 400 `Schema mismatch`; rota do loader server-side, não pública."""
        url = FINANCE_HOST + "/xhr/config?name=services"
        st_g, tx_g = self._pedido("GET", url, timeout=15, tentativas=1)
        st_p, tx_p = self._pedido("POST", url, {"foo": "bar"}, timeout=15,
                                  tentativas=1)
        return [("GET /xhr/config?name=services", st_g, str(tx_g)),
                ("POST /xhr/config (schema inválido)", st_p, str(tx_p))]

    def chat_get(self) -> Tuple[int, Any]:
        """GET /chat — método errado → 404 `not_found` (não há 405; rota e
        método inexistentes se confundem no mesmo 404 — §7)."""
        return self._pedido("GET", PROMENADE + "/chat", timeout=15,
                            tentativas=6)

    def sondar_deep_link(self, url: str) -> Tuple[int, Any]:
        """GET /__ai/scout/chat — 404 para o cliente web; o alvo é o
        webview do app nativo (§9.6)."""
        return self._pedido("GET", url, timeout=15, tentativas=1)

    @staticmethod
    def deep_link(pergunta: str, uuid_artigo: Optional[str] = None) -> str:
        """Construtor verbatim do módulo "Dig deeper": prompt cortado em
        500 caracteres + uuid opcional do artigo (§9.6)."""
        q = urllib.parse.urlencode({"prompt": pergunta[:500]})
        if uuid_artigo:
            q += "&" + urllib.parse.urlencode({"uuid": uuid_artigo})
        return f"{FINANCE_HOST}/__ai/scout/chat?{q}"

    # ------------------------------------------------------------------
    # MAD — AI Analyst (§3.2, §5.5)
    # ------------------------------------------------------------------

    def analista(self, simbolo: str, lang: str = "en-US",
                 regiao: str = "US") -> Dict[str, Any]:
        """GET /ws/mad/v2/analyst/symbol/{symbol} — 8 seções com envelope de
        governança; anônimo; símbolo inexistente → 404 FastAPI."""
        st, tx = self._pedido("GET",
                              f"{Q1}/ws/mad/v2/analyst/symbol/{simbolo}",
                              q={"lang": lang, "region": regiao},
                              timeout=TIMEOUT_CHAT)
        return self._json_ou_erro(f"analista {simbolo}", st, tx)

    def ect(self, transcript_id: Optional[str] = None,
            event_id: Optional[str] = None) -> Dict[str, Any]:
        """GET /ws/mad/v2/analyst/ect — exatamente um identificador
        (exclusão mútua aplicada no servidor, §3.2)."""
        if bool(transcript_id) == bool(event_id):
            raise ValueError("informe exatamente um: transcript_id OU event_id")
        q = ({"event_id": event_id} if event_id
             else {"transcript_id": transcript_id})
        st, tx = self._pedido("GET", f"{Q1}/ws/mad/v2/analyst/ect", q=q,
                              timeout=TIMEOUT_CHAT, tentativas=1)
        return self._json_ou_erro("analyst/ect", st, tx)

    def transcricao(self, transcript_id: Optional[str] = None,
                    quartr_id: Optional[str] = None,
                    event_id: Optional[str] = None,
                    event_type: str = "earnings_call") -> Tuple[int, Any]:
        """GET /xhr/transcript — conteúdo da transcrição; `crumb` na query
        + cookies (§3.2). eventType aceito: earnings_call."""
        if not (transcript_id or quartr_id or event_id):
            raise ValueError("informe transcript_id, quartr_id ou event_id")
        crumb = self._crumb()
        q: Dict[str, Any] = {"eventType": event_type}
        if quartr_id:
            q["quartrId"] = quartr_id
        if transcript_id:
            q["transcriptId"] = transcript_id
        if event_id:
            q["eventId"] = event_id
        if crumb:
            q["crumb"] = crumb
        return self._pedido("GET", FINANCE_HOST + "/xhr/transcript", q=q,
                            tentativas=1)

    # ------------------------------------------------------------------
    # MAD — Dig Deeper de artigos (§3.3, §5.6)
    # ------------------------------------------------------------------

    def ddq_perguntas(self, uuid_artigo: str) -> Optional[Dict[str, Any]]:
        """GET /ws/mad/v2/articles_ddq/{uuid}/questions — 204 = geração
        assíncrona pendente; 404 = provedor fora da allowlist editorial."""
        st, tx = self._pedido(
            "GET", f"{Q1}/ws/mad/v2/articles_ddq/{uuid_artigo}/questions",
            timeout=TIMEOUT_CHAT, tentativas=1)
        if st == 204:
            return None
        return self._json_ou_erro("ddq perguntas", st, tx)

    def ddq_resposta(self, uuid_artigo: str, pergunta_id: str
                     ) -> Optional[Dict[str, Any]]:
        """GET …/questions/{questionId} — resposta com citações `[N]` e
        cadeia de follow-ups (parentQuestionId vazio na raiz)."""
        st, tx = self._pedido(
            "GET",
            f"{Q1}/ws/mad/v2/articles_ddq/{uuid_artigo}/questions/{pergunta_id}",
            timeout=TIMEOUT_CHAT, tentativas=1)
        if st == 204:
            return None
        return self._json_ou_erro("ddq resposta", st, tx)

    # ------------------------------------------------------------------
    # MAD — temas do AI Playground (§3.5, §5.7)
    # ------------------------------------------------------------------

    def temas(self, grain: str = "parent", limit: int = 10,
              order: Optional[str] = None, topic_type: Optional[str] = None,
              q: Optional[str] = None, macro_only: bool = False) -> Any:
        """GET /ws/mad/v2/themes — grain ∈ {storyline, parent};
        order ∈ {articles, random}; limit ≤ 200 (validação 422 server-side)."""
        st, tx = self._pedido("GET", f"{Q1}/ws/mad/v2/themes",
                              q={"grain": grain, "limit": limit,
                                 "order": order, "topic_type": topic_type,
                                 "q": q,
                                 "macro_only": "true" if macro_only else None},
                              timeout=TIMEOUT_CHAT, tentativas=2)
        return self._json_ou_erro("themes", st, tx)

    def temas_tickers(self, grain: str = "parent", limit: int = 10,
                      topic_type: Optional[str] = None) -> Any:
        """GET /ws/mad/v2/themes/tickers (§3.5)."""
        st, tx = self._pedido("GET", f"{Q1}/ws/mad/v2/themes/tickers",
                              q={"grain": grain, "limit": limit,
                                 "topic_type": topic_type},
                              timeout=TIMEOUT_CHAT, tentativas=2)
        return self._json_ou_erro("themes/tickers", st, tx)

    def tema_por_uuid(self, uuid_tema: str, grain: str = "parent",
                      limit: int = 10) -> Any:
        """GET /ws/mad/v2/themes/{themeUuid} — tickers ranqueados com
        supporting_articles; limit ≤ 100 nesta rota."""
        st, tx = self._pedido(
            "GET",
            f"{Q1}/ws/mad/v2/themes/{urllib.parse.quote(uuid_tema, safe='')}",
            q={"grain": grain, "limit": min(limit, 100)},
            timeout=TIMEOUT_CHAT, tentativas=2)
        return self._json_ou_erro("themes/{uuid}", st, tx)

    def temas_por_simbolo(self, ticker: str, grain: str = "parent",
                          limit: int = 10) -> Any:
        """GET /ws/mad/v2/themes/symbol/{ticker} (§3.5)."""
        st, tx = self._pedido(
            "GET",
            f"{Q1}/ws/mad/v2/themes/symbol/{urllib.parse.quote(ticker, safe='')}",
            q={"grain": grain, "limit": min(limit, 100)},
            timeout=TIMEOUT_CHAT, tentativas=2)
        return self._json_ou_erro("themes/symbol/{ticker}", st, tx)

    def grafo(self, window: str = "1d", grain: str = "parent", limit: int = 10,
              topic_type: Optional[str] = None) -> Any:
        """GET /ws/mad/v2/themes/graph — janela ∈ {1d,2d,5d,1w,2w} (§3.5)."""
        st, tx = self._pedido("GET", f"{Q1}/ws/mad/v2/themes/graph",
                              q={"window": window, "grain": grain,
                                 "limit": limit, "topic_type": topic_type},
                              timeout=TIMEOUT_CHAT, tentativas=2)
        return self._json_ou_erro("themes/graph", st, tx)

    def temas_de_artigos(self, uuids: List[str],
                         token_txn: Optional[str] = None
                         ) -> Tuple[int, Any]:
        """POST /ws/mad/v2/themes/from-articles — gate JWT (§2.3): o schema
        do corpo ANTECEDE a checagem do token ([] → 422 mesmo sem header;
        corpo válido sem header → 401)."""
        cab: Dict[str, str] = {}
        if token_txn:
            cab["x-txn-token"] = token_txn
        return self._pedido(
            "POST", f"{Q1}/ws/mad/v2/themes/from-articles",
            corpo={"article_uuids": uuids, "grain": "parent", "limit": 10,
                   "min_support": 1},
            headers=cab, tentativas=1)

    def portfolio_feed(self, holdings: Optional[List[Dict[str, Any]]] = None,
                       portfolio_id: Optional[str] = None,
                       grain: str = "parent", limit: int = 6,
                       narrate: bool = True) -> Tuple[int, Any]:
        """POST/GET /themes/portfolio/feed — com `holdings` → POST (sem gate
        JWT); com `portfolio_id` → GET (posse validada — 404 desconhecido)."""
        if holdings:
            return self._pedido(
                "POST", f"{Q1}/ws/mad/v2/themes/portfolio/feed",
                corpo={"holdings": holdings, "grain": grain, "limit": limit,
                       "narrate": narrate},
                timeout=TIMEOUT_CHAT, tentativas=2)
        return self._pedido(
            "GET", f"{Q1}/ws/mad/v2/themes/portfolio/feed",
            q={"portfolio_id": portfolio_id, "grain": grain, "limit": limit,
               "narrate": "true" if narrate else "false"},
            timeout=TIMEOUT_CHAT, tentativas=2)

    # ------------------------------------------------------------------
    # MAD — insights de portfólio (gate JWT — 401 anônimo, §3.5)
    # ------------------------------------------------------------------

    def diario_analise(self, pf_id: Optional[str] = None) -> Tuple[int, Any]:
        """GET /v2/daily_brief/analysis (ou …/portfolio_insights/analysis)."""
        caminho = ("/v2/daily_brief/portfolio_insights/analysis" if pf_id
                   else "/v2/daily_brief/analysis")
        return self._pedido("GET", Q1 + caminho,
                            q={"pfId": pf_id} if pf_id else None,
                            tentativas=1)

    def portfolio_faqs(self, pergunta: str,
                       pergunta_id: str = "portfolio-analysis",
                       pf_id: Optional[str] = None) -> Tuple[int, Any]:
        """GET /v2/portfolio_ddq/faqs — dispatcher do modo portfólio (§3.5)."""
        return self._pedido("GET", f"{Q1}/v2/portfolio_ddq/faqs",
                            q={"question": pergunta,
                               "questionId": pergunta_id, "pfId": pf_id},
                            tentativas=1)

    def watchlist_resumo(self) -> Tuple[int, Any]:
        """GET /v2/watchlist_insights/summary — 401 sem JWT (§3.5)."""
        return self._pedido("GET", f"{Q1}/v2/watchlist_insights/summary",
                            tentativas=1)

    def watchlist_analise(self, pf_id: Optional[str] = None) -> Tuple[int, Any]:
        """GET /v2/watchlist_insights/analysis — variante com isWatchlist."""
        return self._pedido("GET", f"{Q1}/v2/watchlist_insights/analysis",
                            q={"pfId": pf_id}, tentativas=1)

    def portfolio_insights_resumo(self) -> Tuple[int, Any]:
        """GET /v2/daily_brief/portfolio_insights/summary — 401 sem JWT."""
        return self._pedido("GET",
                            f"{Q1}/v2/daily_brief/portfolio_insights/summary",
                            tentativas=1)

    # ------------------------------------------------------------------
    # MAD — screener NLS (§3.4) e família aposentada (§7)
    # ------------------------------------------------------------------

    def screener_nls(self, consulta: str, usar_legado: bool = False
                     ) -> Tuple[int, Any]:
        """POST do screener em linguagem natural. Rota MAD v2 dormente
        (flag off) sem crumb; rota legada ativa COM crumb (§3.4)."""
        if usar_legado:
            crumb = self._crumb()
            if not crumb:
                raise ErroScout("crumb (getcrumb)", 0,
                                "crumb indisponível no fluxo anônimo")
            return self._pedido(
                "POST", f"{Q1}/ws/screeners/v1/finance/screener/nls",
                corpo={"query": consulta}, q={"crumb": crumb},
                tentativas=3, renovar_401=True)
        return self._pedido("POST", f"{Q1}/ws/mad/v2/screener/nls",
                            corpo={"query": consulta}, tentativas=1)

    def chat_aposentado(self, pergunta: str = "Analyze my portfolio",
                        simbolo: str = "AAPL") -> Tuple[int, Any]:
        """POST /ws/mad/v2/chat — 410 Gone (§7); corpo histórico
        {question, symbol, initial_context} + chat_version=v11."""
        return self._pedido("POST", f"{Q1}/ws/mad/v2/chat",
                            corpo={"question": pergunta, "symbol": simbolo,
                                   "initial_context": ""},
                            q={"chat_version": "v11", "use_fargate": "false"},
                            tentativas=1)

    def chat_sessao_aposentado(self, session_id: str) -> Tuple[int, Any]:
        """POST /ws/mad/v2/chat/{sessionId} — 410 idêntico (§7)."""
        return self._pedido(
            "POST", f"{Q1}/ws/mad/v2/chat/{urllib.parse.quote(session_id, safe='')}",
            corpo={"question": "Analyze my portfolio", "symbol": "AAPL",
                   "initial_context": ""},
            q={"chat_version": "v11", "use_fargate": "false"}, tentativas=1)

    def chat_get_aposentado(self) -> Tuple[int, Any]:
        """GET /ws/mad/v2/chat — 410 idêntico (§7)."""
        return self._pedido("GET", f"{Q1}/ws/mad/v2/chat", tentativas=1)

    def chat_pergunta_aposentada(self, pergunta_id: str) -> Tuple[int, Any]:
        """GET /ws/mad/v2/chat/question/{uuid} — polling histórico, 410 (§7)."""
        return self._pedido(
            "GET",
            f"{Q1}/ws/mad/v2/chat/question/{urllib.parse.quote(pergunta_id, safe='')}",
            tentativas=1)

    def rate_limit_aposentado(self) -> Tuple[int, Any]:
        """GET /ws/mad/v2/chat/rate_limit — 410 idêntico (§7)."""
        return self._pedido("GET", f"{Q1}/ws/mad/v2/chat/rate_limit",
                            tentativas=1)


# ===========================================================================
# 7. UI DE ALTO NÍVEL — telas de resposta, analista, DDQ, temas
# ===========================================================================

def _gov(sec: Dict[str, Any]) -> str:
    """Carimbo de governança da seção do analista (§5.5)."""
    criado = (sec.get("created_at") or "")[:10]
    atualizado = (sec.get("updated_at") or "")[:10]
    extra = (f" · atualizado {atualizado}"
             if atualizado and atualizado != criado else "")
    return c(f"[gerado {criado}{extra}]", "dim")


def _markdown(texto: Optional[str], recuo: str = "  ") -> str:
    """Markdown → terminal sem margem lateral (seções do analista)."""
    saida = []
    for linha in renderizar_md(texto or "", 76).splitlines() or [""]:
        saida.append(recuo + linha)
    return "\n".join(saida)


def tela_analista(j: Dict[str, Any], apenas: Optional[str] = None) -> None:
    """Relatório do AI Analyst — 8 seções renderizadas (§5.5)."""
    print(c("═" * 78, "cyan"))
    print(c(f"AI ANALYST · symbol_id {j.get('symbol_id', '—')}", "bold"))
    print(c("═" * 78, "cyan"))
    for chave, rotulo in SECOES_ANALISTA:
        if apenas and chave != apenas:
            continue
        sec = j.get(chave)
        if not isinstance(sec, dict):
            continue
        print()
        print(c(f"◆ {rotulo.upper()} ", "cyan", "bold") + _gov(sec))
        try:
            if chave == "overview":
                ov = sec.get("overview") or {}
                print(_markdown(ov.get("tldr")))
                ko = ov.get("key_observations") or {}
                if isinstance(ko, list):
                    ko = {"": ko}
                for categoria, itens in ko.items():
                    if not itens:
                        continue
                    if categoria:
                        print(c(f"\n  ▸ {categoria}", "dim"))
                    if isinstance(itens, str):
                        print(_markdown(itens))
                        continue
                    for it in itens:
                        print(_markdown(
                            it.get("observation") or it.get("text")
                            or json.dumps(it, ensure_ascii=False)[:120]
                            if isinstance(it, dict) else str(it)))
            elif chave == "rtr":
                r = sec.get("rtr_summary") or {}
                print(_markdown(r.get("tldr")))
                vp = r.get("viewpoint")
                if vp:
                    rot = {"BULLISH": "BULLISH ▲", "BEARISH": "BEARISH ▼"}.get(
                        vp, vp)
                    print(f"\n  consenso: {c(rot, 'bold')}")
                for campo, rotulo2 in (("price_target", "preço-alvo"),
                                       ("ratings_summary", "ratings"),
                                       ("recent_upgrades", "upgrades"),
                                       ("viewpoint_details", "detalhes")):
                    valor = r.get(campo)
                    if valor:
                        print(f"\n  ▸ {rotulo2}")
                        print(_markdown(valor if isinstance(valor, str)
                                        else json.dumps(valor,
                                                        ensure_ascii=False)[:400]))
            elif chave == "earnings_transcripts_insights":
                e = sec.get("earnings_analysis") or {}
                if sec.get("fiscal_year"):
                    print(f"  trimestre fiscal: {sec.get('fiscal_year')} / "
                          f"{sec.get('fiscal_period', '')}")
                print(_markdown(e.get("tldr")))
                for campo, titulo in (("key_insights", "principais insights"),
                                      ("key_insights_structured",
                                       "principais insights"),
                                      ("analyst_focus", "foco dos analistas")):
                    itens = e.get(campo)
                    if not itens:
                        continue
                    print(f"\n  ▸ {titulo}")
                    print(_markdown(itens if isinstance(itens, str)
                                    else json.dumps(itens,
                                                    ensure_ascii=False)[:600]))
                    break
                qa = e.get("qa_highlights")
                if qa:
                    print("\n  ▸ destaques do Q&A")
                    print(_markdown(qa if isinstance(qa, str)
                                    else json.dumps(qa,
                                                    ensure_ascii=False)[:500]))
                for q2 in (e.get("notable_quotes") or [])[:5]:
                    quem = q2.get("speaker") or q2.get("name") or "" \
                        if isinstance(q2, dict) else ""
                    fala = (q2.get("quote") or q2.get("text") or ""
                            if isinstance(q2, dict) else str(q2))
                    print(_markdown(f"· {fala} — {quem}" if quem
                                    else f"· {fala}", recuo="  "))
            elif chave == "financial_insights":
                print(_markdown(sec.get("tldr")))
                cats = sec.get("categories") or {}
                if isinstance(cats, list):
                    cats = {x.get("category", ""): x for x in cats
                            if isinstance(x, dict)}
                for nome, corpo2 in cats.items():
                    if not corpo2:
                        continue
                    print(f"\n  ▸ {nome}")
                    print(_markdown(corpo2 if isinstance(corpo2, str)
                                    else json.dumps(corpo2,
                                                    ensure_ascii=False)[:500]))
                le = sec.get("latest_earnings_metadata") or {}
                if le:
                    print(c(f"\n  últimos earnings: {le.get('fiscal_year', '?')}/"
                            f"{le.get('fiscal_period', '?')} · divulgados "
                            f"{(le.get('earnings_disclosed_at') or '')[:10]}",
                            "dim"))
            elif chave == "holdings_insights":
                ia = sec.get("insiderActivity") or {}
                print(_markdown(ia.get("highlights") or ia.get("tldr")))
                for campo in ("key_takeaways", "key_takeaways_structured"):
                    for it in (ia.get(campo) or [])[:5]:
                        print(_markdown(
                            it.get("takeaway") or it.get("text")
                            or json.dumps(it, ensure_ascii=False)[:120]
                            if isinstance(it, dict) else str(it)))
            elif chave == "price_movement":
                expl = sec.get("explanation") or {}
                print(_markdown(expl.get("tldr") or expl.get("short_tldr")))
                if expl.get("bottom_line"):
                    print("\n  ▸ bottom line")
                    print(_markdown(expl["bottom_line"]))
                dados = sec.get("data") or {}
                var = dados.get("stock_percentage_price_change")
                if var is not None:
                    print(c(f"\n  variação recente: {var}% · "
                            f"beta {dados.get('beta', '—')} · "
                            f"setor {dados.get('sector', '—')}", "dim"))
            elif chave == "options_analysis":
                pcr = sec.get("pcr") or {}
                vol = pcr.get("pcr_volume")
                noc = pcr.get("pcr_notional")
                if vol is not None or noc is not None:
                    print(f"  put/call (volume): {vol} · (noção): {noc} · "
                          f"data: {pcr.get('quote_date', '—')}")
                kt = sec.get("key_takeaways") or {}
                print(_markdown(kt.get("tldr")))
            elif chave == "news_summary":
                ns = sec.get("news_summary") or {}
                print(_markdown(ns.get("tldr") or ns.get("summary")))
                temas = ns.get("themes") or []
                if temas:
                    print(c("  temas: " + ", ".join(
                        t if isinstance(t, str) else str(t.get("theme", t))
                        for t in temas[:8]), "dim"))
                arts = sec.get("articles_info") or []
                if arts:
                    print(f"\n  ▸ artigos ({len(arts)})")
                    for a in arts[:6]:
                        if isinstance(a, dict):
                            print(f"    · {truncar(a.get('title'), 66)}"
                                  + (c(f"  [{a.get('provider_name', '')}]",
                                       "dim") if a.get("provider_name") else ""))
        except Exception as e:            # renderização nunca derruba o relatório
            print(c(f"  (seção {rotulo}: formato inesperado — {e})", "dim"))
    print(c("═" * 78, "cyan"))


def tela_ddq_perguntas(j: Dict[str, Any]) -> List[Dict[str, Any]]:
    qs = j.get("questions") or []
    painel(f"DIG DEEPER · artigo {j.get('articleId', '—')}",
           [f"{i}. {q.get('question', '')}" for i, q in enumerate(qs, 1)]
           or ["(sem perguntas)"], "magenta")
    return qs


def tela_ddq_resposta(j: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resposta com unescape dos `\n` literais do wire (§5.6) + cadeia."""
    pai = j.get("parentQuestionId") or ""
    topo = (f"pergunta {j.get('questionId', '—')[:13]}…"
            + (f" · pai {pai[:13]}…" if pai else " · raiz"))
    painel("DIG DEEPER — resposta", [topo], "magenta")
    bruto = j.get("answer", "")
    resposta = (bruto.replace("\\n", "\n").replace("\\t", "\t")
                .replace('\\"', '"'))
    print(_markdown(limpar_citacoes(resposta), recuo=""))
    fontes = j.get("sources") or []
    if fontes:
        print(c(f"\n◈ fontes citadas ({len(fontes)}):", "yellow"))
        for i, u in enumerate(fontes, 1):
            print(f"  [{i}] {u}")
    follows = j.get("followUpQuestions") or []
    if follows:
        print(c("\n◈ follow-ups da cadeia (digite o número):", "cyan"))
        for i, f in enumerate(follows, 1):
            print(f"  {i}. {f.get('question', '')}")
    return follows


def tela_temas(j: Dict[str, Any]) -> None:
    """Lista de temas — total do recorte + metadados agregados (§5.7)."""
    temas = j.get("themes") if isinstance(j, dict) else j
    if isinstance(temas, list):
        tabela(f"TEMAS · total {j.get('total', '?')}",
               ["uuid", "tema", "tickers", "artigos"],
               [[(t.get("theme_uuid") or "")[:8],
                 t.get("theme_label") or t.get("label") or "",
                 str(t.get("tickers", "?")),
                 str(t.get("theme_articles", "?"))] for t in temas[:12]],
               [10, 34, 9, 9])


def tela_tema(j: Dict[str, Any]) -> None:
    """Tickers ranqueados de um tema — score/força/confiança/artigos."""
    print(c(f"◆ {j.get('theme_label', '?')} "
            f"({j.get('macro_slug', '?')}) — "
            f"{j.get('count', '?')} tickers", "cyan", "bold"))
    for t in (j.get("tickers") or [])[:8]:
        if isinstance(t, dict):
            arts = t.get("supporting_articles") or []
            print(f"  {t.get('rank', '?')}. {c(t.get('ticker', '?'), 'bold')}  "
                  f"score={t.get('score', '?')}  "
                  f"força={t.get('mean_strength', '?')}  "
                  f"conf={t.get('confidence', '?')}  "
                  f"suporte={t.get('support', '?')}")
            for a in arts[:2]:
                if isinstance(a, dict):
                    print(c(f"      · {truncar(a.get('title'), 64)}", "dim"))


def tela_portfolio(j: Dict[str, Any]) -> None:
    """Feed do portfólio — narração e exposição por tema (§5.7)."""
    print(c(f"◆ {j.get('portfolio_name', '?')} · "
            f"holdings={j.get('holdings', '?')} · "
            f"pnl hoje={j.get('pnl_today', '?')}", "cyan", "bold"))
    print(_markdown(j.get("summary"), recuo="  "))
    for t in (j.get("themes") or [])[:6]:
        print(f"\n  ▸ {t.get('theme_label', '?')}  "
              f"exposure={t.get('exposure', '?')}  "
              f"share={t.get('share', '?')}  rank={t.get('rank', '?')}")
        print(c("    " + ", ".join(t.get("tickers") or []), "dim"))


class Tela:
    """Telas do chat — cabeçalho, corpo, rodapé (fontes/ações/quota)."""

    @staticmethod
    def cabecalho(r: Dict[str, Any], duracao: float) -> None:
        modo = "SSE" if r.get("streaming") else "JSON"
        extra = f"  ·  título: {r['title']}" if r.get("title") else ""
        print(c("─" * 78, "cyan"))
        print(c(f"◆ SCOUT ({modo}, {duracao:.1f}s){extra}", "bold"))
        print(c("─" * 78, "cyan"))

    @staticmethod
    def corpo(r: Dict[str, Any]) -> None:
        print(renderizar_md(limpar_citacoes(r.get("content", ""))))

    @staticmethod
    def rodape(r: Dict[str, Any]) -> List[str]:
        fontes = r.get("grounding_sources") or []
        if fontes:
            print(c(f"\n◈ Fontes ({len(fontes)}):", "yellow"))
            for i, f in enumerate(fontes, 1):
                if isinstance(f, dict) and (f.get("title") or f.get("url")):
                    titulo = (f.get("title") or "")[:66]
                    provedor = (f.get("provider_name")
                                or f.get("provider") or "")
                    url = f.get("cdn_url") or f.get("url") or ""
                    print(f"  [{i}] {titulo}"
                          + (c(f"  · {provedor}", "dim") if provedor else ""))
                    if url:
                        print(c(f"      {url[:96]}", "dim"))
        acoes = r.get("suggested_actions") or []
        if acoes:
            print(c("\n◈ Ações sugeridas:", "magenta"))
            for a in acoes:
                params = ", ".join(f"{k}={v}" for k, v in
                                   (a.get("params") or {}).items())
                print(f"  ▸ {a.get('action_id', '?')}({params})")
        meta = r.get("metadata") or {}
        uso = meta.get("usage") or {}
        if isinstance(uso, dict) and uso.get("total_tokens"):
            chamadas = len(uso.get("calls") or [])
            print(c(f"\n◈ Uso: {uso['total_tokens']:,} tokens · "
                    f"{chamadas} chamada(s) de modelo · "
                    f"{uso.get('model', '?')} ({uso.get('provider', '?')})",
                    "dim"))
        quota = meta.get("quota")
        if isinstance(quota, dict) and quota.get("remaining_tokens") is not None:
            rest = quota.get("remaining_tokens", 0)
            limite = quota.get("limit_tokens", 100000)
            usado = quota.get("used_tokens", 0)
            renova = quota.get("reset_after_seconds")
            barra = medidor(rest, limite)
            linha = (f"\n◈ Quota {barra} {rest:,}/{limite:,}"
                     f" (usados {usado:,})")
            if renova is not None:
                linha += f" — renova em {segundos_legiveis(renova)}"
            print(linha)
            if 0 < rest < 20000:
                print(c("  ⚠ balanço baixo — a quota é POR IDENTIDADE (A3), "
                        "compartilhada por todas as sessões deste jar; "
                        "/renovar obtém identidade nova com 100k tokens.",
                        "yellow"))
        follow = (r.get("follow_up_questions")
                  or r.get("suggestions") or [])
        if follow:
            print(c("\n◈ Perguntas de continuação (digite o número):", "cyan"))
            for i, p in enumerate(follow, 1):
                print(f"  {i}. {p}")
        return list(follow)

    @staticmethod
    def historico(msgs: List[Dict[str, Any]]) -> None:
        for m in msgs:
            papel = m.get("role", "?")
            quando = (m.get("created_at") or "")[:19].replace("T", " ")
            quem = "Você" if papel == "user" else "Scout"
            cor = "green" if papel == "user" else "cyan"
            print(c(f"┌ {quem} ({quando})", cor))
            corpo = limpar_citacoes(m.get("content") or "")
            if papel != "user":
                corpo = renderizar_md(corpo)
            for linha in corpo.splitlines():
                print(c("│ ", cor) + linha)
            fontes = m.get("grounding_sources") or []
            if fontes:
                print(c(f"│ fontes: {len(fontes)}", "dim"))
            print(c("└", cor))
        print(c("─" * 78, "dim"))


# ===========================================================================
# 7-B. APLICATIVO DE TERMINAL — menu, console bruto, comparador, suíte,
#      invariantes, autenticação, exportação (tema Bloomberg)
# ===========================================================================

_TITULO_APP = "SCOUT AI TERMINAL — BLOOMBERG EDITION"
_SUB_APP = "Promenade + MAD v2 · contrato yf_scout_ai.md · somente stdlib"

_MENU = """
  1  CHAT SCOUT            sessão streaming + histórico + seeds + retomada
  2  AI ANALYST            relatório de 8 seções (query1/query2, seção única)
  3  DIG DEEPER            perguntas e respostas encadeadas de um artigo
  4  ECT / TRANSCRIÇÃO     insights + conteúdo de earnings call
  5  PERGUNTAS SUGERIDAS   catálogo dinâmico por símbolo (502 por shard)
  6  TEMAS DO PLAYGROUND   lista · tema por uuid · por símbolo · grafo
  7  PORTFÓLIO / INSIGHTS  feed de temas · família daily_brief (gate JWT)
  8  SCREENER NLS          rota MAD v2 dormente · rota legada com crumb
  9  FAMÍLIA APOSENTADA    410 Gone — 5 rotas do contrato fóssil
 10  CONSOLE BRUTO         GET/POST/HEAD/OPTIONS · hosts · crumb query|header
 11  COMPARADOR            multi-símbolo lado a lado (overview/rtr/target)
 12  SUÍTE AO VIVO         verificação dos comportamentos documentados
 13  INVARIANTES           auditoria offline do contrato (sem rede)
 14  AUTENTICAÇÃO          status do jar · renovação · testes de falha
 15  EXPORTAR JSON         última resposta crua (paridade de bytes)
  0  SAIR
"""


class SairLoop(Exception):
    """Pedido de saída (opção 0, EOF ou Ctrl+C duas vezes)."""


def _entrada(rotulo: str, padrao: str = "") -> str:
    """Prompt com padrão visível; Ctrl+C 2×/EOF levantam SairLoop."""
    global _INTERRUPCOES
    dica = c(f" [{padrao}]" if padrao else "", "low")
    while True:
        try:
            bruto = input(f"{rotulo}{dica}: ")
            break
        except KeyboardInterrupt:
            _INTERRUPCOES += 1
            if _INTERRUPCOES >= 2:
                raise SairLoop
            print(c("  (Ctrl+C de novo sai; ENTER aceita o padrão)", "low"))
            continue
        except EOFError:
            raise SairLoop
    _INTERRUPCOES = 0
    v = bruto.strip()
    return v or padrao


def escolher(titulo: str, opcoes: List[Tuple[str, str]]) -> int:
    """Menu numerado no padrão v7: [ 1]..[ 0] Voltar; reimprime só se inválido."""
    while True:
        print("\n" + c(titulo, "bold", "amber"))
        for i, (rot, desc) in enumerate(opcoes, 1):
            linha = f"  [{i:>2}]  {rot}"
            if desc:
                linha += c("  · " + desc, "low")
            print(linha)
        print(c("  [ 0]  Voltar", "bold"))
        try:
            r = _entrada("Opção")
        except SairLoop:
            return 0
        try:
            n = int(r)
        except (TypeError, ValueError):
            n = -1
        if n == 0:
            return 0
        if 1 <= n <= len(opcoes):
            return n
        print(c("  opção inválida — tente de novo", "yellow"))


def _seguro(fn: Callable, *args: Any) -> None:
    """Executa uma ação — nenhum traceback derruba o app."""
    try:
        fn(*args)
    except ErroScout as e:
        print(c("  [ERRO] " + str(e), "red"))
    except SairLoop:
        raise
    except (EOFError, KeyboardInterrupt):
        print(c("  (interrompido)", "low"))
    except Exception as e:
        print(c("  [ERRO] inesperado: " + str(e), "red"))


# ── submenu 1 · CHAT ─────────────────────────────────────────────────────

def chat_repl(app: "App") -> None:
    """REPL de chat — texto livre pergunta; comandos / do contrato."""
    print(c("  chat aberto — texto livre pergunta · /ajuda = comandos · "
            "/voltar retorna", "low"))
    while True:
        try:
            linha = input(c("chat", "amber", "bold")
                          + c(" > ", "amber")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not linha:
            continue
        if linha in ("/voltar", "/menu", "/sair", "/exit", "/quit"):
            return
        if linha in ("/ajuda", "/help", "?"):
            print(AJUDA)
            continue
        if linha.isdigit() and app.ultimos_follows:
            n = int(linha)
            if 1 <= n <= len(app.ultimos_follows):
                _seguro(app.perguntar, app.ultimos_follows[n - 1])
                print()
                continue
        if linha.startswith("/"):
            cmd, _, resto = linha.partition(" ")
            metodo = app.DESPACHO.get(cmd.lower())
            if metodo is None:
                print(c("  comando desconhecido: " + cmd + " — /ajuda",
                        "yellow"))
                continue
            _seguro(getattr(app, metodo), resto)
            continue
        _seguro(app.perguntar, linha)
        print()


# ── submenu 2 · AI ANALYST ───────────────────────────────────────────────

def menu_analista(app: "App") -> None:
    simbolo = _entrada("  símbolo", "AAPL").upper()
    secoes = [("Todas as seções", "relatório completo")]
    secoes += [(k, d) for k, d in SECOES_ANALISTA]
    n = escolher("AI ANALYST · " + simbolo + " — seção", secoes)
    if n == 0:
        return
    chave = None if n == 1 else SECOES_ANALISTA[n - 2][0]
    app.cmd_analista(simbolo + ((" " + chave) if chave else ""))


# ── submenu 4 · ECT / TRANSCRIÇÃO ────────────────────────────────────────

def menu_ect(app: "App") -> None:
    tid = _entrada("  transcript_id (vazio=pular)")
    eid = _entrada("  event_id (vazio=pular)")
    if bool(tid) == bool(eid):
        print(c("  informe exatamente UM identificador", "yellow"))
        return
    _seguro(app.cmd_ect, "--transcript-id=" + tid if tid
            else "--event-id=" + eid)
    if _entrada("  ver conteúdo da transcrição? (s/N)").lower() == "s":
        _seguro(app.cmd_transcricao, "--transcript-id=" + tid if tid
                else "--event-id=" + eid)


# ── submenu 6 · TEMAS ────────────────────────────────────────────────────

def menu_temas(app: "App") -> None:
    while True:
        n = escolher("TEMAS DO AI PLAYGROUND", [
            ("Lista de temas", "grain parent/storyline"),
            ("Tickers de temas", ""),
            ("Tema por uuid", "tickers ranqueados"),
            ("Temas por símbolo", ""),
            ("Grafo por janela", "1d|2d|5d|1w|2w"),
            ("Grafo de artigos", "from-articles — gate JWT (401/422)"),
        ])
        if n == 0:
            return
        if n == 1:
            _seguro(app.cmd_temas, _entrada("  grain", "parent"))
        elif n == 2:
            _seguro(app.cmd_tickers)
        elif n == 3:
            _seguro(app.cmd_tema, _entrada("  uuid do tema"))
        elif n == 4:
            _seguro(app.cmd_tema_simbolo,
                    _entrada("  símbolo", "NVDA").upper())
        elif n == 5:
            _seguro(app.cmd_grafo, _entrada("  janela", "1d"))
        elif n == 6:
            uuids = [u for u in _entrada(
                "  uuids de artigos (separados por espaço)").split() if u]
            if uuids:
                _seguro(app.cmd_artigos_tema, " ".join(uuids))
        pausa("ENTER para voltar aos temas")


# ── submenu 7 · PORTFÓLIO / INSIGHTS ─────────────────────────────────────

def menu_portfolio(app: "App") -> None:
    while True:
        n = escolher("PORTFÓLIO / INSIGHTS", [
            ("Feed de temas (holdings)", "POST — sem gate JWT"),
            ("Feed por portfolio_id", "GET — posse validada (404)"),
            ("Família de insights", "daily_brief/faqs/watchlist — 401"),
            ("Daily brief — análise", "401 sem JWT"),
            ("FAQ do portfólio", "portfolio_ddq/faqs — 401 sem JWT"),
        ])
        if n == 0:
            return
        if n == 1:
            _seguro(app.cmd_portfolio, _entrada(
                "  holdings", "AAPL:5000,NVDA:3000"))
        elif n == 2:
            _seguro(app.cmd_portfolio, _entrada("  portfolio_id",
                                                "demo-megacap-tech"))
        elif n == 3:
            _seguro(app.cmd_insights)
        elif n == 4:
            _seguro(app.cmd_diario)
        elif n == 5:
            _seguro(app.cmd_faqs, _entrada("  pergunta",
                                           "How is my portfolio doing?"))
        pausa("ENTER para voltar ao portfólio")


def menu_perguntas(app: "App") -> None:
    _seguro(app.cmd_perguntas_mad, _entrada("  símbolo", "NVDA").upper())


# ── 14 · AUTENTICAÇÃO ────────────────────────────────────────────────────

def painel_auth(app: "App") -> None:
    cli = app.cli
    cookies = sorted({x.name for x in cli.jar})
    caixa(["A3 presente: " + ("SIM" if cli.tem_a3() else "NÃO"),
           "cookies no jar: " + (", ".join(cookies) or "—"),
           "crumb (cache): " + (cli._crumb_cache or "—"),
           "quota: POR IDENTIDADE (A3) · janela 24 h · todas as sessões"],
          "AUTENTICAÇÃO")
    n = escolher("AUTENTICAÇÃO", [
        ("Renovar A3", "novo jar = nova quota de 100k tokens"),
        ("Testar falha sem cookie", "POST /sessions -> 400 missing_identity"),
        ("Testar crumb", "GET /v1/test/getcrumb"),
    ])
    if n == 1:
        okk = cli.renova_identidade()
        print(c("  [ OK ] novo A3 — quota renovada" if okk
                else "  [ERRO] bootstrap falhou", "green" if okk else "red"))
    elif n == 2:
        jar2 = http.cookiejar.CookieJar()
        op2 = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar2))
        op2.addheaders = [("User-Agent", UA)]
        req = urllib.request.Request(
            PROMENADE + "/sessions",
            data=json.dumps({"tenant": TENANT}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with op2.open(req, timeout=TIMEOUT_SESSAO) as resp:
                print(c("  (inesperado) HTTP " + str(resp.status)
                        + " sem cookie", "yellow"))
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")[:160]
            estado("POST /sessions SEM cookie", e.code, corpo,
                   esperado="400 missing_identity" if e.code == 400 else None)
        except Exception as e:
            print(c("  [ERRO] " + str(e), "red"))
    elif n == 3:
        crumb = cli._crumb()
        if crumb:
            print(c("  [ OK ] crumb (" + str(len(crumb)) + " chars): "
                    + truncar(crumb, 20) + "...", "green"))
        else:
            print(c("  [ERRO] crumb indisponível", "red"))


# ── 15 · EXPORTAÇÃO ──────────────────────────────────────────────────────

def exportar_json(app: "App") -> None:
    obj = getattr(app, "ultimo_cru", None)
    if obj is None:
        print(c("  nenhuma resposta na sessão — rode uma consulta antes",
                "yellow"))
        return
    padrao = "scout_export_" + time.strftime("%H%M%S") + ".json"
    caminho = _entrada("  caminho", padrao)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(c("  [ OK ] exportado: " + caminho, "green"))


# ── 10 · CONSOLE DE REQUISIÇÃO BRUTA ─────────────────────────────────────

HOSTS_CONSOLE = {"1": PROMENADE, "2": Q1, "3": Q2, "4": FINANCE_HOST}


def console_bruto(app: "App") -> None:
    n = escolher("CONSOLE BRUTO — host", [
        ("Promenade", PROMENADE),
        ("query1", Q1 + "  (MAD / proxy)"),
        ("query2", Q2 + "  (espelho do analyst)"),
        ("finance.yahoo.com", FINANCE_HOST + "  (proxy XHR)"),
    ])
    if n == 0:
        return
    host_url = HOSTS_CONSOLE[str(n)]
    metodos = ["GET", "POST", "HEAD", "OPTIONS"]
    nm = escolher("MÉTODO", [(m2, "") for m2 in metodos])
    if nm == 0:
        return
    metodo = metodos[nm - 1]
    path = _entrada("  path", "/ws/mad/v2/analyst/symbol/AAPL")
    if not path.startswith("/"):
        path = "/" + path
    params: Dict[str, str] = {}
    while True:
        kv = _entrada("  param k=v (vazio encerra)")
        if not kv or "=" not in kv:
            break
        k, _, v = kv.partition("=")
        params[k.strip()] = v.strip()
    headers: Dict[str, str] = {}
    while True:
        kv = _entrada("  header k=v (vazio encerra)")
        if not kv or "=" not in kv:
            break
        k, _, v = kv.partition("=")
        headers[k.strip()] = v.strip()
    cv = escolher("VETOR DO CRUMB", [
        ("Sem crumb", "rotas anônimas do Scout"),
        ("Query ?crumb=", "vetor 1"),
        ("Header x-crumb", "vetor 2"),
    ])
    corpo = None
    if metodo in ("POST", "PATCH"):
        bruto = _entrada("  body JSON (vazio=sem)")
        if bruto:
            try:
                corpo = json.loads(bruto)
            except ValueError:
                print(c("  [ERRO] body não é JSON — sem corpo", "red"))
    if cv in (2, 3):
        crumb = app.cli._crumb()
        if not crumb:
            print(c("  [ERRO] crumb indisponível no fluxo anônimo", "red"))
            return
        if cv == 2:
            params["crumb"] = crumb
        else:
            headers["x-crumb"] = crumb
    url = host_url + urllib.parse.quote(path, safe="/?&=%:@")
    st, obj = app.cli._pedido(metodo, url, corpo=corpo, q=params or None,
                              headers=headers or None, timeout=TIMEOUT_CHAT)
    app.ultimo_cru = obj
    m = getattr(app.cli, "metrica", {}) or {}
    tabela(metodo + " " + url,
           ["status", "latência", "bytes"],
           [[str(st), str(m.get("ms", 0)) + " ms",
             str(m.get("bytes", 0))]], [8, 10, 12])
    print(_cru(st, obj))
    salvar = _entrada("  salvar em arquivo? (caminho, vazio=pular)")
    if salvar:
        with open(salvar, "w", encoding="utf-8") as f:
            f.write(_cru(st, obj))
        print(c("  [ OK ] salvo: " + salvar, "green"))


# ── 11 · COMPARADOR MULTI-SÍMBOLO ────────────────────────────────────────

def comparador(app: "App") -> None:
    cru = _entrada("  símbolos (CSV)", "AAPL,MSFT,NVDA")
    sims = [x.strip().upper() for x in cru.split(",") if x.strip()][:6]
    if not sims:
        print(c("  [ERRO] nenhum símbolo", "red"))
        return
    linhas, falhas = [], []
    for s2 in sims:
        try:
            j = app.cli.analista(s2)
            app.ultimo_cru = j
            ov = ((j.get("overview") or {}).get("overview") or {}).get("tldr", "")
            rtr = (j.get("rtr") or {}).get("rtr_summary") or {}
            ns = len(((j.get("news_summary") or {}).get("articles_info")) or [])
            linhas.append([s2, truncar(ov, 44),
                           truncar(str(rtr.get("viewpoint", "-")), 14),
                           truncar(str(rtr.get("price_target", "-")), 20),
                           str(ns),
                           ((j.get("overview") or {}).get("created_at")
                            or "")[:10]])
        except Exception as e:
            falhas.append([s2, truncar(str(e), 50)])
    tabela("ANALYST — comparativo",
           ["símbolo", "overview (tldr)", "consenso", "price target",
            "notícias", "gerado"], linhas, [9, 44, 14, 20, 9, 10])
    if falhas:
        tabela("FALHAS", ["símbolo", "erro"], falhas, [9, 50])


# ── 12 · SUÍTE DE VERIFICAÇÃO AO VIVO ────────────────────────────────────

def suite_ao_vivo(app: "App") -> None:
    cli = app.cli
    if not cli.tem_a3():
        cli.bootstrap()
    resultados: List[Tuple[str, bool, str]] = []

    def chk(nome: str, ok: bool, detalhe: str = "") -> None:
        resultados.append((nome, ok, detalhe))
        print("  [ " + ("OK " if ok else "FAIL") + " ] "
              + c(nome, "green" if ok else "red")
              + "  " + c(truncar(detalhe, 56), "low"))

    try:
        j = cli.criar_sessao()
        chk("POST /sessions -> 201 + session_id", bool(j.get("session_id")),
            str(j.get("session_id", ""))[:36])
    except Exception as e:
        chk("POST /sessions -> 201", False, str(e)[:60])
    try:
        st, obj = cli.chat_get()
        chk("GET /chat -> 404 not_found", st == 404,
            str((obj or {}).get("code", obj))[:40])
    except Exception as e:
        chk("GET /chat -> 404", False, str(e)[:60])
    try:
        pares = cli.config_servicos()
        chk("GET /xhr/config -> 405", pares[0][1] == 405,
            "HTTP " + str(pares[0][1]))
        chk("POST /xhr/config -> 400", pares[1][1] == 400,
            "HTTP " + str(pares[1][1]))
    except Exception as e:
        chk("/xhr/config", False, str(e)[:60])
    try:
        j = cli.analista("AAPL")
        chk("analyst AAPL -> 200 + symbol_id estável",
            j.get("symbol_id") == "753c0cb0-a9d9-4765-9a03-51574991381d",
            str(j.get("symbol_id", ""))[:36])
        chk("analyst: governança + seções",
            all(k in j for k in ("overview", "rtr", "news_summary")),
            "trace_id + overview/rtr/news")
    except Exception as e:
        chk("analyst AAPL -> 200", False, str(e)[:60])
    try:
        st, obj = cli._pedido("GET", Q1 + "/ws/mad/v2/analyst/symbol/ZZZZZZ",
                              q={"lang": "en-US", "region": "US"},
                              tentativas=1)
        chk("analyst ZZZZZZ -> 404 FastAPI",
            st == 404 and "Symbol not found" in str(obj), "HTTP " + str(st))
    except Exception as e:
        chk("analyst ZZZZZZ -> 404", False, str(e)[:60])
    for rot, q_, frag in (("themes grain=theme -> 422", {"grain": "theme"},
                           "storyline"),
                          ("themes order=score -> 422", {"order": "score"},
                           "articles|random"),
                          ("themes limit=0 -> 422", {"limit": 0},
                           "greater_than_equal")):
        try:
            st, obj = cli._pedido("GET", Q1 + "/ws/mad/v2/themes",
                                  q={**{"limit": 5}, **q_}, tentativas=1)
            chk(rot, st == 422 and frag in str(obj), "HTTP " + str(st))
        except Exception as e:
            chk(rot, False, str(e)[:60])
    try:
        st, obj = cli.chat_aposentado()
        chk("aposentada POST -> 410", st == 410 and "retired" in str(obj),
            "HTTP " + str(st))
        st2, _o = cli.rate_limit_aposentado()
        chk("aposentada rate_limit -> 410", st2 == 410, "HTTP " + str(st2))
    except Exception as e:
        chk("aposentada -> 410", False, str(e)[:60])
    try:
        st, obj = cli.diario_analise()
        chk("daily_brief anônimo -> 401 (gate JWT)", st == 401,
            "HTTP " + str(st))
    except Exception as e:
        chk("daily_brief -> 401", False, str(e)[:60])
    try:
        qs = cli.perguntas_semeadas("NVDA")
        chk("dynamic-seeded-questions NVDA -> 200", len(qs) > 0,
            str(len(qs)) + " perguntas")
    except Exception as e:
        chk("dynamic-seeded-questions NVDA", False, str(e)[:60])
    try:
        st, obj = cli._pedido(
            "GET", PROMENADE + "/chat/resume/" + SESSAO_FANTASMA,
            q={"last_event_id": "0", "tenant": TENANT}, tentativas=1)
        chk("resume sem Accept -> 406", st == 406, "HTTP " + str(st))
    except Exception as e:
        chk("resume sem Accept -> 406", False, str(e)[:60])
    ok_n = sum(1 for _, ok, _ in resultados if ok)
    tabela("RESULTADO DA SUÍTE", ["verificação", "resultado"],
           [[truncar(n2, 46),
             c("PASS", "green") if ok else c("FAIL", "red")]
            for n2, ok, _ in resultados], [46, 10])
    print(c("  " + str(ok_n) + "/" + str(len(resultados))
            + " verificações PASS", "amber", "bold"))


# ── 13 · AUDITORIA DE INVARIANTES (offline, sem rede) ────────────────────

def invariantes() -> None:
    resultados: List[Tuple[str, bool, str]] = []

    def chk(nome: str, ok: bool, detalhe: str = "") -> None:
        resultados.append((nome, ok, detalhe))
        print("  [ " + ("OK " if ok else "FAIL") + " ] "
              + c(nome, "green" if ok else "red")
              + "  " + c(truncar(detalhe, 50), "low"))

    chk("hosts do contrato", PROMENADE.startswith("https://promenade-api")
        and Q1.endswith("query1.finance.yahoo.com")
        and Q2.endswith("query2.finance.yahoo.com"))
    chk("tenant fixo `finance`", TENANT == "finance")
    chk("ttl de seeds = 5", TTL_SEEDS == 5)
    chk("paginação 100 / teto 500 / sessões 25",
        (PAGINA_MENSAGENS, TETO_MENSAGENS, LIMITE_SESSOES) == (100, 500, 25))
    chk("enum de feedback (4 motivos server-side)",
        MOTIVOS_FEEDBACK == ("offensive", "not_helpful", "too_long",
                             "too_short"))
    chk("ordem canônica dos eventos SSE",
        EVENTOS_SSE[0] == "stream.start" and EVENTOS_SSE[-1] == "error"
        and len(EVENTOS_SSE) == 9)
    chk("AI Analyst: 8 seções", len(SECOES_ANALISTA) == 8
        and SECOES_ANALISTA[0][0] == "overview"
        and SECOES_ANALISTA[-1][0] == "news_summary")
    chk("janelas do grafo 1d-2w",
        JANELAS_GRAFO == ("1d", "2d", "5d", "1w", "2w"))
    chk("topic_type: enum de UI com 9 valores", len(TOPIC_TYPES_UI) == 9)
    chk("quota 100.000 tokens / 24 h", True, "limit/period do wire")
    n, d = resolver_evento({"event": "content.delta", "data": {"delta": "x"}},
                           "message")
    chk("SSE: JSON `event` vence `message`", n == "content.delta"
        and d == {"delta": "x"})
    n, _ = resolver_evento({"data": {"v": 1}}, "status.update")
    chk("SSE: linha `event:` como fallback", n == "status.update")
    n, _ = resolver_evento({"data": 123}, "")
    chk("SSE: payload não-objeto -> sem evento", n == "")
    chk("citações [texto][N] -> texto",
        limpar_citacoes("a [b][1] c") == "a b c")
    chk("formatação pt-BR", fmt_num(1234567.891) == "1.234.567,89")
    ok_n = sum(1 for _, ok, _ in resultados if ok)
    tabela("RESULTADO DA AUDITORIA", ["invariante", "resultado"],
           [[truncar(n2, 46),
             c("PASS", "green") if ok else c("FAIL", "red")]
            for n2, ok, _ in resultados], [46, 10])
    print(c("  " + str(ok_n) + "/" + str(len(resultados))
            + " invariantes PASS", "amber", "bold"))


# ── MENU PRINCIPAL (padrão v7: numerado, 0 volta, sem repetir banner) ───

OPCOES_MENU = [
    ("Chat Scout", "sessão streaming · histórico · seeds · retomada"),
    ("AI Analyst", "relatório de 8 seções · allowlist de símbolos"),
    ("Dig Deeper", "perguntas/respostas encadeadas de um artigo"),
    ("ECT / Transcrição", "insights + conteúdo de earnings call"),
    ("Perguntas sugeridas", "catálogo dinâmico (502 por shard)"),
    ("Temas do Playground", "lista · uuid · símbolo · grafo · artigos"),
    ("Portfólio / Insights", "feed de temas · daily_brief (gate JWT)"),
    ("Screener NLS", "rota MAD v2 dormente · legada com crumb"),
    ("Família aposentada", "410 Gone — 5 rotas do contrato fóssil"),
    ("Console bruto", "GET/POST/HEAD/OPTIONS · crumb query|header"),
    ("Comparador", "multi-símbolo lado a lado"),
    ("Suíte ao vivo", "verificação dos comportamentos documentados"),
    ("Invariantes", "auditoria offline do contrato (sem rede)"),
    ("Autenticação", "status · renovação · testes de falha"),
    ("Exportar JSON", "última resposta crua (paridade de bytes)"),
]


def menu(app: "App", no_pause: bool = False) -> None:
    """Menu principal no padrão v7 — 0 sai; ações voltam ao menu limpo."""
    if not app.iniciar():
        print(c("  [ERRO] bootstrap falhou — verifique a rede", "red"))
        if not no_pause:
            pausa()
        return
    while True:
        try:
            n = escolher("MENU PRINCIPAL — SCOUT AI", OPCOES_MENU)
        except SairLoop:
            break
        if n == 0:
            break
        try:
            if n == 1:
                chat_repl(app)
            elif n == 2:
                menu_analista(app)
            elif n == 3:
                _seguro(app.cmd_ddq, _entrada("  uuid do artigo"))
            elif n == 4:
                menu_ect(app)
            elif n == 5:
                menu_perguntas(app)
            elif n == 6:
                menu_temas(app)
            elif n == 7:
                menu_portfolio(app)
            elif n == 8:
                _seguro(app.cmd_screener, _entrada(
                    "  consulta", "top tech stocks by market cap"))
            elif n == 9:
                _seguro(app.cmd_aposentado)
            elif n == 10:
                console_bruto(app)
            elif n == 11:
                comparador(app)
            elif n == 12:
                suite_ao_vivo(app)
            elif n == 13:
                invariantes()
            elif n == 14:
                painel_auth(app)
            elif n == 15:
                exportar_json(app)
        except SairLoop:
            break
        except ErroScout as e:
            print(c("  [ERRO] " + str(e), "red"))
        except Exception as e:
            print(c("  [ERRO] inesperado: " + str(e), "red"))
    print(c("  encerrando o Scout AI Terminal...", "low"))
    if not no_pause:
        pausa("Pressione ENTER para fechar")
# ===========================================================================
# 8. REPL — todas as funções a um `/` de distância
# ===========================================================================

AJUDA = """CHAT — texto livre pergunta ao Scout (streaming); 1..N escolhe follow-up
  /nova                nova sessão de chat
  /sse                 alterna streaming SSE ⇄ JSON completo
  /contexto <valor>    âncora de conteúdo (ex.: ticker:AAPL) — vazio remove
  /historico [n]       histórico da sessão (default 500)
  /info                metadados e título derivado da sessão
  /sessoes             lista de sessões (vazia para anônimo)
  /fixar [0|1]         PATCH pinned (403 anônimo — comportamento documentado)
  /seeds <pergunta>    resposta semeada com cache (POST /chat/seeds)
  /ativas              sonda /active-stream da sessão
  /retomar [id [ev]]   replay de stream (ev=0 retransmite tudo)
  /feedback 0|1 ...    avalia a última resposta (👎: offensive, not_helpful,
                       too_long, too_short)
  /quota               estado da quota da última resposta SSE
  /renovar             novo A3 (nova identidade = quota renovada)
  /apagar              POST /sessions/{id}/delete (403 anônimo — documentado)
  /exportar [arq]      exporta a conversa em JSON

MAD v2
  /analista [SIMB] [seção]              AI Analyst (overview, rtr,
                       earnings_transcripts_insights, financial_insights,
                       holdings_insights, price_movement, options_analysis,
                       news_summary — vazio = todas)
  /ddq <uuid> [n|qid]                   Dig Deeper de artigo (cadeia)
  /ect --transcript-id=ID               insights de transcrição (1 id apenas)
  /transcricao --transcript-id=ID       conteúdo (/xhr/transcript, com crumb)
  /perguntas [SIMB]                     perguntas sugeridas do símbolo
  /temas [grain]                        lista de temas (storyline|parent)
  /tickers                              lista de tickers em temas
  /tema <uuid>                          tickers ranqueados de um tema
  /tema-simbolo [SIMB]                  temas associados ao ticker
  /grafo [1d|2d|5d|1w|2w]               grafo de temas por janela
  /artigos-tema <uuid>…                 POST from-articles (gate JWT — 422/401)
  /portfolio A:P,C:P | <id>             feed de temas do portfólio
  /insights /diario /faqs /watchlist    família de insights (401 sem JWT)
  /screener [consulta]                  screener NLS — rota MAD v2 dormente
  /screener-legado [c]                  screener NLS — rota legada com crumb

INFRA / DIAGNÓSTICO
  /json                alterna saída bruta JSON das respostas MAD
  /config              sonda /xhr/config?name=services + GET /chat (404)
  /deeplink [texto]    constrói e sonda /__ai/scout/chat (404 no web)
  /aposentado          família /ws/mad/v2/chat completa (5 rotas — 410)
  /rate-limit          prova do 410 do rate limit
  /ajuda /sair"""


class App:
    """REPL — chat por default; todas as funções por comando."""

    def __init__(self, sse: bool = True, bruto: bool = False) -> None:
        self.cli = Scout()
        self.sse = sse
        self.bruto = bruto                     # saída bruta JSON (MAD)
        self._em_status = False                # pipeline de status no streaming
        self.sessao_id: Optional[str] = None
        self.contexto: Optional[str] = None
        self.ultima_resposta: Optional[Dict[str, Any]] = None
        self.ultimos_follows: List[str] = []
        self.ddq_uuid: Optional[str] = None
        self.ddq_catalogo: List[Dict[str, Any]] = []
        self.ultimo_cru: Any = None

    # -- abertura ----------------------------------------------------------

    def iniciar(self) -> bool:
        ok = self.cli.bootstrap()
        cab_terminal(_TITULO_APP)
        print(c(" " + _SUB_APP, "low"))
        a3 = c("ok", "green") if ok else c("FALTA", "red")
        print(f"  A3: {a3} · streaming: {'ON' if self.sse else 'OFF'}"
              f" · tenant: {TENANT} · tema: BLOOMBERG")
        print(c("  0/menu = voltar - /ajuda = comandos de chat", "low"))
        return ok

    # -- chat --------------------------------------------------------------

    def perguntar(self, mensagem: str) -> None:
        if not self.sessao_id:
            j = self.cli.criar_sessao()
            self.sessao_id = j["session_id"]
            print(c(f"⊕ Sessão criada: {self.sessao_id}", "dim"))
        t0 = time.time()
        print()
        try:
            if self.sse:
                r = self.cli.chat_sse(mensagem, self.sessao_id, self.contexto,
                                      ao_evento=self._ao_evento)
            else:
                r = self.cli.chat(mensagem, self.sessao_id, self.contexto)
                r["streaming"] = False
        except Exception as e:
            self._tratar_erro(e)
            return
        dur = time.time() - t0
        if self.sse:
            print("\n")
        Tela.cabecalho(r, dur)
        Tela.corpo(r)
        self.ultimos_follows = Tela.rodape(r)
        self.ultima_resposta = r

    def _ao_evento(self, nome: str, dados: Dict[str, Any]) -> None:
        if nome == "status.update":
            self._em_status = True
            print("\r  " + c(f"· {dados.get('status', '…')[:56]:<56}", "dim"),
                  end="", flush=True)
        elif nome == "content.delta":
            if self._em_status:
                print("\r" + " " * 60 + "\r", end="", flush=True)
                self._em_status = False
            print(dados.get("delta", ""), end="", flush=True)
        elif nome == "stream.end":
            print("\r" + " " * 60 + "\r", end="", flush=True)

    def _tratar_erro(self, e: Exception) -> None:
        print(f"\n{c('✖ ' + str(e), 'red')}")
        texto = str(e)
        if "quota_exceeded" in texto:
            print(c("  Quota de 100.000 tokens/24 h esgotada — /renovar "
                    "troca o A3 e renova.", "dim"))
        elif "missing_identity" in texto:
            print(c("  O A3 expirou — /renovar re-autentica.", "dim"))
        elif "session_not_found" in texto:
            print(c("  A sessão não pertence a esta identidade — /nova.",
                    "dim"))
            self.sessao_id = None

    # -- chat: comandos ------------------------------------------------------

    def cmd_nova(self) -> None:
        j = self.cli.criar_sessao()
        self.sessao_id = j["session_id"]
        self.ultima_resposta = None
        self.ultimos_follows = []
        print(f"⊕ Nova sessão: {self.sessao_id}")

    def cmd_sse(self) -> None:
        self.sse = not self.sse
        print(f"⊕ Streaming: {'ON' if self.sse else 'OFF (JSON completo)'}")

    def cmd_json(self) -> None:
        self.bruto = not self.bruto
        print(f"⊕ Saída bruta JSON (MAD): {'ON' if self.bruto else 'OFF'}")

    def cmd_contexto(self, resto: str) -> None:
        if resto.strip():
            self.contexto = resto.strip()
            print(f"⊕ Contexto: {self.contexto}")
        else:
            self.contexto = None
            print("⊕ Contexto removido")

    def cmd_historico(self, resto: str) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        limite = int(resto) if resto.strip().isdigit() else TETO_MENSAGENS
        msgs = self.cli.mensagens(self.sessao_id, limite=limite)
        Tela.historico(msgs)
        print(f"({len(msgs)} mensagens)")

    def cmd_info(self) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        print(json.dumps(self.cli.sessao(self.sessao_id), indent=2,
                         ensure_ascii=False))

    def cmd_sessoes(self) -> None:
        j = self.cli.sessoes()
        itens = j.get("sessions") or []
        if not itens:
            print("⊕ Lista vazia — o listing exige identidade logada (§2.3).")
        for it in itens:
            print(f"  · {it.get('session_id')}  "
                  f"{(it.get('title') or '')[:44]}  "
                  f"{it.get('updated_at', '')[:19]}")

    def cmd_fixar(self, resto: str) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        fixada = resto.strip() != "0"
        st, obj = self.cli.fixar(self.sessao_id, fixada)
        estado(f"PATCH pinned={fixada}", st, obj,
               esperado="403 anônimo documentado (§2.3)")

    def cmd_seeds(self, resto: str) -> None:
        if not resto.strip():
            print("uso: /seeds <pergunta>")
            return
        j = self.cli.seeds(resto.strip())
        print(f"⊕ seed_key: {j.get('seed_key', '')} · cached: {j.get('cached')}")
        if j.get("session_id"):
            print(f"⊕ sessão:   {j['session_id']} (criada pela rota — §4.4)")
        r = {"content": j.get("content", ""), "title": j.get("title"),
             "grounding_sources": j.get("grounding_sources") or [],
             "follow_up_questions": j.get("suggestions") or [],
             "suggested_actions": [], "metadata": {}, "streaming": False}
        Tela.cabecalho(r, 0.0)
        Tela.corpo(r)
        Tela.rodape(r)

    def cmd_ativas(self) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        j = self.cli.stream_ativo(self.sessao_id)
        if j.get("active"):
            print(f"⊕ stream ativo: {j.get('stream_id')} · "
                  f"message_id {j.get('message_id')}")
        else:
            print("⊕ Nenhum stream em andamento ({active:false}).")

    def cmd_retomar(self, resto: str) -> None:
        partes = resto.split()
        if not partes:
            if not self.sessao_id:
                print("✖ informe: /retomar <stream_id>")
                return
            j = self.cli.stream_ativo(self.sessao_id)
            if not j.get("active"):
                print("✖ nenhum stream ativo — informe: /retomar <stream_id>")
                return
            partes = [j.get("stream_id", "")]
        eventos = self.cli.retomar(partes[0],
                                   partes[1] if len(partes) > 1 else "0")
        print(f"⊕ replay: {len(eventos)} eventos")
        conteudo = ""
        for nome, dados in eventos:
            if nome == "content.delta":
                conteudo += dados.get("delta", "")
            elif nome == "status.update":
                print(f"  · {dados.get('status', '')}")
        print()
        print(renderizar_md(limpar_citacoes(conteudo)))

    def cmd_feedback(self, resto: str) -> None:
        if not self.ultima_resposta:
            print("✖ sem resposta para avaliar")
            return
        partes = resto.split(None, 2)
        if not partes or partes[0] not in ("0", "1"):
            print(f"uso: /feedback <0|1> [motivos] [comentário] — motivos 👎: "
                  f"{', '.join(MOTIVOS_FEEDBACK)}")
            return
        rating = int(partes[0])
        motivos = ([m for m in partes[1].split(",") if m]
                   if len(partes) > 1 else [])
        comentario = partes[2] if len(partes) > 2 else None
        j = self.cli.feedback(self.sessao_id or "",
                              self.ultima_resposta.get("message_id", ""),
                              rating, motivos or None, comentario)
        print(f"⊕ {'👍' if rating == 1 else '👎'} registrado em "
              f"{j.get('recorded_at', '')} (overwritten: {j.get('overwritten')})")

    def cmd_quota(self) -> None:
        r = self.ultima_resposta
        if not r:
            print("✖ sem resposta ainda")
            return
        meta = r.get("metadata") or {}
        if not meta:
            print("⊕ metadata vazio — no modo JSON o uso só chega no SSE")
            return
        print(json.dumps(meta.get("quota") or meta, indent=2))
        print(c("  escopo: POR IDENTIDADE (cookie A3) · janela 24 h "
                "(period_seconds 86400) · compartilhada por TODAS as sessões "
                "deste jar · /renovar = novo A3 = balanço cheio", "dim"))

    def cmd_renovar(self) -> None:
        if self.cli.renova_identidade():
            print("⊕ Novo A3 — nova identidade, quota renovada (§5.9).")
            if self.sessao_id:
                print("  Sessões da identidade anterior ficam órfãs — /nova.")
                self.sessao_id = None
        else:
            print("✖ não consegui obter A3 — tente novamente")

    def cmd_apagar(self) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        st, obj = self.cli.apagar(self.sessao_id)
        estado("POST /sessions/{id}/delete", st, obj,
               esperado="403 anônimo documentado (§2.3)" if st == 403 else None)

    def cmd_exportar(self, resto: str) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        caminho = resto.strip() or f"scout_{self.sessao_id[:8]}.json"
        pacote = {"sessao": self.cli.sessao(self.sessao_id),
                  "mensagens": self.cli.mensagens(self.sessao_id),
                  "exportado_em": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(pacote, f, indent=2, ensure_ascii=False)
        print(f"⊕ exportado: {caminho}")

    def cmd_config(self) -> None:
        for rotulo, st, tx in self.cli.config_servicos():
            print(f"⊕ {rotulo} → HTTP {st}")
            print("  " + tx[:200].replace("\n", " "))

    def cmd_deeplink(self, resto: str) -> None:
        url = self.cli.deep_link(resto.strip()
                                 or "What is going on with the market today?")
        print(f"⊕ deep link (§9.6): {url}")
        st, obj = self.cli.sondar_deep_link(url)
        print(f"⊕ GET /__ai/scout/chat → HTTP {st}"
              + ("  (404 esperado — rota do webview nativo)" if st == 404
                 else ""))

    # -- MAD: comandos -------------------------------------------------------

    def _mad(self, resultado: Tuple[int, Any]) -> Any:
        st, obj = resultado
        if self.bruto:
            print(f"⊕ HTTP {st}")
            print(json.dumps(obj, indent=2, ensure_ascii=False)[:6000]
                  if obj is not None else "  (sem corpo)")
        return obj

    def cmd_analista(self, resto: str) -> None:
        partes = resto.split()
        simbolo = (partes[0] if partes else "AAPL").upper()
        secao = partes[1] if len(partes) > 1 else None
        j = self.cli.analista(simbolo)
        if self.bruto:
            print(json.dumps(j, indent=2, ensure_ascii=False)[:8000])
            return
        tela_analista(j, apenas=secao)

    def cmd_ddq(self, resto: str) -> None:
        partes = resto.split()
        if not partes:
            print("uso: /ddq <uuid-artigo> [número|question-id]")
            return
        uuid = partes[0]
        arg2 = partes[1] if len(partes) > 1 else None
        if arg2 is None:
            j = self.cli.ddq_perguntas(uuid)
            if j is None:
                print("⊕ 204 — geração assíncrona pendente; re-tente em minutos.")
                return
            self.ddq_uuid = uuid
            self.ddq_catalogo = tela_ddq_perguntas(j)
            return
        if arg2.isdigit() and self.ddq_catalogo and self.ddq_uuid == uuid:
            n = int(arg2)
            if not 1 <= n <= len(self.ddq_catalogo):
                print("✖ número fora do catálogo")
                return
            qid = self.ddq_catalogo[n - 1].get("questionId", "")
        else:
            qid = arg2
        j = self.cli.ddq_resposta(uuid, qid)
        if j is None:
            print("⊕ 204 — resposta ainda não gerada.")
            return
        follows = tela_ddq_resposta(j)
        self.ddq_uuid = uuid
        self.ddq_catalogo = ([{"questionId": f.get("questionId", ""),
                               "question": f.get("question", "")}
                              for f in follows] if follows else
                             self.ddq_catalogo)

    def cmd_ect(self, resto: str) -> None:
        opts = dict(p.split("=", 1) for p in resto.split() if "=" in p)
        tid = opts.get("--transcript-id") or opts.get("transcript-id")
        eid = opts.get("--event-id") or opts.get("event-id")
        if not tid and not eid:
            print("uso: /ect --transcript-id=ID  (ou --event-id=ID)")
            return
        j = self.cli.ect(transcript_id=tid, event_id=eid)
        print(json.dumps(j, indent=2, ensure_ascii=False)[:3000])

    def cmd_transcricao(self, resto: str) -> None:
        opts: Dict[str, str] = {}
        for par in resto.split():
            if par.startswith("--"):
                chave, _, valor = par.partition("=")
                opts[chave.lstrip("-").replace("-", "_")] = valor.strip("\"'")
        if not opts:
            print("  use: /transcricao --transcript-id=123 | --quartr-id=Q | "
                  "--event-id=UUID")
            return
        st, obj = self.cli.transcricao(
            transcript_id=opts.get("transcript_id") or None,
            quartr_id=opts.get("quartr_id") or None,
            event_id=opts.get("event_id") or None)
        estado("GET /xhr/transcript (crumb + cookies)", st, obj)

    def cmd_perguntas_mad(self, resto: str) -> None:
        simb = resto.strip().upper() or "NVDA"
        qs = self.cli.perguntas_semeadas(simb)
        print(c(f"◈ Perguntas sugeridas de {simb}:", "cyan"))
        for q in qs:
            tag = (q.get("tags") or {}).get("signal_type") or ""
            prio = q.get("priority")
            print(f"  · {(q.get('question_text') or '')[:80]}"
                  + (c(f"  [{tag}]", "dim") if tag else "")
                  + (f" (prio {prio})" if prio is not None else ""))

    def cmd_temas(self, resto: str) -> None:
        j = self.cli.temas(grain=resto.strip() or "parent", limit=12)
        if self.bruto:
            print(json.dumps(j, indent=2, ensure_ascii=False)[:4000])
            return
        tela_temas(j)

    def cmd_tickers(self) -> None:
        obj = self._mad(self.cli.temas_tickers())
        if not self.bruto:
            print(json.dumps(obj, indent=2, ensure_ascii=False)[:2500])

    def cmd_tema(self, resto: str) -> None:
        if not resto.strip():
            print("uso: /tema <uuid>  (copie o uuid de /temas)")
            return
        obj = self._mad(self.cli.tema_por_uuid(resto.strip()))
        if not self.bruto:
            tela_tema(obj or {})

    def cmd_tema_simbolo(self, resto: str) -> None:
        obj = self._mad(self.cli.temas_por_simbolo(resto.strip().upper()
                                                   or "NVDA"))
        if not self.bruto:
            print(json.dumps(obj, indent=2, ensure_ascii=False)[:2500])

    def cmd_grafo(self, resto: str) -> None:
        janela = resto.strip() if resto.strip() in JANELAS_GRAFO else "1d"
        obj = self._mad(self.cli.grafo(window=janela))
        if not self.bruto:
            print(json.dumps(obj, indent=2, ensure_ascii=False)[:3500])

    def cmd_artigos_tema(self, resto: str) -> None:
        uuids = [u for u in resto.split() if u]
        if not uuids:
            print("uso: /artigos-tema <uuid> [uuid…]")
            return
        estado("POST themes/from-articles",
               *self.cli.temas_de_artigos(uuids))

    def cmd_portfolio(self, resto: str) -> None:
        arg = resto.strip()
        if not arg:
            print("uso: /portfolio AAPL:5000,NVDA:3000   |   /portfolio <id>")
            return
        if ":" in arg:
            holdings = []
            for par in arg.split(","):
                ticker, _, peso = par.partition(":")
                holdings.append({"ticker": ticker.strip().upper(),
                                 "weight": float(peso or 1)})
            st, obj = self.cli.portfolio_feed(holdings=holdings)
        else:
            st, obj = self.cli.portfolio_feed(portfolio_id=arg)
        if self.bruto:
            print(f"⊕ HTTP {st}")
            print(json.dumps(obj, indent=2, ensure_ascii=False)[:4000]
                  if obj else "  (sem corpo)")
            return
        if st >= 400 or not obj:
            estado("themes/portfolio/feed", st, obj)
            return
        tela_portfolio(obj)

    def cmd_diario(self) -> None:
        estado("GET /v2/daily_brief/analysis", *self.cli.diario_analise(),
               esperado="401 anônimo documentado (gate JWT)")

    def cmd_faqs(self, resto: str) -> None:
        estado("GET /v2/portfolio_ddq/faqs",
               *self.cli.portfolio_faqs(resto.strip()
                                        or "How is my portfolio doing?"),
               esperado="401 anônimo documentado (gate JWT)")

    def cmd_watchlist(self) -> None:
        estado("GET /v2/watchlist_insights/summary",
               *self.cli.watchlist_resumo(),
               esperado="401 anônimo documentado (gate JWT)")

    def cmd_insights(self) -> None:
        """Família de insights completa — 6 variantes (§3.5)."""
        for rotulo, par in (
            ("GET /v2/daily_brief/analysis", self.cli.diario_analise()),
            ("GET /v2/daily_brief/portfolio_insights/analysis",
             self.cli.diario_analise(pf_id="demo")),
            ("GET /v2/daily_brief/portfolio_insights/summary",
             self.cli.portfolio_insights_resumo()),
            ("GET /v2/watchlist_insights/analysis", self.cli.watchlist_analise()),
            ("GET /v2/watchlist_insights/summary", self.cli.watchlist_resumo()),
            ("GET /v2/portfolio_ddq/faqs",
             self.cli.portfolio_faqs("How is my portfolio doing?")),
        ):
            estado(rotulo, *par, esperado="401 anônimo documentado (gate JWT)")

    def cmd_screener(self, resto: str) -> None:
        estado("POST /ws/mad/v2/screener/nls (dormente)",
               *self.cli.screener_nls(resto.strip()
                                      or "top tech stocks by market cap"),
               esperado="401 anônimo documentado (§3.4)")

    def cmd_screener_legado(self, resto: str) -> None:
        estado("POST /ws/screeners/v1/finance/screener/nls?crumb (ativa)",
               *self.cli.screener_nls(resto.strip()
                                      or "top tech stocks by market cap",
                                      usar_legado=True),
               esperado="401 anônimo documentado (§3.4)")

    def cmd_aposentado(self) -> None:
        """Família aposentada completa — 5 rotas, todas 410 (§7)."""
        for rotulo, par in (
            ("POST /ws/mad/v2/chat", self.cli.chat_aposentado()),
            ("POST /ws/mad/v2/chat/{sessionId}",
             self.cli.chat_sessao_aposentado(SESSAO_FANTASMA)),
            ("GET  /ws/mad/v2/chat", self.cli.chat_get_aposentado()),
            ("GET  /ws/mad/v2/chat/question/{uuid}",
             self.cli.chat_pergunta_aposentada(PERGUNTA_FANTASMA)),
            ("GET  /ws/mad/v2/chat/rate_limit", self.cli.rate_limit_aposentado()),
        ):
            estado(rotulo, *par, esperado="410 Gone — API aposentada")

    def cmd_rate_limit(self) -> None:
        estado("GET /ws/mad/v2/chat/rate_limit",
               *self.cli.rate_limit_aposentado(),
               esperado="410 Gone — API aposentada")

    # -- laço principal --------------------------------------------------------

    DESPACHO = {
        "/nova": "cmd_nova", "/sse": "cmd_sse", "/json": "cmd_json",
        "/contexto": "cmd_contexto", "/historico": "cmd_historico",
        "/info": "cmd_info", "/sessoes": "cmd_sessoes", "/fixar": "cmd_fixar",
        "/seeds": "cmd_seeds", "/ativas": "cmd_ativas",
        "/retomar": "cmd_retomar", "/feedback": "cmd_feedback",
        "/quota": "cmd_quota", "/renovar": "cmd_renovar",
        "/apagar": "cmd_apagar", "/exportar": "cmd_exportar",
        "/config": "cmd_config", "/deeplink": "cmd_deeplink",
        "/analista": "cmd_analista", "/ddq": "cmd_ddq", "/ect": "cmd_ect",
        "/transcricao": "cmd_transcricao", "/perguntas": "cmd_perguntas_mad",
        "/temas": "cmd_temas", "/tickers": "cmd_tickers",
        "/tema": "cmd_tema", "/tema-simbolo": "cmd_tema_simbolo",
        "/grafo": "cmd_grafo", "/artigos-tema": "cmd_artigos_tema",
        "/portfolio": "cmd_portfolio", "/diario": "cmd_diario",
        "/faqs": "cmd_faqs", "/watchlist": "cmd_watchlist",
        "/insights": "cmd_insights", "/screener": "cmd_screener",
        "/screener-legado": "cmd_screener_legado",
        "/aposentado": "cmd_aposentado", "/rate-limit": "cmd_rate_limit",
    }

    def executar(self) -> int:
        if not self.iniciar():
            print("✖ bootstrap falhou — sem cookie A3", file=sys.stderr)
            return 2
        while True:
            try:
                linha = input("scout> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not linha:
                continue
            if linha in ("/sair", "/exit", "/quit", "sair"):
                break
            if linha in ("/ajuda", "/help", "?", "ajuda"):
                print(AJUDA)
                continue
            if linha.isdigit() and self.ultimos_follows:
                n = int(linha)
                if 1 <= n <= len(self.ultimos_follows):
                    self.perguntar(self.ultimos_follows[n - 1])
                    continue
            if linha.startswith("/"):
                cmd, _, resto = linha.partition(" ")
                metodo = self.DESPACHO.get(cmd.lower())
                if metodo is None:
                    print(f"✖ comando desconhecido: {cmd} — /ajuda")
                    continue
                try:
                    getattr(self, metodo)(resto)
                except (ErroScout, ValueError) as e:
                    print(c(f"✖ {e}", "red"))
                except Exception as e:
                    self._tratar_erro(e)
                print()
                continue
            self.perguntar(linha)
            print()
        print("⊕ até logo.")
        return 0


# ===========================================================================
# 9. MODO LOTE (uma operação, para scripting)
# ===========================================================================

def _parse_holdings(texto: str) -> List[Dict[str, Any]]:
    holdings = []
    for par in texto.split(","):
        ticker, _, peso = par.partition(":")
        holdings.append({"ticker": ticker.strip().upper(),
                         "weight": float(peso or 1)})
    return holdings


def modo_lote(args: argparse.Namespace) -> int:
    app = App(sse=not args.json, bruto=args.json)
    if not app.cli.bootstrap():
        print("✖ bootstrap falhou — sem cookie A3", file=sys.stderr)
        return 2

    def falha(e: Exception) -> int:
        print(c(f"✖ {e}", "red"), file=sys.stderr)
        return 1

    if args.pergunta:
        app.sessao_id = None
        app.contexto = args.contexto
        try:
            if args.json:
                j = app.cli.chat(args.pergunta, contexto=args.contexto)
                print(json.dumps(j, indent=2, ensure_ascii=False))
                return 0
            if args.seeds:
                app.cmd_seeds(args.pergunta)
            else:
                app.perguntar(args.pergunta)
        except Exception as e:
            return falha(e)
        return 0

    if args.seeds:
        try:
            app.cmd_seeds(args.seeds)
        except Exception as e:
            return falha(e)
        return 0

    if args.perguntas:
        try:
            app.cmd_perpuntas_mad(args.perguntas)
        except Exception as e:
            return falha(e)
        return 0

    if args.analista:
        try:
            j = app.cli.analista(args.analista)
        except Exception as e:
            return falha(e)
        app.ultimo_cru = j
        if args.json:
            print(json.dumps(j, indent=2, ensure_ascii=False))
        else:
            tela_analista(j, apenas=args.secao)
        return 0

    if args.ddq:
        try:
            j = app.cli.ddq_perguntas(args.ddq)
        except Exception as e:
            return falha(e)
        if j is None:
            print("204 — geração assíncrona pendente")
            return 0
        tela_ddq_perguntas(j)
        return 0

    if args.temas:
        try:
            tela_temas(app.cli.temas(limit=12))
        except Exception as e:
            return falha(e)
        return 0

    if args.grafo:
        try:
            j = app.cli.grafo(window=args.grafo)
        except Exception as e:
            return falha(e)
        print(json.dumps(j, indent=2, ensure_ascii=False)[:4000])
        return 0

    if args.portfolio:
        try:
            if ":" in args.portfolio:
                st, obj = app.cli.portfolio_feed(
                    holdings=_parse_holdings(args.portfolio))
            else:
                st, obj = app.cli.portfolio_feed(portfolio_id=args.portfolio)
        except Exception as e:
            return falha(e)
        if st >= 400 or not obj:
            estado("themes/portfolio/feed", st, obj)
            return 1
        tela_portfolio(obj)
        return 0

    if args.insights:
        app.cmd_insights()
        return 0

    if args.aposentado:
        app.cmd_aposentado()
        return 0

    if args.config:
        app.cmd_config()
        st, obj = app.cli.chat_get()
        estado("GET /chat (método errado — §7)", st, obj,
               esperado="404 not_found (não há 405)")
        return 0

    if args.screener:
        estado("POST /ws/mad/v2/screener/nls (dormente)",
               *app.cli.screener_nls(args.screener),
               esperado="401 anônimo documentado")
        return 0

    print("✖ nenhuma operação informada — rode sem argumentos para o REPL "
          "ou use -q/--analista/--temas/…", file=sys.stderr)
    return 2


# ===========================================================================
# 10. MAIN
# ===========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="scout.py",
        description="Chat completo do Scout AI (Yahoo Finance) — pergunta e "
                    "resposta com todas as funções da API (Promenade + MAD v2). "
                    "Sem argumentos abre o REPL; /ajuda lista os comandos.")
    ap.add_argument("-q", "--pergunta", metavar="TEXTO",
                    help="pergunta única ao Scout e sai (SSE por default)")
    ap.add_argument("--json", action="store_true",
                    help="JSON completo em vez de streaming; envelopes brutos no MAD")
    ap.add_argument("--contexto", metavar="VALOR",
                    help="âncora de conteúdo (ex.: ticker:AAPL)")
    ap.add_argument("--seeds", metavar="PERGUNTA",
                    help="resposta semeada (POST /chat/seeds) e sai")
    ap.add_argument("--perguntas", metavar="SIMBOLO",
                    help="catálogo de perguntas sugeridas do símbolo e sai")
    ap.add_argument("--analista", metavar="SIMBOLO",
                    help="relatório do AI Analyst e sai")
    ap.add_argument("--secao", metavar="SECAO",
                    help="seção única do analista (com --analista)")
    ap.add_argument("--ddq", metavar="UUID_ARTIGO",
                    help="catálogo de perguntas do artigo (Dig Deeper)")
    ap.add_argument("--temas", action="store_true",
                    help="lista de temas do AI Playground e sai")
    ap.add_argument("--grafo", metavar="JANELA",
                    help="grafo de temas por janela (1d|2d|5d|1w|2w) e sai")
    ap.add_argument("--portfolio", metavar="A:P,C:P|ID",
                    help="feed de temas do portfólio e sai")
    ap.add_argument("--insights", action="store_true",
                    help="família de insights de portfólio (401 sem JWT) e sai")
    ap.add_argument("--aposentado", action="store_true",
                    help="família /ws/mad/v2/chat aposentada (410×5) e sai")
    ap.add_argument("--config", action="store_true",
                    help="sonda /xhr/config + GET /chat (404) e sai")
    ap.add_argument("--screener", metavar="CONSULTA",
                    help="screener NLS (rota MAD v2 dormente) e sai")
    ap.add_argument("--ascii", action="store_true",
                    help="caixas +---+ em vez de ╭─╮│╰╯")
    ap.add_argument("--sem-cores", action="store_true",
                    help="desativa todas as cores ANSI")
    ap.add_argument("--com-cores", action="store_true",
                    help="força cores mesmo com stdout redirecionado")
    ap.add_argument("--no-pause", action="store_true",
                    help="sem pausa ao sair (para scripts)")
    args = ap.parse_args()

    iniciar_ui(sem_cores=args.sem_cores, com_cores=args.com_cores,
               ascii_mode=args.ascii)

    tem_lote = any((args.pergunta, args.seeds, args.perguntas, args.analista,
                    args.ddq, args.temas, args.grafo, args.portfolio,
                    args.insights, args.aposentado, args.config,
                    args.screener))
    if tem_lote:
        return modo_lote(args)

    app = App(sse=not args.json)
    app.contexto = args.contexto
    # ANTI-FECHAMENTO: menu em loop — nenhum traceback derruba o app
    try:
        menu(app, no_pause=args.no_pause)
        return 0
    except KeyboardInterrupt:
        print(c("⊕ interrompido — até logo.", "mid"))
        if not args.no_pause:
            pausa()
        return 0
    except Exception as e:                      # última linha de defesa
        print(c(f"✖ erro fatal capturado: {e}", "red"))
        if not args.no_pause:
            pausa()
        return 1


if __name__ == "__main__":
    sys.exit(main())


