#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scout_chat.py — Cliente de chat dinâmico do Scout AI (Yahoo Finance)
====================================================================

Código legado de referência da **Promenade API** — o backend do chat do
Scout (assistente de IA do Yahoo Finance). Implementa o contrato wire
completo documentado em `yf-scout-ai.md` (§2-§8, §13-§15):

  · POST /sessions                     criação de sessão (§3.1)
  · POST /chat                         mensagem — JSON completo ou SSE (§3.2, §6)
  · POST /chat/seeds                   resposta semeada com cache (§3.3)
  · GET  /sessions/{id}/messages       histórico paginado por cursor (§3.4)
  · GET  /sessions/{id}                metadados e título derivado (§3.5)
  · GET  /sessions                     lista de sessões (§3.5)
  · POST /sessions/{id}/delete         exclusão — 403 anônimo (§3.6)
  · GET  /sessions/{id}/active-stream  sondagem de stream em curso (§3.7)
  · GET  /chat/resume/{stream_id}      replay do stream (§3.8)
  · POST /feedback                     avaliação 👍/👎 (§3.9)
  · GET  /xhr/config?name=services     mapa de serviços do loader (§2.1)
  · GET  /chat                         método errado — 404 (§14.1)
  · GET  /__ai/scout/chat              deep link do chat nativo (§13.6)
  · GET  /xhr/dynamic-seeded-questions perguntas sugeridas por símbolo (§3.10, §8)

Autenticação: **cookie A3 anônimo** obtido de `fc.yahoo.com` (§2.3) —
crumb dispensado. Quota: 100.000 tokens/24 h por identidade (§6.4);
a re-autenticação (novo A3) renova a quota.

Somente stdlib (urllib + http.cookiejar) — sem dependências externas.
Python 3.8+.

Uso:
    python scout_chat.py                          # REPL interativo (conversa dinâmica)
    python scout_chat.py -q "What is the Dow?"    # uma pergunta (JSON completo)
    python scout_chat.py -q "How is AAPL?" --sse --contexto "ticker:AAPL"
    python scout_chat.py -q "What is NASDAQ?" --seeds
    python scout_chat.py --perguntas NVDA         # perguntas sugeridas do símbolo

Comandos do REPL (digite /ajuda dentro do programa):
    /nova /sse /contexto /historico /info /sessoes /seeds /ativas
    /retomar /feedback /perguntas /quota /renovar /apagar /exportar /sair
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constantes do contrato (doc §1, §2, §4)
# ---------------------------------------------------------------------------

PROMENADE = "https://promenade-api.search.yahoo.com"   # serviço `scout` (§1)
FINANCE_HOST = "https://finance.yahoo.com"
FC_HOST = "https://fc.yahoo.com"                        # emite A1/A1S/A3 anônimos (§2.3)
TENANT = "finance"                                      # constante do bundle (§4.1)
TTL_SEEDS = 5                                           # fixado pelo cliente (§3.3)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64 x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TIMEOUT_GERAL = 30        # rotas de sessão/metadados
TIMEOUT_CHAT = 150        # chat pode levar o pipeline completo
TIMEOUT_SSE = 240         # streaming (rede lida em pedaços)
TENTATIVAS_5XX = 8        # 500 vazio transiente da borda (§14.7) — a
                          # proporção varia por dia/hora; 8 tentativas com
                          # backoff cobre janelas de borda agitada

# enum de motivos aceitos no 👎 — definido no servidor (§3.9)
MOTIVOS_FEEDBACK = ("offensive", "not_helpful", "too_long", "too_short")

# eventos SSE na ordem canônica observada (§6.2)
EVENTOS_SSE = ("stream.start", "status.update", "content.delta",
               "grounding.sources", "follow_up.questions",
               "actions.suggested", "data", "stream.end", "error")

# símbolos sabidamente estáveis no proxy de perguntas (§3.10 — 502 por shard)
SIMBOLOS_PERGUNTAS_OK = ("NVDA", "TSLA", "F", "AMZN")


# ---------------------------------------------------------------------------
# Erro do contrato
# ---------------------------------------------------------------------------

class ErroScout(Exception):
    """Erro HTTP do Scout — status + corpo (formatos do doc §14.1)."""

    def __init__(self, acao: str, status: int, corpo: str) -> None:
        self.acao = acao
        self.status = status
        self.corpo = corpo
        try:
            j = json.loads(corpo)
            detalhe = j.get("message") or j.get("detail") or j.get("error") or corpo
        except Exception:
            detalhe = corpo
        super().__init__(f"{acao} → HTTP {status}: {detalhe}")


# ---------------------------------------------------------------------------
# Helpers de formatação (regras do cliente web, §13)
# ---------------------------------------------------------------------------

def limpar_citacoes(texto: str) -> str:
    """Reduz a forma `[texto][N]` do modelo a `texto` (função O do §13.1)."""
    return re.sub(r"\[([^\]]*)\]\[\d+\]", r"\1", texto)


def renderizar_md(texto: str, largura: int = 78) -> str:
    """Renderização Markdown minimalista para terminal.

    O `content` chega em Markdown (§5.2): negrito `**`, títulos `#`,
    listas com `-`/`*` e links `[rótulo](url)`. Mantém-se simples por
    design (código legado) — não há dependência de bibliotecas.
    """
    linhas_saida: List[str] = []
    dentro_codigo = False
    for linha in texto.splitlines() or [""]:
        if linha.strip().startswith("```"):
            dentro_codigo = not dentro_codigo
            linhas_saida.append("  │ " + linha if dentro_codigo else "  │ ```")
            continue
        if dentro_codigo:
            linhas_saida.append("  │ " + linha)
            continue
        travado = linha.lstrip()
        recuo = len(linha) - len(travado)
        negrito = re.sub(r"\*\*([^*]+)\*\*", r"\1", travado)
        negrito = re.sub(r"\*([^*]+)\*", r"\1", negrito)
        negrito = re.sub(r"`([^`]+)`", r"\1", negrito)
        m = re.match(r"^(#{1,6})\s+(.*)$", negrito)
        if m:
            linhas_saida.append("")
            linhas_saida.append((" " * recuo) + "◆ " + m.group(2).upper())
            linhas_saida.append((" " * recuo) + "─" * min(len(m.group(2)) + 2, largura))
            continue
        m = re.match(r"^[-*]\s+(.*)$", negrito)
        if m:
            linhas_saida.append((" " * recuo) + "  • " + m.group(1))
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", negrito)
        if m:
            linhas_saida.append((" " * recuo) + "  " + m.group(1) + ". " + m.group(2))
            continue
        # links [rótulo](url) → rótulo ‹url›
        negrito = re.sub(r"\[([^\]]*)\]\(([^)]+)\)", r"\1 ‹\2›", negrito)
        linhas_saida.append((" " * recuo) + negrito)
    return "\n".join(linhas_saida).rstrip()


def formatar_fonte(fonte: Dict[str, Any], indice: int) -> str:
    """Uma linha de fonte do evento `grounding.sources` (§6.3)."""
    titulo = (fonte.get("title") or "").strip()
    url = (fonte.get("url") or fonte.get("cdn_url") or "").strip()
    provedor = (fonte.get("provider_name") or fonte.get("provider") or "").strip()
    data = (fonte.get("publish_time") or fonte.get("pub_date") or "").strip()
    partes = [f"[{indice}]"]
    if titulo:
        partes.append(titulo[:70])
    if provedor:
        partes.append(f"· {provedor}")
    if data:
        partes.append(f"· {data}")
    if url:
        partes.append(f"\n     {url[:96]}")
    return " ".join(partes)


def segundos_legiveis(seg: float) -> str:
    seg = int(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# Parser SSE (regra do resolvedor duplo do cliente — §6.1)
# ---------------------------------------------------------------------------

def resolver_evento(obj: Any, linha_evento: str) -> Tuple[str, Dict[str, Any]]:
    """Reproduz o resolvedor `X` do chunk arrow_upward (§6.1).

    O nome do evento tem duas fontes: o campo `event` DENTRO do JSON do
    payload (prioridade) e a linha `event:` do enquadramento SSE — com a
    exceção do valor genérico ``message``, descartado (tratado como
    ausente). Payload não-objeto vira `data` vazio.
    """
    base = "" if linha_evento == "message" else (linha_evento or "")
    if isinstance(obj, dict):
        ev = obj.get("event")
        ev = ev if isinstance(ev, str) else ""
        nome = ev or base
        dados = obj.get("data")
        dados = dados if isinstance(dados, dict) else {}
        return nome, dados
    return base, {}


def iterar_sse(resp: urllib.request.urlopen) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Lê o corpo `text/event-stream` linha a linha (sem compressão — §6.1).

    O enquadramento é `id:` + `data:`; o tipo vem no campo `event` do JSON
    (§6.1). `data:` vazio ou JSON inválido é descartado, como no parser K.
    """
    linha_evento = ""
    for bruta in resp:
        linha = bruta.decode("utf-8", "replace").rstrip("\r\n")
        if not linha:
            linha_evento = ""          # moldura encerrada — reseta o discriminador
            continue
        if linha.startswith(":"):
            continue                    # comentário keep-alive
        if linha.startswith("event:"):
            linha_evento = linha[6:].strip()
            continue
        if linha.startswith("id:"):
            continue                    # carimbo `ms-seq` (§6.1)
        if linha.startswith("data:"):
            bruto = linha[5:].strip()
            if not bruto:
                continue
            try:
                obj = json.loads(bruto)
            except ValueError:
                continue                # fora de JSON — descartado (parser K)
            if not isinstance(obj, dict):
                continue
            nome, dados = resolver_evento(obj, linha_evento)
            if nome:
                yield nome, dados
            continue
        # linha solta fora de moldura — ignora


# ---------------------------------------------------------------------------
# Cliente Promenade
# ---------------------------------------------------------------------------

class ClienteScout:
    """Cliente da Promenade API — A3 anônimo de bootstrap basta (§2.3)."""

    def __init__(self, timeout_chat: int = TIMEOUT_CHAT) -> None:
        self.timeout = timeout_chat
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [("User-Agent", UA)]
        self.identidade_nova = False

    # -- bootstrap de identidade (§2.3) ------------------------------------

    def bootstrap(self) -> bool:
        """Obtém o cookie A3 anônimo de `fc.yahoo.com`.

        Sem o A3, as rotas de escrita respondem 400 `missing_identity`
        (§14.1). A visita a `finance.yahoo.com` garante cookies de borda
        complementares (A1/A1S). Retorna True quando o A3 está no jar.
        """
        self.identidade_nova = True
        try:
            self.opener.open(FC_HOST, timeout=20).read(512)
        except urllib.error.HTTPError:
            pass  # 4xx do fc é normal — os cookies já vieram nos headers
        try:
            self.opener.open(FINANCE_HOST, timeout=20).read(2048)
        except urllib.error.HTTPError:
            pass
        return any(c.name == "A3" for c in self.jar)

    def renova_identidade(self) -> bool:
        """Limpa o jar e re-faz o bootstrap — novo A3 = nova quota (§6.4).

        Sem limpar os cookies, `fc.yahoo.com` não re-emite o A3 e a
        identidade (com a quota esgotada) permanece a mesma.
        """
        self.jar.clear()
        return self.bootstrap()

    # -- núcleo HTTP --------------------------------------------------------

    def _pedido(self, metodo: str, url: str, corpo: Optional[dict],
                headers: Optional[Dict[str, str]],
                timeout: int, tentativas: int = 1) -> Tuple[int, str]:
        """Pedido com corpo completo. Devolve (status, texto).

        Repete em 500/502/503/504 — a borda Promenade devolve 500 com
        corpo vazio de forma intermitente (§14.7); re-tentar resolve.
        """
        dados = None
        cab = {"Accept": "*/*"}
        if corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
            cab["Content-Type"] = "application/json"
        if headers:
            cab.update(headers)
        ultimo = (0, "")
        for i in range(max(1, tentativas)):
            req = urllib.request.Request(url, data=dados, headers=cab,
                                         method=metodo)
            try:
                with self.opener.open(req, timeout=timeout) as resp:
                    return resp.status, resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                try:
                    texto = e.read().decode("utf-8", "replace")
                except Exception:
                    texto = ""
                ultimo = (e.code, texto)
                if e.code in (500, 502, 503, 504) and i < tentativas - 1:
                    time.sleep(1.5 + i)          # §14.7 — falha transiente
                    continue
                return ultimo
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                ultimo = (0, str(e))
                if i < tentativas - 1:
                    time.sleep(1.5 + i)
                    continue
                return ultimo
        return ultimo

    def _pedido_sse(self, url: str, corpo: dict,
                    timeout: int = TIMEOUT_SSE
                    ) -> Tuple[int, Iterator[Tuple[str, Dict[str, Any]]]]:
        """POST com `Accept: text/event-stream` — devolve iterador de eventos.

        Sem o Accept a rota devolve JSON completo (§3.2); com ele, o servidor
        responde `text/event-stream` sem compressão e `Transfer-Encoding:
        chunked` (§6.1) — leitura linha a linha como texto puro.
        """
        req = urllib.request.Request(
            url, data=json.dumps(corpo).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Accept": "text/event-stream"},
            method="POST")
        # 500 vazio transiente também atinge o estabelecimento do stream
        # (§14.7) — re-tenta a abertura; depois de aberto não há replay.
        ultimo: Tuple[int, str] = (0, "")
        for i in range(TENTATIVAS_5XX):
            try:
                resp = self.opener.open(req, timeout=timeout)
                return resp.status, iterar_sse(resp)
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
        raise ErroScout("POST /chat (SSE)", ultimo[0], ultimo[1])

    @staticmethod
    def _json_ou_erro(acao: str, status: int, texto: str,
                      esperado: int = 200) -> Dict[str, Any]:
        if status != esperado:
            raise ErroScout(acao, status, texto)
        try:
            return json.loads(texto)
        except ValueError:
            raise ErroScout(acao, status, texto[:200]) from None

    # -- §3.1 POST /sessions -------------------------------------------------

    def criar_sessao(self) -> Dict[str, Any]:
        """Cria sessão — corpo `{"tenant":"finance"}`, resposta 201 (§5.1)."""
        st, tx = self._pedido("POST", f"{PROMENADE}/sessions",
                              {"tenant": TENANT}, None, TIMEOUT_GERAL,
                              tentativas=TENTATIVAS_5XX)
        return self._json_ou_erro("POST /sessions", st, tx, esperado=201)

    # -- §3.2 POST /chat (JSON completo) -------------------------------------

    def chat(self, mensagem: str, session_id: Optional[str] = None,
             contexto: Optional[str] = None, variante: Optional[str] = None,
             chave_idempotencia: Optional[str] = None
             ) -> Dict[str, Any]:
        """Envia mensagem na negociação default — JSON completo (§5.2).

        `session_id` é opcional no servidor (conversa ad-hoc), mas o app
        web sempre cria a sessão antes (§3.2). Campos tolerados fora do
        schema são ignorados; 409 `duplicate_request` em idempotência
        repetida (§14.2).
        """
        corpo: Dict[str, Any] = {"message": mensagem, "tenant": TENANT}
        if session_id:
            corpo["session_id"] = session_id
        if contexto:
            corpo["context"] = contexto
        if variante:
            corpo["variant"] = variante
        if chave_idempotencia:
            corpo["idempotency_key"] = chave_idempotencia
        st, tx = self._pedido("POST", f"{PROMENADE}/chat", corpo, None,
                              self.timeout, tentativas=TENTATIVAS_5XX)
        return self._json_ou_erro("POST /chat", st, tx)

    # -- §3.2/§6 POST /chat (streaming SSE) -----------------------------------

    def chat_sse(self, mensagem: str, session_id: Optional[str] = None,
                 contexto: Optional[str] = None, variante: Optional[str] = None,
                 chave_idempotencia: Optional[str] = None,
                 ao_evento: Optional[Callable[[str, Dict[str, Any]], None]] = None
                 ) -> Dict[str, Any]:
        """Envia mensagem com `Accept: text/event-stream` (§6).

        Consome o fluxo chamando `ao_evento(nome, payload)` a cada evento
        e devolve o resultado consolidado (content, fontes, follow-ups,
        ações, usage, quota — §6.2/§6.4). O evento `error` no meio do
        stream vira `ErroScout` (código `quota_exceeded` incluído, §6.2).
        """
        corpo: Dict[str, Any] = {"message": mensagem, "tenant": TENANT}
        if session_id:
            corpo["session_id"] = session_id
        if contexto:
            corpo["context"] = contexto
        if variante:
            corpo["variant"] = variante
        if chave_idempotencia:
            corpo["idempotency_key"] = chave_idempotencia
        _, eventos = self._pedido_sse(f"{PROMENADE}/chat", corpo,
                                      timeout=self.timeout + TIMEOUT_SSE)
        resultado: Dict[str, Any] = {
            "message_id": "", "content": "", "citations": [],
            "grounding_sources": [], "follow_up_questions": [],
            "suggested_actions": [], "title": None,
            "status": [], "metadata": {}, "streaming": True,
        }
        for nome, dados in eventos:
            if ao_evento:
                ao_evento(nome, dados)
            if nome == "stream.start":
                resultado["message_id"] = dados.get("message_id", "")
            elif nome == "status.update":
                resultado["status"].append(dados.get("status", ""))
            elif nome == "content.delta":
                resultado["content"] += dados.get("delta", "")
            elif nome == "grounding.sources":
                resultado["grounding_sources"] = dados.get(
                    "grounding_sources", []) or []
            elif nome in ("follow_up.questions", "suggestions"):
                resultado["follow_up_questions"] = dados.get(
                    "follow_up_questions") or dados.get("suggestions") or []
            elif nome == "actions.suggested":
                resultado["suggested_actions"] = [
                    a for a in (dados.get("actions") or [])
                    if isinstance(a, dict) and isinstance(a.get("action_id"), str)]
            elif nome == "data" and dados.get("key") == "data-chat-title":
                resultado["title"] = (dados.get("payload") or {}).get("title")
            elif nome == "stream.end":
                resultado["message_id"] = dados.get(
                    "message_id", resultado["message_id"])
                resultado["citations"] = dados.get("citations", [])
                resultado["suggestions"] = dados.get("suggestions", [])
                resultado["metadata"] = dados.get("metadata", {}) or {}
                if dados.get("title"):
                    resultado["title"] = dados["title"]
            elif nome == "error":
                raise ErroScout("stream /chat error",
                                dados.get("code") or 500,
                                json.dumps(dados))
        return resultado

    # -- §3.3 POST /chat/seeds -------------------------------------------------

    def seeds(self, mensagem: str, ttl: int = TTL_SEEDS) -> Dict[str, Any]:
        """Pergunta semeada — cache por identidade por `ttl` segundos (§5.4).

        A rota cria a sessão implicitamente (`session_id`/`message_id`
        acompanham a resposta) e devolve o JSON integral — sempre JSON,
        sem negociação SSE (§3.3).
        """
        st, tx = self._pedido(
            "POST", f"{PROMENADE}/chat/seeds",
            {"message": mensagem, "tenant": TENANT, "ttl": ttl},
            None, self.timeout, tentativas=TENTATIVAS_5XX)
        return self._json_ou_erro("POST /chat/seeds", st, tx)

    # -- §3.4 GET /sessions/{id}/messages --------------------------------------

    def mensagens(self, session_id: str, limite: int = 500,
                  pagina: int = 100) -> List[Dict[str, Any]]:
        """Histórico completo com paginação por cursor opaco (§3.4).

        O cliente do build pagina com página de 100 e teto de 500
        mensagens; o `next_cursor` é um base64 de chaves estilo DynamoDB.
        Cursor inválido é ignorado pelo servidor (200 com a primeira
        página). Sessão inexistente → 404 `session_not_found`.
        """
        acumulado: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            query = {"tenant": TENANT, "limit": str(min(pagina, 100))}
            if cursor:
                query["cursor"] = cursor
            url = (f"{PROMENADE}/sessions/{session_id}/messages?"
                   + urllib.parse.urlencode(query))
            st, tx = self._pedido("GET", url, None, None, TIMEOUT_GERAL,
                                   tentativas=TENTATIVAS_5XX)
            j = self._json_ou_erro("GET /sessions/{id}/messages", st, tx)
            acumulado.extend(j.get("messages", []) or [])
            cursor = j.get("next_cursor")
            if not cursor or len(acumulado) >= limite:
                break
        return acumulado[:limite]

    # -- §3.5 GET /sessions/{id} e GET /sessions -------------------------------

    def sessao(self, session_id: str) -> Dict[str, Any]:
        """Metadados da sessão — título derivado, timestamps (§5.1/§7)."""
        url = (f"{PROMENADE}/sessions/{session_id}?"
               + urllib.parse.urlencode({"tenant": TENANT}))
        st, tx = self._pedido("GET", url, None, None, TIMEOUT_GERAL,
                               tentativas=TENTATIVAS_5XX)
        return self._json_ou_erro("GET /sessions/{id}", st, tx)

    def sessoes(self, limite: int = 25) -> Dict[str, Any]:
        """Lista de sessões da identidade — vazia para A3 anônimo (§3.5).

        O *listing* é alimentado pela identidade logada; com cookie
        anônimo devolve `{"sessions":[],"next_cursor":null}` mesmo após
        criar e conversar em sessões.
        """
        url = (f"{PROMENADE}/sessions?"
               + urllib.parse.urlencode({"tenant": TENANT, "limit": limite}))
        st, tx = self._pedido("GET", url, None, None, TIMEOUT_GERAL,
                               tentativas=TENTATIVAS_5XX)
        return self._json_ou_erro("GET /sessions", st, tx)

    # -- §3.6 escrita restrita --------------------------------------------------

    def apagar_sessao(self, session_id: str) -> Tuple[int, str]:
        """POST /sessions/{id}/delete — rota real de exclusão do app (§3.6).

        Com A3 anônimo devolve 403 `forbidden` ("Anonymous sessions
        cannot be deleted") — registrado como comportamento do contrato.
        """
        url = (f"{PROMENADE}/sessions/{session_id}/delete?"
               + urllib.parse.urlencode({"tenant": TENANT}))
        return self._pedido("POST", url, None, None, TIMEOUT_GERAL,
                             tentativas=TENTATIVAS_5XX)

    def fixar_sessao(self, session_id: str, fixada: bool = True
                     ) -> Tuple[int, str]:
        """PATCH /sessions/{id} — escrita restrita (403 anônimo, §3.6)."""
        url = (f"{PROMENADE}/sessions/{session_id}?"
               + urllib.parse.urlencode({"tenant": TENANT}))
        return self._pedido("PATCH", url, {"pinned": fixada}, None,
                            TIMEOUT_GERAL)

    # -- §3.7/§3.8 retomada de stream -------------------------------------------

    def stream_ativo(self, session_id: str) -> Dict[str, Any]:
        """Sonda `/active-stream` — `{active:false}` quando ociosa (§3.7).

        Sessão inexistente também responde 200 `{active:false}` — exceção
        graciosa da família (§14.1).
        """
        url = (f"{PROMENADE}/sessions/{session_id}/active-stream?"
               + urllib.parse.urlencode({"tenant": TENANT}))
        st, tx = self._pedido("GET", url, None, None, TIMEOUT_GERAL,
                               tentativas=TENTATIVAS_5XX)
        return self._json_ou_erro("GET active-stream", st, tx)

    def retomar(self, stream_id: str, ultimo_evento: str = "0"
                ) -> List[Tuple[str, Dict[str, Any]]]:
        """Replay do stream — `last_event_id=0` retransmite tudo (§3.8).

        Exige `Accept: text/event-stream` (sem ele, 406); `last_event_id`
        é obrigatório na query (400 sem ele — §3.8); stream inexistente →
        404 `stream_not_found`. Devolve a lista de eventos do replay.
        """
        url = (f"{PROMENADE}/chat/resume/{stream_id}?"
               + urllib.parse.urlencode(
                   {"last_event_id": ultimo_evento, "tenant": TENANT}))
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"},
                                     method="GET")
        try:
            resp = self.opener.open(req, timeout=TIMEOUT_SSE)
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")
            raise ErroScout("GET /chat/resume", e.code, texto) from None
        return list(iterar_sse(resp))

    # -- §3.9 POST /feedback ------------------------------------------------------

    def feedback(self, session_id: str, message_id: str, rating: int,
                 motivos: Optional[List[str]] = None,
                 comentario: Optional[str] = None) -> Dict[str, Any]:
        """Avaliação de resposta — 👍=1 / 👎=0 (§3.9).

        No 👎 os motivos vão em `fields.reason` (aninhado, unidos por
        vírgula) — o enum é do servidor: `offensive`, `not_helpful`,
        `too_long`, `too_short`; fora disso, 422 `not_accepted`.
        Reavaliação da mesma mensagem → `overwritten: true`.
        """
        corpo: Dict[str, Any] = {
            "tenant": TENANT, "session_id": session_id,
            "message_id": message_id, "rating": rating,
        }
        if motivos and rating == 0:
            invalidos = [m for m in motivos if m not in MOTIVOS_FEEDBACK]
            if invalidos:
                raise ValueError(
                    "motivos inválidos: %s — aceitos: %s"
                    % (", ".join(invalidos), ", ".join(MOTIVOS_FEEDBACK)))
            corpo["fields"] = {"reason": ",".join(motivos)}
        if comentario:
            corpo["feedback"] = comentario
        st, tx = self._pedido("POST", f"{PROMENADE}/feedback", corpo, None,
                              TIMEOUT_GERAL, tentativas=TENTATIVAS_5XX)
        return self._json_ou_erro("POST /feedback", st, tx)

    # -- §3.10/§8 perguntas sugeridas ---------------------------------------------

    def perguntas_semeadas(self, simbolo: str, limite: int = 5
                           ) -> List[Dict[str, Any]]:
        """Catálogo de perguntas geradas para um símbolo (§8).

        O proxy responde 200 anônimo. **502 é por símbolo e transitório**
        (§3.10 — timeout do shard de backend; AAPL/MSFT/GOOGL/META
        falharam enquanto NVDA/TSLA/F/AMZN respondiam): re-tenta e, se
        persistir, sugere símbolos sabidamente estáveis.
        """
        url = (FINANCE_HOST + "/xhr/dynamic-seeded-questions?"
               + urllib.parse.urlencode({"symbol": simbolo,
                                         "limit": str(limite)}))
        st, tx = 0, ""
        for i in range(5):
            st, tx = self._pedido("GET", url, None, None, 60)
            if st == 200:
                j = json.loads(tx)
                return j.get("dynamic_questions") or []
            if st in (502, 503, 504) and i < 4:
                time.sleep(1.5 * (i + 1))   # §3.10 — shard transitório
                continue
        raise ErroScout("GET /xhr/dynamic-seeded-questions", st,
                        tx[:160] or "502 Request timed out (shard do símbolo)")

    # -- §2.1 mapa de serviços (/xhr/config) ---------------------------------

    def config_servicos(self) -> List[Tuple[str, int, str]]:
        """Sonda GET/POST /xhr/config?name=services — rota do loader
        SvelteKit (§2.1).

        GET → **405** `"GET method not allowed"`; POST com corpo fora
        do schema interno → **400** `{"message":"Schema mismatch for
        /xhr/config"}`. O mapa real (scout/scoutDev → promenade-api,
        timeout 30000; finance/financeProd → query1) chega embutido no
        HTML em blocos `data-sveltekit-fetched` (cache `data-ttl=120`).
        """
        url = FINANCE_HOST + "/xhr/config?name=services"
        st_g, tx_g = self._pedido("GET", url, None, None, 15)
        st_p, tx_p = self._pedido("POST", url, {"foo": "bar"}, None, 15)
        return [("GET /xhr/config?name=services", st_g, tx_g),
                ("POST /xhr/config (schema inválido)", st_p, tx_p)]

    # -- §14.1 método errado — GET /chat ---------------------------------------

    def chat_get(self) -> Tuple[int, str]:
        """GET /chat — método errado → **404** `{"code":"not_found",...}`
        (§14.1: não há 405; rota inexistente e método inexistente se
        confundem no mesmo 404). Repete 5xx vazio — a borda devolve 500
        transitório de forma intermitente (§14.7); em dias de borda
        agitada a proporção de 500 vazio sobe e o 404 pode exigir várias
        tentativas.
        """
        return self._pedido("GET", PROMENADE + "/chat", None, None, 15,
                            tentativas=6)

    # -- §13.6 deep link do chat nativo ----------------------------------------

    def sondar_deep_link(self, url: str) -> Tuple[int, str]:
        """GET no deep link /__ai/scout/chat — **404** para o cliente web
        comum (§13.6: o alvo é o webview do app nativo).
        """
        return self._pedido("GET", url, None, None, 15)

# ---------------------------------------------------------------------------
# Deep link do chat nativo (§13.6) — construtor verbatim do módulo
# "Dig deeper" dos artigos: prompt cortado em 500 caracteres + uuid
# opcional do artigo (flag enableArticleDdqNativeChat).
# ---------------------------------------------------------------------------

def deep_link(pergunta: str, uuid_artigo: Optional[str] = None) -> str:
    """Constrói a URL /__ai/scout/chat — deep link do chat nativo."""
    q = urllib.parse.urlencode({"prompt": pergunta[:500]})
    if uuid_artigo:
        q += "&" + urllib.parse.urlencode({"uuid": uuid_artigo})
    return f"{FINANCE_HOST}/__ai/scout/chat?{q}"


# ---------------------------------------------------------------------------
# Apresentação de respostas
# ---------------------------------------------------------------------------

class Tela:
    """Camada de apresentação — imprime respostas JSON e SSE no terminal."""

    @staticmethod
    def cabecalho_resposta(r: Dict[str, Any], duracao: float) -> None:
        print("─" * 78)
        modo = "SSE" if r.get("streaming") else "JSON"
        extra = ""
        if r.get("title"):
            extra = f"  ·  título: {r['title']}"
        print(f"◆ Scout ({modo}, {duracao:.1f}s){extra}")
        print("─" * 78)

    @staticmethod
    def corpo_resposta(r: Dict[str, Any]) -> None:
        conteudo = limpar_citacoes(r.get("content", ""))
        print(renderizar_md(conteudo))
        print()

    @staticmethod
    def rodape_resposta(r: Dict[str, Any]) -> List[str]:
        """Imprime fontes, ações e quota; devolve as follow-up numeradas."""
        fontes = r.get("grounding_sources") or []
        if fontes:
            print(f"◈ Fontes ({len(fontes)}):")
            for i, f in enumerate(fontes, 1):
                if isinstance(f, dict) and (f.get("title") or f.get("url")):
                    print("  " + formatar_fonte(f, i))
            print()
        acoes = r.get("suggested_actions") or []
        if acoes:
            print("◈ Ações sugeridas:")
            for a in acoes:
                pid = a.get("action_id", "?")
                params = ", ".join(f"{k}={v}" for k, v in
                                   (a.get("params") or {}).items())
                print(f"  ▸ {pid}({params})")
            print()
        meta = (r.get("metadata") or {})
        quota = meta.get("quota")
        if quota and isinstance(quota, dict) and quota.get("remaining_tokens") is not None:
            rest = quota.get("remaining_tokens", 0)
            limite = quota.get("limit_tokens", 100000)
            usado = quota.get("used_tokens", 0)
            renova = quota.get("reset_after_seconds")
            txt = (f"◈ Quota: {rest:,}/{limite:,} tokens restantes "
                   f"(usados {usado:,})")
            if renova is not None:
                txt += f" — renova em {segundos_legiveis(renova)}"
            print(txt)
            print()
        uso = meta.get("usage")
        if uso and isinstance(uso, dict) and uso.get("total_tokens"):
            modelo = uso.get("model") or "?"
            chamadas = len(uso.get("calls") or [])
            print(f"◈ Uso: {uso['total_tokens']:,} tokens · {chamadas} chamada(s) "
                  f"de modelo · {modelo}")
            print()
        follow = (r.get("follow_up_questions")
                  or r.get("follow_up") or r.get("suggestions") or [])
        if follow:
            print("◈ Perguntas de continuação (digite o número):")
            for i, p in enumerate(follow, 1):
                print(f"  {i}. {p}")
            print()
        return list(follow)

    @staticmethod
    def historico(msgs: List[Dict[str, Any]]) -> None:
        print("─" * 78)
        for m in msgs:
            papel = m.get("role", "?")
            quando = (m.get("created_at") or "")[:19].replace("T", " ")
            if papel == "user":
                print(f"┌ Você ({quando})")
                for linha in (m.get("content") or "").splitlines():
                    print("│ " + linha)
                print("└")
            else:
                print(f"┌ Scout ({quando})")
                for linha in renderizar_md(
                        limpar_citacoes(m.get("content") or "")).splitlines():
                    print("│ " + linha)
                fontes = m.get("grounding_sources") or []
                if fontes:
                    print("│")
                    print(f"│ fontes: {len(fontes)}")
                    for i, f in enumerate(fontes, 1):
                        if isinstance(f, dict):
                            print(f"│   [{i}] {(f.get('title') or '')[:68]}")
                print("└")
        print("─" * 78)


# ---------------------------------------------------------------------------
# REPL — conversa dinâmica
# ---------------------------------------------------------------------------

class Conversa:
    """REPL do chat — mantém sessão, contexto, streaming e última resposta."""

    def __init__(self, cliente: ClienteScout, sse: bool = True) -> None:
        self.cli = cliente
        self.sse = sse
        self.sessao_id: Optional[str] = None
        self.contexto: Optional[str] = None
        self.ultima_resposta: Optional[Dict[str, Any]] = None
        self.ultimos_follows: List[str] = []
        self.ultima_pergunta: str = ""
        self.transitorio = {"respostas": 0, "perguntas": 0}

    # -- envio --------------------------------------------------------------

    def enviar(self, mensagem: str) -> None:
        """Envia a mensagem na sessão corrente (criando-a se preciso)."""
        if not self.sessao_id:
            j = self.cli.criar_sessao()
            self.sessao_id = j["session_id"]
            print(f"⊕ Sessão criada: {self.sessao_id}")
        t0 = time.time()
        print()
        try:
            if self.sse:
                r = self.cli.chat_sse(
                    mensagem, self.sessao_id, self.contexto,
                    ao_evento=self._ao_evento)
            else:
                r = self.cli.chat(mensagem, self.sessao_id, self.contexto)
                r["streaming"] = False
        except ErroScout as e:
            self._tratar_erro(e)
            return
        dur = time.time() - t0
        if self.sse:
            print("\n")  # fecha a linha de deltas
        Tela.cabecalho_resposta(r, dur)
        Tela.corpo_resposta(r)
        self.ultimos_follows = Tela.rodape_resposta(r)
        self.ultima_resposta = r
        self.ultima_pergunta = mensagem
        self.transitorio["respostas"] += 1
        self.transitorio["perguntas"] += 1

    def _ao_evento(self, nome: str, dados: Dict[str, Any]) -> None:
        """Callback de streaming: status em uma linha, deltas no lugar."""
        if nome == "status.update":
            print(f"\r  · {dados.get('status', '…')[:60]:<60}", end="",
                  flush=True)
        elif nome == "content.delta":
            print(dados.get("delta", ""), end="", flush=True)
        elif nome == "stream.end":
            print("\r" + " " * 64 + "\r", end="", flush=True)

    def _tratar_erro(self, e: ErroScout) -> None:
        print(f"\n✖ {e}")
        if "quota_exceeded" in str(e):
            print("  A quota de 100.000 tokens/24 h desta identidade acabou (§6.4).")
            print("  Use /renovar para obter um novo A3 (nova identidade = nova quota).")
        elif e.status == 400 and "missing_identity" in e.corpo:
            print("  O cookie A3 expirou — use /renovar para re-autenticar.")
        elif e.status == 404 and "session_not_found" in e.corpo:
            print("  A sessão não pertence a esta identidade — use /nova.")
            self.sessao_id = None

    # -- comandos -------------------------------------------------------------

    def cmd_nova(self) -> None:
        j = self.cli.criar_sessao()
        self.sessao_id = j["session_id"]
        self.ultima_resposta = None
        self.ultimos_follows = []
        print(f"⊕ Nova sessão: {self.sessao_id}")

    def cmd_sse(self) -> None:
        self.sse = not self.sse
        print(f"⊕ Streaming: {'ON' if self.sse else 'OFF (JSON completo)'}")

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
        try:
            limite = int(resto) if resto.strip().isdigit() else 500
            msgs = self.cli.mensagens(self.sessao_id, limite=limite)
        except ErroScout as e:
            print(f"✖ {e}")
            return
        Tela.historico(msgs)
        print(f"({len(msgs)} mensagens)")

    def cmd_info(self) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        try:
            j = self.cli.sessao(self.sessao_id)
        except ErroScout as e:
            print(f"✖ {e}")
            return
        print(json.dumps(j, indent=2, ensure_ascii=False))

    def cmd_sessoes(self) -> None:
        j = self.cli.sessoes()
        itens = j.get("sessions") or []
        if not itens:
            print("⊕ Lista vazia — o listing exige identidade logada (§3.5).")
        for it in itens:
            print(f"  · {it.get('session_id')}  {(it.get('title') or '')[:48]}"
                  f"  {it.get('updated_at', '')[:19]}")

    def cmd_seeds(self, resto: str) -> None:
        if not resto.strip():
            print("uso: /seeds <pergunta>")
            return
        try:
            j = self.cli.seeds(resto.strip())
        except ErroScout as e:
            print(f"✖ {e}")
            return
        print(f"⊕ seed_key: {j.get('seed_key', '')}")
        print(f"⊕ cached:   {j.get('cached')}")
        if j.get("session_id"):
            print(f"⊕ sessão:   {j['session_id']} (criada pela rota, §5.4)")
        r = {"content": j.get("content", ""), "title": j.get("title"),
             "grounding_sources": j.get("grounding_sources") or [],
             "follow_up_questions": j.get("suggestions") or [],
             "suggested_actions": [], "metadata": {}, "streaming": False}
        Tela.cabecalho_resposta(r, 0.0)
        Tela.corpo_resposta(r)
        Tela.rodape_resposta(r)

    def cmd_ativas(self) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        j = self.cli.stream_ativo(self.sessao_id)
        if j.get("active"):
            print(f"⊕ stream ativo: {j.get('stream_id')}")
            print(f"  message_id:    {j.get('message_id')}")
            print(f"  resume_url:    {j.get('resume_url')}")
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
        stream_id = partes[0]
        ultimo = partes[1] if len(partes) > 1 else "0"
        try:
            eventos = self.cli.retomar(stream_id, ultimo)
        except ErroScout as e:
            print(f"✖ {e}")
            return
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
            print("uso: /feedback <0|1> [motivos] [comentário]")
            print(f"     motivos 👎: {', '.join(MOTIVOS_FEEDBACK)}")
            return
        rating = int(partes[0])
        motivos: List[str] = []
        comentario = None
        if len(partes) > 1:
            motivos = [m for m in partes[1].split(",") if m]
        if len(partes) > 2:
            comentario = partes[2]
        try:
            j = self.cli.feedback(self.sessao_id or "",
                                  self.ultima_resposta.get("message_id", ""),
                                  rating, motivos or None, comentario)
        except (ErroScout, ValueError) as e:
            print(f"✖ {e}")
            return
        nota = "👍" if rating == 1 else "👎"
        print(f"⊕ {nota} registrado em {j.get('recorded_at', '')} "
              f"(overwritten: {j.get('overwritten')})")

    def cmd_perguntas(self, resto: str) -> None:
        simbolo = resto.strip().upper() or "NVDA"
        try:
            qs = self.cli.perguntas_semeadas(simbolo)
        except ErroScout as e:
            print(f"✖ {e}")
            print(f"  símbolos sabidamente estáveis: "
                  f"{', '.join(SIMBOLOS_PERGUNTAS_OK)}")
            return
        if not qs:
            print(f"⊕ nenhuma pergunta gerada para {simbolo}")
            return
        print(f"◈ Perguntas sugeridas para {simbolo} (digite o número):")
        textos: List[str] = []
        for i, q in enumerate(qs, 1):
            texto = q.get("question_text") or q.get("question") or ""
            prio = q.get("priority")
            tag = ((q.get("tags") or {}).get("signal_type") or "")
            print(f"  {i}. {texto}" + (f"   [{tag}]" if tag else "")
                  + (f"  (prio {prio})" if prio is not None else ""))
            textos.append(texto)
        self.ultimos_follows = textos  # números também escolhem perguntas

    def cmd_quota(self) -> None:
        r = self.ultima_resposta
        if not r:
            print("✖ sem resposta ainda")
            return
        meta = (r.get("metadata") or {})
        if not meta:
            print("⊕ metadata vazio — no modo JSON o uso só chega no SSE (§5.2)")
            return
        print(json.dumps(meta.get("quota") or meta, indent=2))

    def cmd_renovar(self) -> None:
        if self.cli.renova_identidade():
            print("⊕ Novo A3 obtido — nova identidade, quota renovada (§6.4).")
            if self.sessao_id:
                print("  As sessões da identidade anterior ficam órfãs; "
                      "use /nova antes de conversar.")
                self.sessao_id = None
        else:
            print("✖ não consegui obter A3 — tente novamente")

    def cmd_apagar(self) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        st, tx = self.cli.apagar_sessao(self.sessao_id)
        if st == 403:
            print("⊕ 403 {forbidden: Anonymous sessions cannot be deleted}")
            print("  (rota real de exclusão do app — escrita exige sessão "
                  "logada, §3.6)")
        else:
            print(f"⊕ HTTP {st}: {tx[:120]}")
            if st == 200:
                self.sessao_id = None

    def cmd_config(self) -> None:
        """Sonda /xhr/config?name=services — mapa de serviços (§2.1)."""
        for rotulo, st, tx in self.cli.config_servicos():
            print(f"⊕ {rotulo} → HTTP {st}")
            try:
                j = json.loads(tx)
                print("  " + json.dumps(j, ensure_ascii=False)[:200])
            except ValueError:
                print("  " + tx[:200].replace("\n", " "))
        print("  (o mapa real chega embutido no HTML — data-sveltekit-fetched)")

    def cmd_deeplink(self, resto: str) -> None:
        """Constrói e sonda o deep link /__ai/scout/chat (§13.6)."""
        texto = resto.strip() or "What is going on with the market today?"
        url = deep_link(texto)
        print(f"⊕ deep link (§13.6 — corte em 500 caracteres):\n  {url}")
        st, tx = self.cli.sondar_deep_link(url)
        if st == 404:
            print("⊕ GET /__ai/scout/chat → HTTP 404 — rota do webview do "
                  "app nativo, não do cliente web")
        else:
            print(f"⊕ GET /__ai/scout/chat → HTTP {st}")
            print("  " + tx[:160].replace("\n", " "))

    def cmd_exportar(self, resto: str) -> None:
        if not self.sessao_id:
            print("✖ sem sessão corrente")
            return
        caminho = resto.strip() or f"scout_{self.sessao_id[:8]}.json"
        try:
            msgs = self.cli.mensagens(self.sessao_id)
            info = self.cli.sessao(self.sessao_id)
        except ErroScout as e:
            print(f"✖ {e}")
            return
        pacote = {
            "sessao": info,
            "mensagens": msgs,
            "exportado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "contrato": "yf-scout-ai.md §3.4/§5.3",
        }
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(pacote, f, indent=2, ensure_ascii=False)
        print(f"⊕ exportado: {caminho} ({len(msgs)} mensagens)")

    # -- laço principal ----------------------------------------------------------

    AJUDA = """
comandos:
  (texto livre)        envia a mensagem na sessão corrente (conversa dinâmica)
  1..N                 envia a pergunta de continuação / sugerida numerada
  /nova                cria nova sessão de chat
  /sse                 alterna streaming SSE ⇄ JSON completo
  /contexto <valor>    fixa âncora de conteúdo (ex.: ticker:AAPL) — vazio remove
  /historico [n]       histórico da sessão (n = limite, default 500)
  /info                metadados e título derivado da sessão
  /sessoes             lista de sessões da identidade (vazia para anônimo)
  /seeds <pergunta>    resposta semeada com cache (POST /chat/seeds)
  /ativas              sonda /active-stream da sessão
  /retomar [id [ev]]   replay de stream (default: o ativo; ev=0 retransmite)
  /feedback 0|1 ...    avalia a última resposta — 👎 aceita motivos:
                       offensive, not_helpful, too_long, too_short
  /perguntas [SIMB]    perguntas sugeridas do símbolo (default NVDA)
  /quota               estado da quota da última resposta SSE
  /renovar             novo A3 (nova identidade = quota renovada)
  /apagar              POST /sessions/{id}/delete (403 anônimo — §3.6)
  /config              sonda /xhr/config?name=services — mapa de serviços (§2.1)
  /deeplink [texto]    constrói e sonda /__ai/scout/chat (§13.6)
  /exportar [arq]      exporta a conversa em JSON
  /ajuda               esta ajuda
  /sair                encerra
"""

    def executar(self) -> None:
        print("╭──────────────────────────────────────────────────────────────╮")
        print("│  Scout AI — chat dinâmico · Promenade API (Yahoo Finance)    │")
        print("╰──────────────────────────────────────────────────────────────╯")
        print(f"  identidade A3: {'ok' if any(c.name == 'A3' for c in self.cli.jar) else 'FALTA'}"
              f"  ·  streaming: {'ON' if self.sse else 'OFF'}"
              f"  ·  tenant: {TENANT}")
        print("  digite /ajuda para os comandos; /sair encerra.\n")
        while True:
            try:
                linha = input("scout> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not linha:
                continue
            if linha in ("/sair", "/exit", "/quit"):
                break
            if linha in ("/ajuda", "/help", "?"):
                print(self.AJUDA)
                continue
            if linha.isdigit() and self.ultimos_follows:
                n = int(linha)
                if 1 <= n <= len(self.ultimos_follows):
                    self.enviar(self.ultimos_follows[n - 1])
                    continue
            if linha.startswith("/"):
                cmd, _, resto = linha.partition(" ")
                cmd = cmd.lower()
                desp = {
                    "/nova": lambda: self.cmd_nova(),
                    "/sse": self.cmd_sse,
                    "/contexto": lambda: self.cmd_contexto(resto),
                    "/historico": lambda: self.cmd_historico(resto),
                    "/info": self.cmd_info,
                    "/sessoes": self.cmd_sessoes,
                    "/seeds": lambda: self.cmd_seeds(resto),
                    "/ativas": self.cmd_ativas,
                    "/retomar": lambda: self.cmd_retomar(resto),
                    "/feedback": lambda: self.cmd_feedback(resto),
                    "/perguntas": lambda: self.cmd_perguntas(resto),
                    "/quota": self.cmd_quota,
                    "/renovar": self.cmd_renovar,
                    "/apagar": self.cmd_apagar,
                    "/config": self.cmd_config,
                    "/deeplink": lambda: self.cmd_deeplink(resto),
                    "/exportar": lambda: self.cmd_exportar(resto),
                }
                acao = desp.get(cmd)
                if acao is None:
                    print(f"✖ comando desconhecido: {cmd} — /ajuda lista os válidos")
                    continue
                try:
                    acao()
                except ErroScout as e:
                    self._tratar_erro(e)
                print()
                continue
            self.enviar(linha)
            print()
        print("⊕ até logo.")


# ---------------------------------------------------------------------------
# Modo não-interativo
# ---------------------------------------------------------------------------

def modo_lote(args: argparse.Namespace) -> int:
    """Executa uma única operação e sai (para scripting)."""
    cli = ClienteScout()
    if not cli.bootstrap():
        print("✖ bootstrap falhou — sem cookie A3", file=sys.stderr)
        return 2

    if args.perguntas:
        try:
            qs = cli.perguntas_semeadas(args.perguntas, args.limite or 5)
        except ErroScout as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        for q in qs:
            print(json.dumps({
                "id": q.get("id"), "question_text": q.get("question_text"),
                "priority": q.get("priority"),
                "signal_type": (q.get("tags") or {}).get("signal_type"),
                "source_workflows": (q.get("additional_info") or {})
                    .get("source_workflows"),
            }, ensure_ascii=False))
        return 0

    if args.config:
        for rotulo, st, tx in cli.config_servicos():
            print(f"{rotulo} → HTTP {st}")
            print("  " + tx[:200].replace("\n", " "))
        st, tx = cli.chat_get()
        print(f"GET /chat (método errado, §14.1) → HTTP {st}"
              + (" — 500 vazio: transitório da borda (§14.7), re-tente"
                 if st == 500 and not tx.strip() else ""))
        print("  " + tx[:200].replace("\n", " "))
        return 0

    if args.deeplink:
        url = deep_link(args.deeplink)
        print(f"deep link (§13.6): {url}")
        st, tx = cli.sondar_deep_link(url)
        print(f"GET /__ai/scout/chat → HTTP {st}"
              f"{' — 404 esperado: rota do webview nativo' if st == 404 else ''}")
        return 0

    if not args.pergunta:
        print("✖ informe --pergunta, --seeds, --perguntas, --config ou "
              "--deeplink (ou rode sem argumentos para o REPL)", file=sys.stderr)
        return 2

    if args.json_bruto:
        j = (cli.seeds(args.pergunta) if args.seeds
             else cli.chat(args.pergunta, contexto=args.contexto))
        print(json.dumps(j, indent=2, ensure_ascii=False))
        return 0

    conv = Conversa(cli, sse=args.sse)
    conv.contexto = args.contexto
    try:
        if args.seeds:
            conv.cmd_seeds(args.pergunta)
        else:
            conv.enviar(args.pergunta)
    except ErroScout as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="scout_chat.py",
        description="Chat dinâmico com o Scout AI do Yahoo Finance "
                    "(Promenade API — contrato yf-scout-ai.md).")
    ap.add_argument("-q", "--pergunta", metavar="TEXTO",
                    help="pergunta única (sem REPL)")
    ap.add_argument("--sse", action="store_true", default=False,
                    help="força streaming SSE na pergunta única")
    ap.add_argument("--seeds", action="store_true",
                    help="usa POST /chat/seeds (cache por identidade)")
    ap.add_argument("--contexto", metavar="VALOR",
                    help="âncora de conteúdo (ex.: ticker:AAPL)")
    ap.add_argument("--perguntas", metavar="SIMBOLO",
                    help="lista perguntas sugeridas do símbolo e sai")
    ap.add_argument("--config", action="store_true",
                    help="sonda /xhr/config?name=services (§2.1) + GET /chat "
                         "(404, §14.1) e sai")
    ap.add_argument("--deeplink", metavar="TEXTO",
                    help="constrói e sonda o deep link /__ai/scout/chat "
                         "(§13.6) e sai")
    ap.add_argument("--limite", type=int, default=None,
                    help="limite do catálogo de perguntas")
    ap.add_argument("--json-bruto", action="store_true",
                    help="imprime o envelope JSON integral da resposta")
    args = ap.parse_args()

    if args.pergunta or args.seeds or args.perguntas \
            or args.config or args.deeplink:
        return modo_lote(args)

    cli = ClienteScout()
    if not cli.bootstrap():
        print("✖ bootstrap falhou — sem cookie A3 (fc.yahoo.com)", file=sys.stderr)
        return 2
    Conversa(cli, sse=True).executar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
