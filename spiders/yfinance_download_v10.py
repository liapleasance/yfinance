#!/usr/bin/env python3
"""YAHOO FINANCE BUNDLE DOWNLOADER - V10.0
===========================================
Baixa o núcleo do frontend SvelteKit de finance.yahoo.com:

  1. auto-detecta os entries vivos (start.* / app.*) no HTML da homepage;
  2. extrai o manifesto m.f do entry e baixa o grafo de imports JS;
  3. crawleia as rotas SSR: a rota vira .html dentro de pages/ —
     /<seg>/ -> pages/<seg>/index.html, /<a>/<b>/ ->
     pages/<a>/<b>.html, /quote/<TICKER>/ -> pages/quote/index.html e
     /quote/<TICKER>/<sub>/ -> pages/quote/<sub>.html (o ticker é
     parâmetro da rota, não diretório do espelho; rotas que caem no
     MESMO arquivo — dois tickers — rendem um único exemplar: o
     primeiro URL que responder vence); dados SSR ao lado:
     __data.json em rotas-container, <nome>.data.json em rotas-folha;
  4. descobre o webcore dinâmico citado no HTML das páginas;
  5. scan recursivo de imports em .js/.mjs até convergir.

Sessão: por padrão colhe o cookie A3 em fc.yahoo.com, fecha o
consentimento em guce.yahoo.com e envia o cofre (*.yahoo.com) nas
requisições, gravando yahoo_session.json (chmod 600) + export Netscape
yahoo_cookies.txt NO DIRETÓRIO DE SAÍDA (--output). Com --no-session
nada disso acontece.

Escopo do download (allowlist por host + caminho) — só o NÚCLEO:
  finance.yahoo.com/assets/_app/immutable/**   (entries, chunks, nodes)
  finance.yahoo.com/assets/_app/cosaic/**      (CSS dos gráficos)
  finance.yahoo.com/{__rapidworker-1.2.js, _service-worker.js,
                     assets/_app/version.json, xhr/i18n}
  s.yimg.com/uc/finance/webcore/**, /uc/finance/srchjs/**, /uc/sf/**
  s.yimg.com/fe/yf-fe-mono/**, /ss/**, /cx/, /oa/, /aaq/f10d509c/
  consent.cmp.oath.com/**, cdn.payments.yahoo.com/checkout-component/**
  cdn.jsdelivr.net/npm/protobufjs@7.1.2/dist/minimal/protobuf.min.js
  Sem --include-extras ficam de fora o resto do jsdelivr e outros aaq/.
Fontes e imagens NÃO são baixados (proposital); CSS só com --include-css.

Uso:
  python yfinance_download_v10.py [--entries URL ...] [--pages URL ...]
      [--output DIR] [--workers N] [--per-host N] [--rounds N]
      [--timeout S] [--no-crawl] [--revalidate] [--no-retry-on-drift]
      [--include-extras] [--modern-only] [--no-session] [--jar F]
      [--impersonate TARGET] [--only-fixed] [--include-css]
      [--include-i18n]

FIXED_ASSET_URLS é apenas UMA das 4 fontes da fila de download (as
outras: entries + manifesto m.f, <script src> do crawl SSR, webcore
dinâmico do HTML e o scan recursivo de imports — este último
enfileira qualquer URL .js citada em TEXTO de .js já baixado dentro
da allowlist, ex.: web-analytics-debugger-v1.js citado dentro de
analytics-3.90.0.js). Com --only-fixed a fila vira EXATAMENTE o
FIXED_ASSET_URLS: sem entries, sem crawl e sem scan de imports.

O conteúdo baixado vai para --output (padrão: finance-yahoo-com/, na
pasta do script — layout plano, sem subpasta bundle_<hash>).

MUDANÇAS DO V10 (todas validadas empiricamente com Playwright/Chromium
navegando no site ao vivo — tráfego real capturado em 4 fases):

  [D1] version.json com cache-bust: a URL fixa vinha de cache de borda
       ATS com até 66 min de atraso (4/4 leituras divergiram do valor
       fresco), cegando/falseando o detector de build drift. Agora o
       probe usa ?cb=<epoch-ms>, que muda a chave de cache da borda e
       devolve sempre o valor de origem.
  [D2] protobufjs promovido a NÚCLEO: o streamer de cotações
       (streamer.mjs + streamer.worker.mjs + _staticFinProtobuf.mjs)
       importa protobufjs@7.1.2 do jsdelivr em TODA carga de página —
       dependência funcional, não "extra". Sem ele o bundle perde o
       runtime de decodificação das cotações ao vivo.
  [D3] --include-css: o browser real carrega ~119 CSS de immutable/
       assets/ + 2 CSS de _app/cosaic/ por carga de página; sem CSS o
       espelho offline não renderiza. Descoberta via <link> do HTML
       SSR + arrays m.f dos chunks ("../assets/X.css") + referências
       em texto de JS; mapeados para assets/ e cosaic/.
  [D4] --include-i18n: o XHR /xhr/i18n (~251 KB por família de rota)
       alimenta TODOS os textos da UI em toda navegação; sem ele o
       espelho offline renderiza UI sem legendas. Gravado em i18n/.
  [D5] cofre de sessão + export Netscape passam a morar no diretório
       de --output (antes: sempre na pasta do script, criando pastas
       fantasmas em runs com --output customizado).

  Mantido do v9 (confirmado empiricamente): AE conservadora por
  backend (o site serve gzip para ~99% dos .js mesmo para Chrome com
  br/zstd); webcore estável entre builds (não re-baixa com cache
  local); __data.json segue sendo baixado para as rotas crawleadas
  (dados SSR úteis ao espelho) embora o browser hidrate via XHR às
  APIs e nunca peça __data.json na navegação client-side.

CORREÇÕES V10.1 (revisão linha a linha; só a F4 muda comportamento
observável do crawl):

  [F1] export_netscape() grava atomicamente (atomic_write), como o
       cofre JSON — sem meia-escrita se o processo cair no meio.
  [F2] main(): encanamento vestigial de multi-comando removido
       (set_defaults fn= / args.fn) — chamada direta a cmd_download.
  [F3] ramo urllib do Transport.request: corpo do erro lido em
       err_body, sem sombrear o corpo do POST (`body`).
  [F4] crawl SSR determinístico: rotas que mapeiam para o mesmo
       arquivo local (dois tickers de /quote/<TICKER>/) são
       agrupadas — crawlea o primeiro URL que responder; os demais
       são pulados (antes: corrida de sobreposição entre 8 workers
       concorrentes, "último a gravar vence").

Versão: v10.1 — v10 + F1-F4. A versão de TOOL_VERSION alimenta banners
do CLI, --help e o campo "tool" do manifest.json.
"""

import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import html
import json
import os
import posixpath
import random
import re
import sys
import threading
import time
import zlib
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlencode, urljoin, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_NAME = "manifest.json"

# Pasta principal (nome do site https://finance.yahoo.com/ em kebab-case):
# todo o conteúdo baixado, o cofre de sessão e o export de cookies vão
# morar aqui DIRETAMENTE (layout plano, sem subpasta por build).
SITE_DIR_NAME = "finance-yahoo-com"
SITE_ROOT = os.path.join(SCRIPT_DIR, SITE_DIR_NAME)

TOOL_VERSION = "10.1"
TOOL_NAME = "yfinance_download_v10.py"
TOOL_ID = f"{TOOL_NAME}/v{TOOL_VERSION}"

# ---- Dependências opcionais -------------------------------------------
# Cascade de transporte: curl_cffi (impersonation) -> httpx (HTTP/2)
# -> requests -> urllib (stdlib, sempre presente).

try:
    from curl_cffi import requests as _cffi_requests
    _CFFI = _cffi_requests
except Exception:
    _CFFI = None

try:
    from typing import get_args as _get_args
    from curl_cffi.requests.impersonate import BrowserTypeLiteral as _BTL
    _CFFI_TARGETS = frozenset(_get_args(_BTL))
except Exception:
    _CFFI_TARGETS = frozenset()

try:
    import httpx as _httpx
    _HTTPX = _httpx
except Exception:
    _HTTPX = None

try:
    import requests as _requests
except Exception:
    _requests = None

try:
    import brotli as _brotli
except Exception:
    _brotli = None

try:
    import zstandard as _zstd
except Exception:
    _zstd = None

RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


# ---- Impersonation: UA e sec-ch-ua coerentes com o target -------------

_UA_BY_TARGET: Dict[str, str] = {
    # Chrome 155: captura real do operador (DevTools -> Copy as cURL).
    "chrome155": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/155.0.0.0 Safari/537.36"),
    "chrome133a": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/133.0.0.0 Safari/537.36"),
    "chrome131": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Safari/537.36"),
    "chrome124": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"),
    "chrome120": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"),
}
_SECCH_BY_TARGET: Dict[str, str] = {
    # Ordem de brands conforme a captura viva: no Chrome 155 "Google Chrome"
    # vem primeiro (o GREASE muda a cada major; captura: Not(A:Brand v24).
    "chrome155": ('"Google Chrome";v="155", "Chromium";v="155", '
                  '"Not(A:Brand";v="24"'),
    "chrome133a": ('"Chromium";v="133", "Not(A:Brand";v="99", '
                   '"Google Chrome";v="133"'),
    "chrome131": ('"Chromium";v="131", "Not(A:Brand";v="99", '
                  '"Google Chrome";v="131"'),
    "chrome124": ('"Chromium";v="124", "Not(A:Brand";v="8", '
                  '"Google Chrome";v="124"'),
    "chrome120": ('"Chromium";v="120", "Not(A:Brand";v="24", '
                  '"Google Chrome";v="120"'),
}
_DEFAULT_TARGET = "chrome155"
_DEFAULT_UA = _UA_BY_TARGET[_DEFAULT_TARGET]
_DEFAULT_SECCH = _SECCH_BY_TARGET[_DEFAULT_TARGET]
_GREASE_NOVO = '"Not(A:Brand";v="24"'
_GREASE_CLASSICO = '"Not(A:Brand";v="99"'

ACCEPT_HTML = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/jxl,image/avif,image/webp,image/apng,*/*;q=0.8,"
               "application/signed-exchange;v=b3;q=0.7")
# Locale do operador — captura real do navegador (pt-BR,pt;q=0.9).
ACCEPT_LANGUAGE = "pt-BR,pt;q=0.9"
# Valor de REFERÊNCIA do módulo (importável por testes). O valor
# EFETIVO de cada requisição é Transport.accept_encoding, calculado a
# partir do backend ATIVO — ver Transport.__init__: se a impersonation
# falhar e o transporte cair em httpx/requests/urllib, não se anuncia
# br/zstd sem os módulos que os decodificam (senão o servidor responde
# comprimido e bytes brutos são gravados como se fossem .js).
ACCEPT_ENCODING = ("gzip, deflate"
                   + (", br" if (_CFFI is not None or _brotli is not None)
                      else "")
                   + (", zstd" if (_CFFI is not None or _zstd is not None)
                      else ""))

CDN_BASE = "https://finance.yahoo.com/assets/_app/immutable/"
WEBCORE_PREFIX = "https://s.yimg.com/uc/finance/"

DISCOVERY_PAGES = [
    "https://finance.yahoo.com/",
    "https://finance.yahoo.com/markets/",
    "https://finance.yahoo.com/markets/commodities/",
    "https://finance.yahoo.com/markets/crypto/all/",
    "https://finance.yahoo.com/markets/currencies/",
    "https://finance.yahoo.com/quote/TSLA/",
    "https://finance.yahoo.com/quote/TSLA/earnings-calls/",
    "https://finance.yahoo.com/quote/TSLA/key-statistics/",
    "https://finance.yahoo.com/quote/TSLA/options/",
    "https://finance.yahoo.com/quote/TSLA/financials/",
    "https://finance.yahoo.com/quote/TSLA/profile/",
    "https://finance.yahoo.com/quote/TSLA/history/",
    "https://finance.yahoo.com/markets/options/most-active/",
    "https://finance.yahoo.com/quote/TSLA/holders/",
    "https://finance.yahoo.com/research-hub/screener/",
    "https://finance.yahoo.com/calendar",
]

# Fila fixa MÍNIMA — só o essencial de runtime/consentimento citado pelo
# HTML vivo. Excluídos intencionalmente (propaganda/analytics/vídeo/
# pagamentos/build-machinery): cmp.js, _service-worker.js,
# __rapidworker-1.2.js, version.json, analytics3.js, aaq/*, yf-fe-mono/*
# e yp-checkout.js. Nota: o version.json saiu da fila de arquivos — a
# detecção de build drift agora consulta a URL ao vivo no fim do run
# (_fetch_version_json), em vez de ler a cópia local do bundle.
# [D2-v10] protobufjs@7.1.2 promovido de "extra" a NÚCLEO: o streamer
# de cotações (streamer.mjs, streamer.worker.mjs e
# _staticFinProtobuf.mjs) o importa em TODA carga de página — o browser
# real o busca na primeira renderização. O .map fica em --include-extras.
FIXED_ASSET_URLS = [
    "https://s.yimg.com/uc/finance/srchjs/1.2.50/js/finSearch.modern.js",
    "https://s.yimg.com/oa/consent.js",
    "https://s.yimg.com/oa/guce.js",
    "https://s.yimg.com/cx/acookie/acookie.js",
    "https://s.yimg.com/uc/sf/0.2.18/js/safe.modern.js",
    "https://s.yimg.com/oa/guce-iframe.js",
    "https://s.yimg.com/oa/build/js/site-6e2f3260.js",
    "https://cdn.jsdelivr.net/npm/protobufjs@7.1.2/dist/minimal/"
    "protobuf.min.js",
]

ALLOWED_SCAN_HOSTS = ("yahoo.com", "yimg.com", "oath.com", "jsdelivr.net")
SKIP_EXTENSIONS = (".css",)
TEXT_EXTS = (".js", ".mjs", ".json")
ROOT_SUBDIR_HOSTS = {
    "cdn.payments.yahoo.com": "cdn_payments_yahoo_com",
}
BUNDLE_SUBDIRS = ("entry", "chunks", "nodes", "webcore", "pages", "yimg")


# ---- Escopo do run (allowlist host+caminho) ---------------------------
# Estado do run corrente, definido uma vez no início de run_download.

SCOPE: Dict[str, bool] = {"extras": False, "modern_only": False,
                         "include_css": False}


def set_scope(extras: bool = False, modern_only: bool = False,
              include_css: bool = False) -> None:
    """Fixa o escopo global usado por is_denied_url()/is_core_url()."""
    SCOPE["extras"] = bool(extras)
    SCOPE["modern_only"] = bool(modern_only)
    SCOPE["include_css"] = bool(include_css)


def css_enabled() -> bool:
    """--include-css ativo? (CSS deixa de ser extensão pulada.)"""
    return bool(SCOPE.get("include_css"))


# [D4-v10] famílias de rota observadas no XHR /xhr/i18n do site vivo
# (fases A-D da captura Playwright); a página "common" vem em todas.
I18N_FAMILIES = ("common,home", "common,quote,leaf-chart")
I18N_LANG = "en-US"


def skip_ext(path: str) -> bool:
    """Extensões puladas: .css só quando --include-css está DESLIGADO."""
    exts: Tuple[str, ...] = () if css_enabled() else SKIP_EXTENSIONS
    return path.lower().endswith(exts)


_CORE_RULES = (
    ("finance.yahoo.com", "/assets/_app/immutable/", False),
    # [D3-v10] CSS dos gráficos (chartQuote/chartQuoteEvents) — família
    # observada no tráfego real em /assets/_app/cosaic/<ver>/css/.
    ("finance.yahoo.com", "/assets/_app/cosaic/", False),
    ("finance.yahoo.com", "/__rapidworker-1.2.js", True),
    ("finance.yahoo.com", "/assets/_app/version.json", True),
    ("finance.yahoo.com", "/__data.json", True),
    ("finance.yahoo.com", "/_service-worker.js", True),
    # [D4-v10] pacotes de tradução da UI (XHR observado em toda navegação).
    ("finance.yahoo.com", "/xhr/i18n", True),
    ("s.yimg.com", "/uc/finance/webcore/", False),
    ("s.yimg.com", "/uc/finance/srchjs/", False),
    ("s.yimg.com", "/uc/sf/", False),
    ("s.yimg.com", "/fe/yf-fe-mono/", False),
    ("s.yimg.com", "/ss/", False),
    ("s.yimg.com", "/cx/", False),
    ("s.yimg.com", "/oa/", False),
    ("s.yimg.com", "/aaq/f10d509c/", False),
    ("consent.cmp.oath.com", "/", False),
    ("cdn.payments.yahoo.com", "/checkout-component/", False),
    # [D2-v10] protobufjs@7.1.2 — runtime do streamer de cotações
    # (importado por streamer.mjs/streamer.worker.mjs). SÓ este caminho:
    # o resto do jsdelivr segue exigindo --include-extras.
    ("cdn.jsdelivr.net", "/npm/protobufjs@7.1.2/dist/minimal/", False),
)
_EXTRA_RULES = (
    ("s.yimg.com", "/aaq/", False),
    ("cdn.jsdelivr.net", "/", False),
)


def _rule_match(host: str, path: str, rules) -> bool:
    for rule_host, prefix, exact in rules:
        if host == rule_host and (path == prefix if exact
                                  else path.startswith(prefix)):
            return True
    return False


def is_core_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    if _rule_match(host, path, _CORE_RULES):
        return True
    return SCOPE["extras"] and _rule_match(host, path, _EXTRA_RULES)


def is_legacy_url(url: str) -> bool:
    """Fallbacks para navegadores antigos (nomodule) — opt-out via
    --modern-only."""
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() != "s.yimg.com":
        return False
    path = parsed.path.lower()
    if path.startswith("/uc/finance/webcore/"):
        return path.endswith(".js")
    if path.startswith("/uc/finance/srchjs/"):
        return ".modern." not in path
    return False


def host_in_allowlist(host: str) -> bool:
    """Suffix-match estrito — yahoo.com.evil.tld NÃO casa yahoo.com."""
    host = (host or "").lower().lstrip(".")
    return any(host == h or host.endswith("." + h)
               for h in ALLOWED_SCAN_HOSTS)


# ---- Denylist (propaganda/rastreadores/vídeo nunca são baixados) ------

_DENIED_HOSTS: Dict[str, str] = {
    "google.com": "google",
    "googleapis.com": "google",
    "googleusercontent.com": "google",
    "gstatic.com": "google",
    "googletagmanager.com": "google",
    "googlesyndication.com": "google",
    "googleadservices.com": "google",
    "doubleclick.net": "google",
    "youtube.com": "google",
    "ytimg.com": "google",
    "youtu.be": "google",
    "recaptcha.net": "google",
    "firebaseio.com": "google",
    "crashlytics.com": "google",
    "amazon.com": "amazon",
    "amazonaws.com": "amazon",
    "amazon-adsystem.com": "amazon",
    "media-amazon.com": "amazon",
    "ssl-images-amazon.com": "amazon",
    "a2z.com": "amazon",
    "primevideo.com": "amazon",
    "twitter.com": "twitter",
    "twimg.com": "twitter",
    "x.com": "twitter",
    "t.co": "twitter",
    "ad-delivery.net": "adshield",
    "p-n.io": "adshield",
    "pushly.com": "adshield",
    "scorecardresearch.com": "tracker",
    "comscore.com": "tracker",
    "taboola.com": "propaganda",
    "outbrain.com": "propaganda",
    "criteo.com": "propaganda",
    "rubiconproject.com": "propaganda",
    "pubmatic.com": "propaganda",
    "openx.net": "propaganda",
    "adnxs.com": "propaganda",
    "casalemedia.com": "propaganda",
}

_DENIED_URL_RE = [
    ("propaganda", re.compile(
        r"securepubads|doubleclick|googlesyndication|googleadservices"
        r"|adtech(?:us|de)?\.|\badsystem\b|\badservice\b|\badserver\b", re.I)),
    ("adshield", re.compile(
        r"ad-delivery|(?<![a-z0-9])p-n\.io|adshield", re.I)),
    ("propaganda", re.compile(
        r"(?<![a-z0-9])(?:benji|live-connect|liveconnect|badads|adkit)"
        r"(?![a-z0-9])", re.I)),
    ("propaganda", re.compile(
        r"(?<![a-z0-9])(?:moatads|adsafeprotected|casalemedia|rubiconproject"
        r"|pubmatic|criteo|openx|indexww|yieldmo|sharethrough|taboola"
        r"|outbrain|teads|spotx|springserve|smartadserver|adnxs|adform"
        r"|sonobi|gumgum)(?![a-z0-9])", re.I)),
    ("propaganda", re.compile(r"(?:^|/)du/", re.I)),
    ("video", re.compile(
        r"\.(?:mp4|m3u8|mpd|webm|m4s|ts|aac)(?:[?#]|$)", re.I)),
    ("video", re.compile(
        r"/rx/ev/|(?<![a-z0-9])(?:evplayer|shaka|rmp-vast|omid|omweb"
        r"|comscore|scorecardresearch)(?![a-z0-9])", re.I)),
]


def _denied_host_category(host: str) -> Optional[str]:
    host = host.lower().lstrip(".")
    for domain, cat in _DENIED_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return cat
    return None


class DenyStats:
    """Contadores de exclusão por categoria (para o relatório final)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counts: Dict[str, int] = {}
        self.samples: Dict[str, List[str]] = {}

    def record(self, url: str, category: str) -> None:
        with self._lock:
            self.counts[category] = self.counts.get(category, 0) + 1
            sample = self.samples.setdefault(category, [])
            if url not in sample and len(sample) < 40:
                sample.append(url)

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {"categorias": dict(sorted(self.counts.items())),
                    "amostras": {k: sorted(v)
                                 for k, v in self.samples.items()}}


DENY_STATS = DenyStats()


def is_denied_url(url: str) -> bool:
    """True = NÃO baixar. Ordem: hosts/regex proibidos -> fora do núcleo
    -> legado."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    category = _denied_host_category(parsed.hostname or "")
    if category:
        DENY_STATS.record(url, category)
        return True
    for cat, rx in _DENIED_URL_RE:
        if rx.search(url):
            DENY_STATS.record(url, cat)
            return True
    if not is_core_url(url):
        DENY_STATS.record(url, "fora_do_nucleo")
        return True
    if SCOPE["modern_only"] and is_legacy_url(url):
        DENY_STATS.record(url, "legado")
        return True
    return False


# ---- Regexes de extração ----------------------------------------------

RE_ENTRY_ABS = re.compile(
    r'https?://[^\s"\'<>]*/assets/_app/immutable/entry/'
    r'(?:app|start)\.[A-Za-z0-9_-]+\.js')
# Prefixo (?:\.{0,2}/)* aceita "./", "../", "/" e repetições: páginas
# SSR de nível mais profundo (ex.: /markets/) referenciam o entry como
# import("../assets/_app/immutable/entry/start.<HASH>.js").
RE_ENTRY_REL = re.compile(
    r'["\'](?:\.{0,2}/)*(assets/_app/immutable/entry/'
    r'(?:app|start)\.[A-Za-z0-9_-]+\.js)["\']')
RE_ENTRY_IMPORT = re.compile(
    r'import\(["\'](?:\.{0,2}/)*(assets/_app/immutable/entry/'
    r'(?:app|start)\.[A-Za-z0-9_-]+\.js)["\']\)')
RE_MANIFEST = re.compile(
    r'm\.f\s*=\s*(?:\(m\.f\s*=\s*)?\[\s*((?:["\'][^"\']*["\']\s*,?\s*)+)\s*\]')
RE_MANIFEST_FALLBACK = re.compile(
    r'["\'](\.\./(?:chunks|nodes)/[^"\']+?\.(?:js|mjs))["\']')
RE_TEMPLATE = re.compile(r'\$\{[^}]+\}|%s')
RE_JS_URL = re.compile(
    r'https?://[^\s"\'<>\\)]+?\.(?:js|mjs)(?![A-Za-z0-9_])', re.IGNORECASE)
RE_ATTR_JS = re.compile(
    r'(?:src|href)\s*=\s*["\']([^"\'#?\s]+?\.(?:js|mjs))(?:[?#][^"\']*)?["\']',
    re.IGNORECASE)
RE_IMPORT_REL = re.compile(
    r'["\']((?:\.{0,2}/)?(?:chunks|nodes|webcore)[^"\']*?\.(?:js|mjs))["\']',
    re.IGNORECASE)
RE_IMPORT_SAMEDIR_WEB = re.compile(
    r'["\'](\.\/[A-Za-z0-9_./@-]+\.(?:js|mjs))["\']')
RE_IMPORT_SAMEDIR = re.compile(r'["\'](\.\/[A-Za-z0-9_.\-]+\.(?:js|mjs))["\']')
# [D3-v10] CSS citado em texto de JS — os chunks SvelteKit carregam os
# arrays m.f com "../assets/Componente.<hash>.css" (mesma sintaxe dos
# módulos JS). Só usado com --include-css.
RE_IMPORT_CSS = re.compile(
    r'["\']((?:\.{1,2}/)?assets/[A-Za-z0-9_.\-]+\.css)["\']')
# [D3-v10] <link rel="stylesheet" href="...css"> do HTML SSR (as
# páginas crawleadas trazem os CSS da rota como links relativos).
RE_LINK_CSS = re.compile(
    r'<link\b[^>]*?\bhref\s*=\s*["\']([^"\']+?\.css)(?:[?#][^"\']*)?'
    r'["\'][^>]*?>', re.IGNORECASE)
# [D3-v10] caminho seguro de CSS do manifesto m.f: assets/X.css
RE_SAFE_CSS = re.compile(r'^assets/[A-Za-z0-9_.@\-]+\.css$')

RE_WEBCORE_URL = re.compile(
    r'https://s\.yimg\.com/uc/finance/'
    r'[A-Za-z0-9_./@-]+?\.(?:js|mjs)(?![A-Za-z0-9_])',
    re.IGNORECASE)
RE_FINJS_URL = re.compile(
    r'https://s\.yimg\.com/uc/finance/(?:srchjs|sf)/'
    r'[A-Za-z0-9_./\-]+?\.(?:js|mjs)',
    re.IGNORECASE)

RE_NODE_IDS = re.compile(r'node_ids\s*:\s*\[([0-9,\s]+)\]')
RE_BUILD_HASH = re.compile(r'/entry/(?:start|app)\.([A-Za-z0-9_-]+)\.js')
RE_START_HASH = re.compile(r'/entry/start\.([A-Za-z0-9_-]+)\.js')
RE_SAFE_CHUNK = re.compile(r"^(?:chunks|nodes|entry)/[A-Za-z0-9_.@\-]+\.m?js$")


# ---- Helpers de caminho e segurança -----------------------------------


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def norm_rel(path: str) -> str:
    return path.replace(os.sep, "/")


def safe_rel(rel: str) -> Optional[str]:
    """Normaliza um caminho relativo de bundle; None se for perigoso
    (vazio, NUL, letra de drive ou qualquer segmento '..')."""
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        return None
    normalized = rel.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", normalized):
        return None
    parts: List[str] = []
    for seg in normalized.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            return None
        parts.append(seg)
    return "/".join(parts) if parts else None


def safe_join(root: str, rel: str) -> Optional[str]:
    """Junta root+rel garantindo (via realpath) que o resultado fica
    dentro de root."""
    normalized = safe_rel(rel)
    if normalized is None:
        return None
    root_abs = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_abs, *normalized.split("/")))
    try:
        if os.path.commonpath([root_abs, target]) != root_abs:
            return None
    except ValueError:
        return None
    return target


def sha256_file(path: str) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def looks_like_html(data: bytes) -> bool:
    """Detecta payload HTML (usado contra soft-404 e cache contaminado)."""
    head = data[:1024]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    head = head.lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def is_real_url(url: str) -> bool:
    return not RE_TEMPLATE.search(url)


def is_skippable_url(url: str) -> bool:
    if css_enabled():
        return False
    return urlparse(url).path.lower().endswith(SKIP_EXTENSIONS)


def get_base_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if "/entry/" in path:
        base_path = path.split("/entry/")[0] + "/"
    elif "/immutable/" in path:
        base_path = path.split("/immutable/")[0] + "/immutable/"
    else:
        base_path = os.path.dirname(path) + "/"
    return f"{parsed.scheme}://{parsed.netloc}{base_path}"


def map_url_to_relative_path(url: str) -> str:
    """URL -> caminho relativo dentro do bundle (separador sempre '/')."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lstrip("/")

    if host == "finance.yahoo.com":
        if path in ("_service-worker.js", "__rapidworker-1.2.js",
                    "__data.json", "assets/_app/version.json"):
            return path
    if host.endswith("cmp.oath.com"):
        return "cmp.oath.com/" + path
    if host == "finance.yahoo.com" and path.startswith("version/"):
        return "cmp.oath.com/" + path
    # aaq/ (propaganda) fica na raiz por escolha explícita; o resto do
    # s.yimg.com fora do webcore segue a lógica yimg/ + path (inclusive
    # cx/ e srchjs/, alinhado à especificação do mirror).
    if host == "s.yimg.com" and path.startswith("aaq/"):
        return path
    if host in ROOT_SUBDIR_HOSTS:
        return ROOT_SUBDIR_HOSTS[host] + "/" + path
    if "/uc/finance/webcore/" in parsed.path:
        return "webcore/" + parsed.path.split("/uc/finance/webcore/", 1)[1]
    # [D3-v10] CSS dos gráficos mantém a árvore versionada do cosaic.
    if host == "finance.yahoo.com" and "/_app/cosaic/" in parsed.path:
        return "cosaic/" + parsed.path.split("/_app/cosaic/", 1)[1]
    # chunks/nodes/entry ficam planos; assets/ (CSS do SvelteKit) mantém
    # o diretório para não poluir a raiz com ~119 arquivos .css.
    for seg in ("chunks", "nodes", "entry", "assets"):
        if f"/{seg}/" in parsed.path:
            return seg + "/" + posixpath.basename(path)
    if host == "s.yimg.com":
        return "yimg/" + path
    if host != "finance.yahoo.com":
        return host.replace(".", "_") + "/" + path
    return posixpath.basename(path)


_ROOT_REL_FILES = ("_service-worker.js", "__rapidworker-1.2.js", "__data.json",
                   "assets/_app/version.json")


def relative_path_to_url(rel: str, base_url: str) -> str:
    """Inverso de map_url_to_relative_path (usado para resolver imports
    relativos). srchjs/cx/sf vivem sob yimg/ (regra yimg/ + path); só o
    webcore verdadeiro tem árvore própria."""
    if rel.startswith("webcore/"):
        return WEBCORE_PREFIX + rel
    if rel.startswith("yimg/"):
        return "https://s.yimg.com/" + rel[len("yimg/"):]
    if rel.startswith("aaq/"):
        return "https://s.yimg.com/" + rel
    if rel.startswith("cmp.oath.com/"):
        return "https://consent.cmp.oath.com/" + rel[len("cmp.oath.com/"):]
    # [D3-v10] inverso da regra cosaic (árvore versionada de CSS).
    if rel.startswith("cosaic/"):
        return "https://finance.yahoo.com/assets/_app/" + rel
    for host, sub in ROOT_SUBDIR_HOSTS.items():
        if rel.startswith(sub + "/"):
            return f"https://{host}/" + rel[len(sub) + 1:]
    if rel in _ROOT_REL_FILES:
        return "https://finance.yahoo.com/" + rel
    return base_url + rel


# ---- Extração de HTML / manifesto SvelteKit ---------------------------


def extract_entry_urls(page_html: str,
                       base: str = "https://finance.yahoo.com/") -> List[str]:
    """Entries start.*/app.* do HTML. O start.* vem sempre primeiro."""
    parsed_base = urlparse(base)
    origin = (f"{parsed_base.scheme}://{parsed_base.netloc}/"
              if parsed_base.scheme and parsed_base.netloc
              else "https://finance.yahoo.com/")
    found: Set[str] = set()
    for match in RE_ENTRY_ABS.finditer(page_html):
        found.add(match.group(0))
    for match in RE_ENTRY_REL.finditer(page_html):
        found.add(urljoin(origin, match.group(1)))
    for match in RE_ENTRY_IMPORT.finditer(page_html):
        found.add(urljoin(origin, match.group(1)))
    return sorted(found, key=lambda u: (0 if "/entry/start." in u else 1, u))


def extract_build_hash(entry_urls: List[str]) -> str:
    """Hash do build = hash do start.* (fallback: primeiro entry)."""
    for url in entry_urls:
        match = RE_START_HASH.search(url)
        if match:
            return match.group(1)
    for url in entry_urls:
        match = RE_BUILD_HASH.search(url)
        if match:
            return match.group(1)
    return "unknown"


def extract_node_ids(page_html: str) -> List[List[int]]:
    """Extrai os node_ids dos scripts inline kit.start(...) do HTML (o
    literal não existe nos entries .js). Retorna uma lista por ilha, na
    ordem do HTML."""
    results: List[List[int]] = []
    for match in RE_NODE_IDS.finditer(page_html):
        try:
            ids = [int(x.strip()) for x in match.group(1).split(",")
                   if x.strip()]
            results.append(ids)
        except ValueError:
            pass
    return results


def discover_webcore_from_html(page_html: str) -> List[str]:
    """URLs de webcore/srchjs/sf citadas no HTML da página viva, já
    filtradas pelo escopo e pela denylist."""
    found: Set[str] = set()
    for rx in (RE_WEBCORE_URL, RE_FINJS_URL):
        for match in rx.finditer(page_html):
            url = match.group(0).split("?")[0].split("#")[0]
            if (is_real_url(url) and not is_skippable_url(url)
                    and not is_denied_url(url)):
                found.add(url)
    return sorted(found)


def _resolve_manifest_path(raw: str) -> Optional[str]:
    """'../chunks/x.js' (relativo a entry/) -> 'chunks/x.js'; CSS
    '../assets/x.css' -> 'assets/x.css' quando --include-css; None se
    suspeito ou CSS fora do modo CSS."""
    if not isinstance(raw, str):
        return None
    resolved = posixpath.normpath(posixpath.join("entry",
                                                 raw.replace("\\", "/")))
    if RE_SAFE_CHUNK.match(resolved):
        return resolved
    # [D3-v10] CSS do manifesto m.f (só com --include-css).
    if css_enabled() and RE_SAFE_CSS.match(resolved):
        return resolved
    return None


def extract_manifest_from_entry(entry_text: str,
                                base_url: str) -> List[Tuple[str, str]]:
    """Manifesto m.f (__vite__mapDeps) -> [(url, caminho_relativo)] (só
    JS)."""
    raws: Set[str] = set()
    match = RE_MANIFEST.search(entry_text)
    if match:
        inner = match.group(1).strip().rstrip(",").rstrip()
        if inner:
            try:
                normalized = re.sub(r"'([^']*)'", r'"\1"', inner)
                raws.update(json.loads("[" + normalized + "]"))
            except Exception:
                pass
    if not raws:
        raws.update(RE_MANIFEST_FALLBACK.findall(entry_text))
    targets: List[Tuple[str, str]] = []
    for raw in sorted(x for x in raws if isinstance(x, str)):
        clean = _resolve_manifest_path(raw)
        if clean:
            targets.append((base_url + clean, clean))
    return targets


def dedup_targets(targets_with_tier: List[Tuple[str, str, int]]
                  ) -> Dict[str, str]:
    """Dedup por caminho completo; o menor tier vence. Retorna
    {caminho: url}."""
    best: Dict[str, Tuple[str, str, int]] = {}
    for target_path, url, tier in targets_with_tier:
        key = os.path.normcase(os.path.normpath(target_path))
        if key not in best or tier < best[key][2]:
            best[key] = (target_path, url, tier)
    return {t: u for t, u, _ in best.values()}


def extract_script_urls(page_html: str, page_url: str) -> Set[str]:
    """Scripts .js/.mjs do HTML (absolutos e relativos), só do escopo."""
    urls: Set[str] = set(RE_JS_URL.findall(page_html))
    for match in RE_ATTR_JS.finditer(page_html):
        urls.add(urljoin(page_url, match.group(1)))
    return {u.split("?")[0].split("#")[0]
            for u in urls
            if is_real_url(u) and not is_skippable_url(u)
            and urlparse(u).path.lower().endswith((".js", ".mjs"))
            and not is_denied_url(u)}


def extract_css_urls(page_html: str, page_url: str) -> Set[str]:
    """[D3-v10] CSS do HTML SSR: <link ... href="...css"> (absolutos e
    relativos). Só chama com --include-css — fora disso devolve vazio
    (o filtro is_skippable_url devolve True para .css)."""
    if not css_enabled():
        return set()
    urls: Set[str] = set()
    for match in RE_LINK_CSS.finditer(page_html):
        candidate = urljoin(page_url, match.group(1))
        candidate = candidate.split("?")[0].split("#")[0]
        if (urlparse(candidate).path.lower().endswith(".css")
                and is_real_url(candidate)
                and not is_skippable_url(candidate)
                and not is_denied_url(candidate)):
            urls.add(candidate)
    return urls


def extract_import_targets(text: str, rel_path: str,
                           base_url: str) -> Dict[str, str]:
    """Imports de um .js -> {caminho_local: url}.

    Entende "./foo.js" e "../foo.js" (relativos ao arquivo atual),
    "/foo.js" e "chunks/foo.js" (raiz do bundle) e URLs absolutas do
    escopo. Caminhos que escapam da raiz são descartados.
    """
    out: Dict[str, str] = {}
    rel_matches = set(RE_IMPORT_REL.findall(text))
    if rel_path.startswith("webcore/"):
        rel_matches |= set(RE_IMPORT_SAMEDIR_WEB.findall(text))
    if rel_path.startswith(("chunks/", "nodes/", "cdn_payments_yahoo_com/",
                            "yimg/")):
        rel_matches |= set(RE_IMPORT_SAMEDIR.findall(text))
    # [D3-v10] CSS citado nos arrays m.f dos chunks/nodes/entry
    # ("../assets/Componente.<hash>.css") — só com --include-css.
    if css_enabled():
        rel_matches |= set(RE_IMPORT_CSS.findall(text))
    cur_dir = posixpath.dirname(rel_path)
    for rel in rel_matches:
        if rel.startswith("/"):
            cand = posixpath.normpath(rel.lstrip("/"))
        elif rel.startswith(("./", "../")):
            cand = posixpath.normpath(posixpath.join(cur_dir, rel))
        else:
            cand = posixpath.normpath(rel)
        resolved = safe_rel(cand)
        if resolved is None or resolved.startswith("vendor/"):
            continue
        url = relative_path_to_url(resolved, base_url)
        if is_denied_url(url):
            continue
        out[resolved] = url
    for url in RE_JS_URL.findall(text):
        url = url.split("?")[0].split("#")[0]
        if (not is_real_url(url) or is_skippable_url(url)
                or not urlparse(url).path.lower().endswith((".js", ".mjs"))
                or not host_in_allowlist(_host(url)) or is_denied_url(url)):
            continue
        rel = safe_rel(map_url_to_relative_path(url))
        if rel:
            out[rel] = url
    return out


# ---- Camada HTTP ------------------------------------------------------


@dataclass
class HttpResponse:
    status_code: int
    url: str
    headers: Dict[str, str]
    content: bytes = b""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300


class ExponentialBackoff:
    """Backoff exponencial com jitter (50%-100% do teto da tentativa)."""

    def __init__(self, base: float = 0.5, cap: float = 8.0):
        self.base = base
        self.cap = cap

    def delay(self, attempt: int) -> float:
        ceiling = min(self.cap, self.base * (2 ** max(0, attempt)))
        return random.uniform(0.5 * ceiling, ceiling)


class CircuitBreaker:
    """Abre após `threshold` falhas seguidas; depois de `recovery_s`
    deixa passar UMA sonda (half-open). Se a sonda falhar, a janela
    reinicia."""

    def __init__(self, threshold: int = 8, recovery_s: float = 30.0):
        self.threshold = threshold
        self.recovery_s = recovery_s
        self._fails: Dict[str, int] = {}
        self._opened_at: Dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, host: str) -> bool:
        with self._lock:
            opened = self._opened_at.get(host)
            if opened is None:
                return True
            now = time.time()
            if now - opened >= self.recovery_s:
                self._opened_at[host] = now
                return True
            return False

    def record_success(self, host: str) -> None:
        with self._lock:
            self._fails.pop(host, None)
            self._opened_at.pop(host, None)

    def record_failure(self, host: str) -> None:
        with self._lock:
            self._fails[host] = self._fails.get(host, 0) + 1
            if host in self._opened_at or self._fails[host] >= self.threshold:
                self._opened_at[host] = time.time()


def _cookie_dict(obj) -> Dict[str, str]:
    """Fotografa um jar de cookies (curl_cffi/requests/httpx) em
    {nome: valor}."""
    if obj is None:
        return {}
    try:
        snapshot = obj.get_dict()
        if isinstance(snapshot, dict):
            return {str(k): str(v) for k, v in snapshot.items() if v}
    except Exception:
        pass
    try:
        # httpx: Cookies não tem get_dict() e a iteração só devolve nomes;
        # o protocolo de mapeamento (dict()) é que expõe {nome: valor}.
        snapshot = dict(obj)
        if snapshot and all(isinstance(v, str) for v in snapshot.values()):
            return {str(k): str(v) for k, v in snapshot.items() if v}
    except Exception:
        pass
    out: Dict[str, str] = {}
    try:
        for cookie in obj:
            name = getattr(cookie, "name", None)
            if name is None and isinstance(cookie, tuple):
                name = cookie[0]
            value = getattr(cookie, "value", None)
            if value is None and isinstance(cookie, tuple):
                value = cookie[1]
            if name and value:
                out[str(name)] = str(value)
    except Exception:
        pass
    return out


def _set_cookie_dict(headers) -> Dict[str, str]:
    """{nome: valor} dos headers Set-Cookie (backend urllib)."""
    out: Dict[str, str] = {}
    try:
        raw_list = headers.get_all("Set-Cookie") or []
    except Exception:
        raw_list = []
    for raw in raw_list:
        name, _, value = raw.split(";", 1)[0].partition("=")
        name, value = name.strip(), value.strip()
        if name and value:
            out[name] = value
    return out


_URLLIB_NO_REDIRECT: List[Any] = [None]


def _urllib_opener(allow_redirects: bool):
    """Opener do urllib; sem redirect, o 3xx chega como HTTPError (com
    Location)."""
    import urllib.request as urllib_request
    if allow_redirects:
        return urllib_request.build_opener()
    if _URLLIB_NO_REDIRECT[0] is None:
        class _NoRedirect(urllib_request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None
        _URLLIB_NO_REDIRECT[0] = urllib_request.build_opener(_NoRedirect)
    return _URLLIB_NO_REDIRECT[0]


# ---- Transporte (cascade curl_cffi -> httpx -> requests -> urllib) ----


def target_headers(target: str) -> Tuple[str, str]:
    """UA e sec-ch-ua coerentes com um target curl_cffi (chrome155,
    chrome150...). Targets da tabela literal usam os valores capturados;
    os demais são derivados do número da versão. Chrome >= 136 usa a
    ordem moderna de brands ("Google Chrome" primeiro)."""
    if target in _UA_BY_TARGET and target in _SECCH_BY_TARGET:
        return _UA_BY_TARGET[target], _SECCH_BY_TARGET[target]
    match = re.match(r"^chrome(\d+)[a-z]?$", target or "")
    if not match:
        return _DEFAULT_UA, _DEFAULT_SECCH
    major = int(match.group(1))
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
    grease = _GREASE_NOVO if major >= 136 else _GREASE_CLASSICO
    if major >= 136:
        secch = (f'"Google Chrome";v="{major}", "Chromium";v="{major}", '
                 f'{grease}')
    else:
        secch = (f'"Chromium";v="{major}", {grease}, '
                 f'"Google Chrome";v="{major}"')
    return ua, secch


def sec_fetch_site(url: str) -> str:
    host = _host(url)
    if host == "finance.yahoo.com":
        return "same-origin"
    if host.endswith(".yahoo.com"):
        return "same-site"
    return "cross-site"


def is_no_referer_url(url: str) -> bool:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() == "s.yimg.com":
        return (parsed.path.startswith("/aaq/")
                or parsed.path.startswith("/cx/"))
    return False


class Transport:
    """HTTP com impersonation, retry/backoff, circuit breaker e cofre de
    cookies. Os headers de navegador (UA/sec-ch-ua) vivem AQUI, casados
    com o target de impersonation — não em globais de módulo.
    """

    def __init__(self, prefer_cffi: bool = True, jar: Any = None,
                 impersonate: Optional[str] = None):
        self.backend_name = "urllib"
        self.jar = jar
        self.user_agent = _DEFAULT_UA
        self.sec_ch_ua = _DEFAULT_SECCH
        self._impersonate: Optional[str] = None
        self._httpx_client = None
        self._sessions: List[Any] = []
        self._sess_lock = threading.Lock()
        self._local = threading.local()

        if prefer_cffi and _CFFI is not None:
            candidates = self._candidate_targets()
            if impersonate:
                candidates = ([impersonate]
                              + [t for t in candidates if t != impersonate])
            for target in candidates:
                try:
                    probe = _CFFI.Session(impersonate=target)
                    if hasattr(probe, "close"):
                        probe.close()
                    self._impersonate = target
                    self.backend_name = f"curl_cffi({target})"
                    self.user_agent, self.sec_ch_ua = target_headers(target)
                    break
                except Exception:
                    continue

        self.ua_mismatch = bool(
            self._impersonate
            and not re.match(r"^chrome\d+[a-z]?$", self._impersonate))

        if self._impersonate is None and _HTTPX is not None:
            try:
                self._httpx_client = _HTTPX.Client(
                    http2=True, timeout=20.0, follow_redirects=True,
                    limits=_HTTPX.Limits(max_connections=30,
                                         max_keepalive_connections=10))
                self.backend_name = "httpx(http2)"
            except Exception:
                pass

        if self._impersonate is None and self._httpx_client is None:
            if _requests is not None:
                self.backend_name = "requests"

        # Accept-Encoding coerente com o backend ATIVO (e não com a mera
        # presença do módulo curl_cffi): com impersonation, libcurl decoda
        # gzip/deflate/br/zstd nativamente; nos fallbacks (httpx/requests/
        # urllib) só anunciamos o que consegue ser decodificado — direto
        # pelo backend ou por _transparent_decode com os módulos brotli/
        # zstandard instalados. Anunciar sem poder decodificar grava bytes
        # comprimidos no disco como se fossem .js (corrupção silenciosa).
        if self._impersonate is not None:
            self.accept_encoding = "gzip, deflate, br, zstd"
        else:
            self.accept_encoding = (
                "gzip, deflate"
                + (", br" if _brotli is not None else "")
                + (", zstd" if _zstd is not None else ""))

        self.backoff = ExponentialBackoff()
        self.breaker = CircuitBreaker()

    @staticmethod
    def _candidate_targets() -> List[str]:
        prefs = ["chrome155", "chrome150", "chrome146", "chrome145",
                 "chrome142", "chrome136", "chrome133a", "chrome131",
                 "chrome124", "chrome120", "chrome"]
        if _CFFI_TARGETS:
            return [t for t in prefs if t in _CFFI_TARGETS]
        return prefs

    def _track(self, session) -> Any:
        with self._sess_lock:
            self._sessions.append(session)
        return session

    def close(self) -> None:
        """Fecha sessões por-thread e o cliente httpx (chamar ao fim do
        run)."""
        with self._sess_lock:
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass
        if self._httpx_client is not None:
            try:
                self._httpx_client.close()
            except Exception:
                pass

    def _cffi_session(self):
        session = getattr(self._local, "cffi_sess", None)
        if session is None:
            session = self._track(
                _CFFI.Session(impersonate=self._impersonate))
            self._local.cffi_sess = session
        return session

    def _cookie_header(self) -> str:
        """Cookie do cofre vivo; com --no-session devolve vazio (nada de
        cookies de arquivo escondidos)."""
        if self.jar is not None:
            return self.jar.header()
        return ""

    def build_headers(self, url: str, mode: str = "script",
                      minimal: bool = False) -> Dict[str, str]:
        """Headers de navegador coerentes com o impersonation ativo.
        `minimal=True` = mesmos headers, SEM Cookie (retry após
        401/403)."""
        headers: Dict[str, str] = {
            "User-Agent": self.user_agent,
            "sec-ch-ua": self.sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Accept-Language": ACCEPT_LANGUAGE,
            "Accept-Encoding": self.accept_encoding,
        }
        if mode == "navigate":
            headers.update({
                "Accept": ACCEPT_HTML,
                "Cache-Control": "max-age=0",
                "Priority": "u=0, i",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": sec_fetch_site(url),
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            })
        else:
            headers["Accept"] = "*/*"
            headers["Sec-Fetch-Dest"] = "empty"
            headers["Sec-Fetch-Mode"] = "cors"
            headers["Sec-Fetch-Site"] = sec_fetch_site(url)
            headers["Referer"] = ("" if is_no_referer_url(url)
                                  else "https://finance.yahoo.com/")
            if (sec_fetch_site(url) != "same-origin"
                    and not is_no_referer_url(url)):
                headers["Origin"] = "https://finance.yahoo.com"

        if not minimal:
            host = _host(url)
            if host == "yahoo.com" or host.endswith(".yahoo.com"):
                cookie = self._cookie_header()
                if cookie:
                    headers["Cookie"] = cookie
        return headers

    @staticmethod
    def _transparent_decode(content: bytes, encoding: str,
                            magic_only: bool = False) -> bytes:
        """Descomprime o corpo se ele ainda estiver comprimido.

        magic_only=True = decide só por magic bytes (backends que já
        decodificam); magic_only=False = usa também o header
        Content-Encoding (urllib).
        """
        if not content:
            return content
        encoding = (encoding or "").lower()
        try:
            if content[:2] == b"\x1f\x8b":
                return gzip.decompress(content)
            if _zstd is not None and content[:4] == b"\x28\xb5\x2f\xfd":
                return _zstd.ZstdDecompressor().decompress(content)
            if "br" in encoding and _brotli is not None:
                # Vale também no magic_only: brotli não tem magic bytes
                # confiáveis, mas a tentativa é segura — conteúdo já
                # decodificado pelo backend lança exceção e cai no retorno
                # original; conteúdo br cru (backend sem decoder) é salvo.
                try:
                    return _brotli.decompress(content)
                except Exception:
                    pass
            if magic_only or not encoding:
                return content
            if "deflate" in encoding:
                try:
                    return zlib.decompress(content)
                except zlib.error:
                    try:
                        return zlib.decompress(content, -15)
                    except zlib.error:
                        pass
        except Exception:
            pass
        return content

    def _mark(self, host: str, status: int) -> None:
        if status >= 500:
            self.breaker.record_failure(host)
        else:
            self.breaker.record_success(host)

    def _absorb(self, pairs: Optional[Dict[str, str]]) -> None:
        """Integra cookies recebidos no cofre da sessão."""
        if self.jar is not None and pairs:
            self.jar.absorb(pairs, "resposta")

    def request(self, url: str, headers: Dict[str, str],
                timeout: float = 20.0, allow_redirects: bool = True,
                method: str = "GET", data: Any = None) -> HttpResponse:
        host = (urlparse(url).hostname or "").lower()
        if not self.breaker.allow(host):
            return HttpResponse(0, url, {}, error=f"circuit-open:{host}")
        body = (urlencode(data).encode("utf-8")
                if isinstance(data, (list, tuple, dict)) else data)
        try:
            if self._impersonate and _CFFI is not None:
                session = self._cffi_session()
                raw = session.request(method.upper(), url,
                                      headers=dict(headers), timeout=timeout,
                                      allow_redirects=allow_redirects,
                                      data=body)
                self._absorb(_cookie_dict(getattr(session, "cookies", None)))
                raw_headers = {str(k).lower(): str(v)
                               for k, v in raw.headers.items()}
                content = self._transparent_decode(
                    raw.content or b"",
                    raw_headers.get("content-encoding", ""), True)
                self._mark(host, raw.status_code)
                return HttpResponse(raw.status_code,
                                    str(getattr(raw, "url", url)),
                                    raw_headers, content)

            if self._httpx_client is not None:
                raw = self._httpx_client.request(
                    method.upper(), url, headers=dict(headers),
                    timeout=timeout, data=body,
                    follow_redirects=allow_redirects)
                self._absorb(
                    _cookie_dict(getattr(self._httpx_client, "cookies", None)))
                raw_headers = {str(k).lower(): str(v)
                               for k, v in raw.headers.items()}
                content = self._transparent_decode(
                    raw.content or b"",
                    raw_headers.get("content-encoding", ""), True)
                self._mark(host, raw.status_code)
                return HttpResponse(raw.status_code, str(raw.url),
                                    raw_headers, content)

            if _requests is not None:
                session = getattr(self._local, "req_sess", None)
                if session is None:
                    session = self._track(_requests.Session())
                    self._local.req_sess = session
                raw = session.request(method.upper(), url,
                                      headers=dict(headers), timeout=timeout,
                                      allow_redirects=allow_redirects,
                                      data=body)
                self._absorb(_cookie_dict(getattr(session, "cookies", None)))
                raw_headers = {str(k).lower(): str(v)
                               for k, v in raw.headers.items()}
                content = self._transparent_decode(
                    raw.content or b"",
                    raw_headers.get("content-encoding", ""), True)
                self._mark(host, raw.status_code)
                return HttpResponse(raw.status_code, str(raw.url),
                                    raw_headers, content)

            import urllib.error as urllib_error
            import urllib.request as urllib_request
            req = urllib_request.Request(url, data=body, headers=dict(headers))
            try:
                with _urllib_opener(allow_redirects).open(
                        req, timeout=timeout) as resp:
                    raw_bytes = resp.read()
                    raw_headers = {str(k).lower(): str(v)
                                   for k, v in resp.headers.items()}
                    self._absorb(_set_cookie_dict(resp.headers))
                    content = self._transparent_decode(
                        raw_bytes, raw_headers.get("content-encoding", ""))
                    status = getattr(resp, "status", 200)
                    self._mark(host, status)
                    return HttpResponse(status, resp.geturl(), raw_headers,
                                        content)
            except urllib_error.HTTPError as http_error:
                raw_headers = {str(k).lower(): str(v)
                               for k, v in http_error.headers.items()}
                self._absorb(_set_cookie_dict(http_error.headers))
                # [F3-v10.1] err_body: o corpo do ERRO não sombreia o
                # corpo do POST (que vive em `body`).
                try:
                    err_body = self._transparent_decode(
                        http_error.read(),
                        raw_headers.get("content-encoding", ""))
                except Exception:
                    err_body = b""
                self._mark(host, http_error.code)
                return HttpResponse(http_error.code, url, raw_headers,
                                    err_body,
                                    error=f"HTTP {http_error.code}")

        except Exception as exc:
            self.breaker.record_failure(host)
            return HttpResponse(0, url, {},
                                error=f"{type(exc).__name__}: {exc}")

    def fetch(self, url: str, mode: str = "script", timeout: float = 20.0,
              attempts: int = 3) -> HttpResponse:
        """GET com retry e backoff. Se o servidor responder 401/403 com
        Cookie enviado, repete UMA vez com headers minimal (sem
        Cookie)."""
        last = HttpResponse(0, url, {}, error="?")
        minimal = False
        for attempt in range(1, attempts + 1):
            headers = self.build_headers(url, mode=mode, minimal=minimal)
            last = self.request(url, headers, timeout=timeout)
            if last.ok:
                return last
            if (last.status_code in (401, 403) and not minimal
                    and "Cookie" in headers and attempt < attempts):
                minimal = True
                continue
            if last.status_code and last.status_code not in RETRYABLE_HTTP:
                return last
            if last.error and str(last.error).startswith("circuit-open"):
                return last
            if attempt >= attempts:
                break
            delay = self.backoff.delay(attempt)
            if last.status_code == 429:
                retry_after = last.headers.get("retry-after")
                try:
                    if retry_after:
                        delay = max(0.5, min(float(retry_after), 15.0))
                except (ValueError, TypeError):
                    pass
            time.sleep(delay)
        return last


# ---- Sessão (cookie A3 + consentimento GUCE) --------------------------

FC_YAHOO = "https://fc.yahoo.com/"
FINANCE_HOME = "https://finance.yahoo.com/"
GUCE_CONSENT = "https://guce.yahoo.com/consent"
GUCE_COPY_CONSENT = "https://guce.yahoo.com/copyConsent"
CONSENT_HOST_RE = re.compile(r"guce\.yahoo\.com|consent\.yahoo\.com", re.I)
CONSENT_HOPS = 6
CONSENT_FORM_RE = re.compile(
    r"<form[^>]*\baction=[\"']([^\"']+)[\"']", re.I)
CONSENT_INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
CONSENT_NAME_RE = re.compile(r"\bname=[\"']([^\"']+)[\"']", re.I)
CONSENT_VALUE_RE = re.compile(r"\bvalue=[\"']([^\"']*)[\"']", re.I)
CONSENT_WALL_MARKS = (b"collectconsent", b"guce.yahoo.com/consent")
SESSION_SCHEMA = "yahoo-bundle-session/1"
SESSION_FILE = "yahoo_session.json"
NETSCAPE_FILE = "yahoo_cookies.txt"
COOKIE_DOMAIN = ".yahoo.com"
SESSION_SKIP = ("A1S",)

# Arquivos locais que semeiam o cofre quando a sessão está ativa.
COOKIE_SOURCES = [os.path.join(SITE_ROOT, "session_cookies.txt"),
                  os.path.join(SCRIPT_DIR, "session_cookies.txt"),
                  os.path.join(SITE_ROOT, "yahoo_auth_vault.json"),
                  os.path.join(SCRIPT_DIR, "yahoo_auth_vault.json")]
_cookies_cache: Optional[str] = None
_cookies_lock = threading.Lock()


def _pairs_to_header(pairs) -> str:
    return "; ".join(f"{name}={value}" for name, value in pairs
                     if name and value and name != "A1S")


def _parse_cookie_file(raw: str) -> str:
    """Aceita: JSON {"cookies":[{name,value}]}, cookies.txt (Netscape, 7
    colunas separadas por TAB) ou o valor do header Cookie (uma ou
    várias linhas)."""
    raw = raw.strip()
    if raw.startswith("{"):
        data = json.loads(raw)
        return _pairs_to_header((c.get("name"), c.get("value"))
                                for c in data.get("cookies", []))
    lines: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        if line and not line.startswith("#"):
            lines.append(line)
    if lines and all(len(ln.split("\t")) >= 7 for ln in lines):
        return _pairs_to_header((ln.split("\t")[5], ln.split("\t")[6])
                                for ln in lines)
    return "; ".join(lines)


def load_cookie_header() -> str:
    """Cookie header lido dos arquivos locais (semente do cofre)."""
    global _cookies_cache
    with _cookies_lock:
        if _cookies_cache is not None:
            return _cookies_cache
        header = ""
        for path in COOKIE_SOURCES:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    header = _parse_cookie_file(handle.read())
                if header:
                    break
            except Exception:
                continue
        _cookies_cache = re.sub(r"[\r\n]", "", header)
        return _cookies_cache


def _pairs_from_cookie_header(value: str) -> Dict[str, str]:
    """'A3=x; GUC=y' -> {A3: x, GUC: y}."""
    out: Dict[str, str] = {}
    for pair in (value or "").split(";"):
        name, _, val = pair.strip().partition("=")
        if name and val:
            out[name] = val
    return out


class SessionJar:
    """Cofre dos cookies de sessão (*.yahoo.com) colhidos das respostas.

    Guarda nome/valor/origem, persiste em JSON com chmod 600 e exporta
    no formato Netscape para reuso por curl/wget/yt-dlp.
    """

    def __init__(self, path: str = "",
                 seed: Optional[Dict[str, str]] = None):
        self.path = path or os.path.join(SITE_ROOT, SESSION_FILE)
        self._lock = threading.RLock()
        self.cookies: Dict[str, str] = {}
        self.origem: Dict[str, str] = {}
        if seed:
            self.absorb(seed, "semente")

    def absorb(self, pairs: Optional[Dict[str, str]],
               origin: str = "resposta") -> List[str]:
        """Integra {nome: valor}; devolve os nomes que ainda não
        existiam."""
        novos: List[str] = []
        with self._lock:
            for nome, valor in (pairs or {}).items():
                if not nome or not valor or nome in SESSION_SKIP:
                    continue
                if nome not in self.cookies:
                    novos.append(nome)
                if self.cookies.get(nome) != valor:
                    self.cookies[nome] = valor
                    self.origem[nome] = origin
        return novos

    def header(self) -> str:
        """Valor do header Cookie, na ordem de inserção."""
        with self._lock:
            return "; ".join(f"{n}={v}" for n, v in self.cookies.items())

    def has(self, name: str) -> bool:
        with self._lock:
            return bool(self.cookies.get(name))

    def names(self) -> List[str]:
        with self._lock:
            return sorted(self.cookies)

    def as_dict(self) -> Dict[str, Any]:
        """Visão sem valores — segura para o manifest.json."""
        with self._lock:
            return {"cofre": self.path,
                    "cookies": sorted(self.cookies),
                    "origem": {k: self.origem.get(k, "?")
                               for k in sorted(self.cookies)},
                    "a3_presente": bool(self.cookies.get("A3")),
                    "guc_presente": bool(self.cookies.get("GUC"))}

    def save(self) -> str:
        """Grava o cofre (atômico, chmod 600) e devolve o caminho."""
        with self._lock:
            data = {"schema": SESSION_SCHEMA,
                    "saved_at": int(time.time()),
                    "tool": TOOL_ID,
                    "cookies": [{"name": n, "value": v,
                                 "domain": COOKIE_DOMAIN, "path": "/"}
                                for n, v in sorted(self.cookies.items())],
                    "origem": dict(self.origem)}
        atomic_write(self.path, json.dumps(
            data, ensure_ascii=False, indent=1).encode("utf-8"))
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return self.path

    def load(self) -> bool:
        """Lê o cofre do disco; False quando não existe ou está
        ilegível."""
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return False
        self.absorb({c.get("name"): c.get("value")
                     for c in data.get("cookies", [])}, "cofre")
        return bool(self.cookies)

    def export_netscape(self, path: str = "") -> str:
        """Exporta o cofre no formato Netscape (é o que curl/wget
        consomem). [D5-v10] sem caminho explícito grava AO LADO do
        cofre (que mora no diretório de --output)."""
        if not path:
            base = os.path.dirname(os.path.abspath(self.path))
            path = os.path.join(base, NETSCAPE_FILE)
        destino = path
        linhas = ["# Netscape HTTP Cookie File", "# gerado por " + TOOL_ID]
        with self._lock:
            for nome, valor in sorted(self.cookies.items()):
                prefixo = "#HttpOnly_" if nome in ("A1", "A3") else ""
                # Formato Netscape: 7 campos separados por TAB
                # (o parser _parse_cookie_file e o curl exigem TAB).
                registro = "\t".join([f"{prefixo}{COOKIE_DOMAIN}", "TRUE",
                                      "/", "TRUE", "0", nome, valor])
                linhas.append(registro)
        directory = os.path.dirname(os.path.abspath(destino))
        if directory:
            os.makedirs(directory, exist_ok=True)
        # [F1-v10.1] gravação atômica, como a do cofre JSON: sem
        # meia-escrita se o processo cair no meio do export.
        atomic_write(destino, ("\n".join(linhas) + "\n").encode("utf-8"))
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
        return destino


def prepare_session(jar_path: str = "",
                    active: bool = True) -> Optional[SessionJar]:
    """Abre o cofre, semeia com os cookies locais e o devolve (None com
    --no-session)."""
    if not active:
        return None
    jar = SessionJar(jar_path or os.path.join(SITE_ROOT, SESSION_FILE))
    jar.load()
    seed = load_cookie_header()
    if seed:
        jar.absorb(_pairs_from_cookie_header(seed), "arquivo")
    return jar


def _accept_consent_form(transport: Transport, resp: HttpResponse,
                         page_url: str, timeout: float,
                         report: Dict[str, Any]) -> str:
    """POST do formulário de consentimento + copyConsent (fluxo com
    página, típico EU)."""
    text = resp.content.decode("utf-8", "ignore")
    match = CONSENT_FORM_RE.search(text)
    if not match:
        return "página de consentimento sem <form action=...>"
    action = urljoin(page_url, html.unescape(match.group(1)))
    campos: Dict[str, str] = {}
    for tag in CONSENT_INPUT_RE.findall(text):
        name_match = CONSENT_NAME_RE.search(tag)
        if not name_match:
            continue
        value_match = CONSENT_VALUE_RE.search(tag)
        campos.setdefault(html.unescape(name_match.group(1)),
                          html.unescape(value_match.group(1) if value_match
                                        else ""))
    pairs: List[Tuple[str, str]] = list(campos.items())
    pairs += [("agree", "agree")]
    pairs += [("consentUUID", campos.get("consentUUID") or "default")]
    post_headers = transport.build_headers(action, "navigate")
    post_headers["Origin"] = "https://guce.yahoo.com"
    post_headers["Referer"] = page_url
    try:
        transport.request(action, post_headers, timeout=timeout,
                          method="POST", data=pairs)
    except Exception as exc:
        return f"POST do formulário falhou: {type(exc).__name__}"
    copy_headers = transport.build_headers(GUCE_COPY_CONSENT, "navigate")
    copy_headers["Referer"] = page_url
    try:
        transport.request(GUCE_COPY_CONSENT, copy_headers, timeout=timeout)
    except Exception:
        pass
    report["form_postado"] = True
    return "formulário de consentimento aceito (collectConsent + copyConsent)"


def is_consent_wall(content: bytes, final_url: str = "") -> bool:
    """True quando a resposta é o muro de consentimento, não a página
    real."""
    if CONSENT_HOST_RE.search(final_url or ""):
        return True
    head = (content or b"")[:8192].lower()
    return any(mark in head for mark in CONSENT_WALL_MARKS)


def warm_session(transport: Transport, jar: Optional[SessionJar],
                 timeout: float = 20.0) -> Dict[str, Any]:
    """Colhe o A3 em fc.yahoo.com e fecha o consentimento em
    guce.yahoo.com.

    Retorna um relatório decidível (nunca levanta exceção): status do
    fc, presença de A3/GUC, caminho do consentimento e detalhe textual.
    """
    report: Dict[str, Any] = {"ativada": jar is not None,
                              "fc_status": None, "a3": False, "guc": False,
                              "consent": "não testado", "saltos": 0,
                              "final": "", "form_postado": False,
                              "detalhe": ""}
    if jar is None:
        return report
    if not jar.has("A3"):
        try:
            resp = transport.request(
                FC_YAHOO, transport.build_headers(FC_YAHOO, "navigate"),
                timeout=timeout, allow_redirects=False)
            report["fc_status"] = resp.status_code
        except Exception as exc:
            report["detalhe"] = f"fc.yahoo.com: {type(exc).__name__}: {exc}"
    report["a3"] = jar.has("A3")
    if jar.has("GUC"):
        report["guc"] = True
        report["consent"] = "já consentido (GUC veio do cofre)"
        return report

    url = f"{GUCE_CONSENT}?src=finance&finalDestination={FINANCE_HOME}"
    resp: Optional[HttpResponse] = None
    try:
        while report["saltos"] < CONSENT_HOPS:
            resp = transport.request(
                url, transport.build_headers(url, "navigate"),
                timeout=timeout, allow_redirects=False)
            destino = resp.headers.get("location")
            if resp.status_code in (301, 302, 303, 307, 308) and destino:
                url = urljoin(url, destino)
                report["saltos"] += 1
                continue
            break
    except Exception as exc:
        report["detalhe"] = f"guce: {type(exc).__name__}: {exc}"
        return report
    report["final"] = url
    if not CONSENT_HOST_RE.search(url):
        report["consent"] = ("sessão já consentida (saiu do guce em "
                             f"{report['saltos']} salto(s))")
    elif resp is not None and resp.status_code == 200:
        report["consent"] = _accept_consent_form(transport, resp, url,
                                                 timeout, report)
    else:
        report["consent"] = ("resposta inesperada do guce (HTTP "
                             f"{getattr(resp, 'status_code', '?')})")
    report["a3"] = jar.has("A3")
    report["guc"] = jar.has("GUC")
    return report


# ---- Núcleo de download ------------------------------------------------


@dataclass
class DownloadRecord:
    url: str
    path: str
    cls: str = "?"
    msg: str = ""
    status: Optional[int] = None
    size: int = 0
    sha256: Optional[str] = None

    def as_dict(self, base_dir: str) -> Dict[str, Any]:
        try:
            rel = norm_rel(os.path.relpath(self.path, base_dir))
        except ValueError:
            rel = norm_rel(self.path)
        return {"path": rel, "url": self.url, "cls": self.cls,
                "msg": self.msg, "status": self.status,
                "size": self.size, "sha256": self.sha256}


def cache_is_valid(target_path: str) -> bool:
    """Cache local aproveitável = arquivo não-vazio que não parece HTML
    (soft-404 gravado por engano)."""
    if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
        return False
    try:
        with open(target_path, "rb") as handle:
            head = handle.read(1024)
    except OSError:
        return False
    return not looks_like_html(head)


def atomic_write(target_path: str, data: bytes) -> None:
    directory = os.path.dirname(target_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = target_path + ".part"
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, target_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def classify_http_failure(status_code: int, error: str) -> str:
    if status_code in (404, 410):
        return "NAO_EXISTE_404"
    if status_code in (401, 403):
        return "BLOQUEIO"
    if status_code == 0 and "circuit-open" in error:
        return "CIRCUIT_OPEN"
    if status_code == 400:
        return "REQ_INVALIDA_400"
    return "ERRO_REDE"


def download_file_to_disk(transport: Transport, url: str,
                          target_path: str, timeout: float = 20.0,
                          attempts: int = 3,
                          revalidate: bool = False) -> DownloadRecord:
    record = DownloadRecord(url=url, path=target_path)
    # [D3-v10] .css só é pulado quando --include-css está desligado.
    if skip_ext(target_path):
        record.cls, record.msg = "PULADO_CSS", "extensão ignorada"
        return record
    directory = os.path.dirname(target_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not revalidate and cache_is_valid(target_path):
        record.cls, record.msg = "CACHE", "cache local válido"
        record.size = os.path.getsize(target_path)
        record.sha256 = sha256_file(target_path)
        return record

    resp = transport.fetch(url, mode="script", timeout=timeout,
                           attempts=attempts)
    record.status = resp.status_code or None
    if not resp.ok:
        record.cls = classify_http_failure(resp.status_code, str(resp.error))
        record.msg = str(resp.error or f"HTTP {resp.status_code}")
        return record

    ctype = (resp.headers.get("content-type") or "").lower()
    data = resp.content

    if target_path.lower().endswith(TEXT_EXTS) and looks_like_html(data):
        record.cls, record.msg = ("SOFT_404_HTML",
                                  f"200 + HTML payload ({ctype})")
        return record
    if not data:
        record.cls, record.msg = "VAZIO", "corpo vazio"
        return record

    atomic_write(target_path, data)
    record.cls = "OK"
    record.size = len(data)
    record.sha256 = hashlib.sha256(data).hexdigest()
    record.msg = f"{len(data):,}B {ctype.split(';')[0].strip() or '-'}"
    return record


class TokenBucket:
    """Rate limiter por host: `rate` tokens/s, capacidade `burst`."""

    def __init__(self, rate: float = 6.0, burst: float = 12.0):
        self.rate = rate
        self.burst = burst
        self._buckets: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def acquire(self, host: str) -> None:
        """Bloqueia até haver um token disponível para este host."""
        while True:
            with self._lock:
                tokens, last_t = self._buckets.get(
                    host, (self.burst, time.monotonic()))
                now = time.monotonic()
                tokens = min(self.burst, tokens + (now - last_t) * self.rate)
                if tokens >= 1.0:
                    self._buckets[host] = (tokens - 1.0, now)
                    return
                wait = (1.0 - tokens) / self.rate
            time.sleep(wait)


class Downloader:
    """Pool de threads com rate-limit por host e semáforo por host."""

    def __init__(self, transport: Transport, workers: int = 24,
                 per_host: int = 6, timeout: float = 20.0,
                 attempts: int = 3):
        self.transport = transport
        self.workers = workers
        self.per_host = per_host
        self.timeout = timeout
        self.attempts = attempts
        self._host_sems: Dict[str, threading.Semaphore] = {}
        self._sems_lock = threading.Lock()
        self._bucket = TokenBucket()
        self.results: List[DownloadRecord] = []
        self._res_lock = threading.Lock()

    def _sem(self, host: str) -> threading.Semaphore:
        with self._sems_lock:
            if host not in self._host_sems:
                self._host_sems[host] = threading.Semaphore(self.per_host)
            return self._host_sems[host]

    def _worker(self, url: str, path: str, **kwargs) -> DownloadRecord:
        host = _host(url)
        self._bucket.acquire(host)
        with self._sem(host):
            return download_file_to_disk(self.transport, url, path,
                                         timeout=self.timeout,
                                         attempts=self.attempts, **kwargs)

    def run(self, targets: Dict[str, str], revalidate: bool = False,
            fresh_paths: Optional[Iterable[str]] = None
            ) -> List[DownloadRecord]:
        """`fresh_paths`: destinos que devem ser rebaixados mesmo com
        cache (assets fixos sem hash, cujo conteúdo muda sem mudar de
        nome)."""
        if not targets:
            return []

        def _norm(path: str) -> str:
            return os.path.normcase(os.path.normpath(path))

        fresh = {_norm(x) for x in (fresh_paths or ())}
        batch: List[DownloadRecord] = []
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.workers) as executor:
            futures = {
                executor.submit(
                    self._worker, url, path,
                    revalidate=(revalidate or _norm(path) in fresh)):
                (url, path)
                for path, url in targets.items()}
            for future in concurrent.futures.as_completed(futures):
                try:
                    record = future.result()
                except Exception as exc:
                    url, path = futures[future]
                    record = DownloadRecord(url=url, path=path,
                                            cls="ERRO_REDE",
                                            msg=f"{type(exc).__name__}: {exc}")
                batch.append(record)
        with self._res_lock:
            self.results.extend(batch)
        return batch


# ---- Crawl SSR das páginas -------------------------------------------


def kebab(seg: str) -> str:
    """Normaliza um segmento de rota para kebab-case (nome de arquivo
    seguro em qualquer SO)."""
    return re.sub(r"[^a-z0-9]+", "-", seg.lower()).strip("-")


def page_local_paths(page_url: str) -> Tuple[str, str]:
    """Rota de finance.yahoo.com -> (caminho do .html, caminho dos dados
    SSR), ambos relativos a pages/. Especificação do espelho:

      /                       -> index.html + __data.json
      /<seg>/                 -> <seg>/index.html + <seg>/__data.json
      /quote/<TICKER>/        -> quote/index.html + quote/__data.json
      /quote/<TICKER>/<sub>/  -> quote/<sub>.html + quote/<sub>.data.json
      /<a>/<b>/               -> <a>/<b>.html + <a>/<b>.data.json

    O ticker de /quote/<TICKER>/… é parâmetro da rota, não diretório do
    espelho: o bundle guarda um único exemplar do template —
    /quote/TSLA/ e /quote/META/ caem no mesmo pages/quote/index.html.
    [F4-v10.1] o crawl agrupa as rotas por arquivo local e crawlea só
    o primeiro URL que responder (os demais do grupo são pulados;
    antes havia corrida de sobreposição entre workers concorrentes).
    """
    segs = [kebab(s) for s in urlparse(page_url).path.split("/") if s]
    if len(segs) > 1 and segs[0] == "quote":
        segs = [segs[0]] + segs[2:]
    if not segs:
        return "index.html", "__data.json"
    if len(segs) == 1:
        return f"{segs[0]}/index.html", f"{segs[0]}/__data.json"
    head, last = segs[:-1], segs[-1]
    base = "/".join(head)
    return f"{base}/{last}.html", f"{base}/{last}.data.json"


def crawl_data_json(transport: Transport, url: str, pages_dir: str,
                    timeout: float, revalidate: bool) -> bool:
    """Baixa o /__data.json da rota e grava ao lado do .html da página
    (dados SSR): __data.json para rotas-container, <nome>.data.json
    para rotas-folha — ver page_local_paths(). Retorna True se o
    arquivo está no bundle."""
    data_url = url.rstrip("/") + "/__data.json"
    try:
        resp = transport.fetch(data_url, mode="script", timeout=timeout,
                               attempts=1)
    except Exception:
        return False
    if not resp.ok or not resp.content or looks_like_html(resp.content):
        return False
    destino = safe_join(pages_dir, page_local_paths(url)[1])
    if destino is None:
        return False
    if (revalidate or not os.path.exists(destino)
            or os.path.getsize(destino) == 0):
        atomic_write(destino, resp.content)
    return True


def fetch_i18n_bundles(transport: Transport, version: Optional[str],
                       output_dir: str, timeout: float,
                       revalidate: bool) -> List[str]:
    """[D4-v10] Baixa os pacotes de tradução do XHR /xhr/i18n para
    i18n/<família>.json (famílias observadas no tráfego real). O
    parâmetro v= é o timestamp do build (version.json); sem versão
    conhecida usa o epoch atual — o endpoint aceita qualquer v."""
    salvos: List[str] = []
    v_param = version or str(int(time.time() * 1000))
    for pages in I18N_FAMILIES:
        fname = "i18n/" + pages.replace(",", "-") + ".json"
        destino = safe_join(output_dir, fname)
        if destino is None:
            continue
        if (not revalidate and os.path.exists(destino)
                and os.path.getsize(destino) > 0):
            salvos.append(fname)
            continue
        url = ("https://finance.yahoo.com/xhr/i18n?"
               + urlencode({"pages": pages, "lang": I18N_LANG,
                            "v": v_param}))
        try:
            resp = transport.fetch(url, mode="script", timeout=timeout,
                                   attempts=1)
        except Exception:
            continue
        if not resp.ok or not resp.content or looks_like_html(resp.content):
            continue
        atomic_write(destino, resp.content)
        salvos.append(fname)
    return salvos


def crawl_page(transport: Transport, url: str, pages_dir: str,
               timeout: float = 25.0,
               revalidate: bool = False
               ) -> Tuple[str, Set[str], List[str], str, List[List[int]],
                          Set[str]]:
    """Crawl SSR de `url`, gravando o .html da rota em pages/ (ver
    page_local_paths) e o __data.json ao lado.

    Retorna (url, script_urls, webcore_urls, status_msg,
    node_ids_do_html, css_urls). Redirecionamento para fora de
    finance.yahoo.com e resposta que não é HTML são rejeitados.
    """
    resp = transport.fetch(url, mode="navigate", timeout=timeout, attempts=2)
    if not resp.ok:
        return (url, set(), [],
                f"[ERRO] {resp.error or 'HTTP ' + str(resp.status_code)}",
                [], set())
    if _host(resp.url) != "finance.yahoo.com":
        return url, set(), [], f"[REDIRECT] {resp.url}", [], set()
    html_bytes = resp.content
    if not html_bytes or not looks_like_html(html_bytes):
        return url, set(), [], "[INVALIDO] resposta não é HTML", [], set()
    if is_consent_wall(html_bytes, resp.url):
        return (url, set(), [],
                "[CONSENT] muro de consentimento — sem sessão válida",
                [], set())
    html_text = html_bytes.decode("utf-8", "ignore")
    destino = safe_join(pages_dir, page_local_paths(url)[0])
    if destino is None:
        return url, set(), [], "[ERRO] caminho de página inseguro", [], set()
    if (revalidate or not os.path.exists(destino)
            or os.path.getsize(destino) == 0):
        atomic_write(destino, html_bytes)
    data_ok = crawl_data_json(transport, url, pages_dir, timeout,
                              revalidate)
    return (url, extract_script_urls(html_text, url),
            discover_webcore_from_html(html_text),
            f"OK ({len(html_bytes):,} bytes"
            + (", +__data.json" if data_ok else "") + ")",
            extract_node_ids(html_text),
            extract_css_urls(html_text, url))


def crawl_page_group(transport: Transport, urls: List[str],
                     pages_dir: str, timeout: float = 25.0,
                     revalidate: bool = False
                     ) -> Tuple[str, Set[str], List[str], str,
                                List[List[int]], Set[str]]:
    """[F4-v10.1] Crawlea o primeiro URL que RESPONDER de um grupo de
    rotas que mapeiam para o MESMO arquivo local (ex.: /quote/TSLA/ e
    /quote/META/ -> pages/quote/index.html): o espelho guarda um único
    exemplar do template. Se o primeiro falha (erro/redirect/muro de
    consentimento), tenta o próximo; devolve o resultado da última
    tentativa. `urls` vem em ordem de preferência (a da lista --pages)."""
    resultado = None
    for url in urls:
        resultado = crawl_page(transport, url, pages_dir, timeout,
                               revalidate)
        if resultado[3].startswith("OK"):
            return resultado
    return resultado


# ---- Descoberta de entries e scan recursivo --------------------------


def discover_live_entries(transport: Transport,
                          pages: Optional[List[str]] = None,
                          verbose: bool = True,
                          timeout: float = 25.0) -> List[str]:
    """Auto-detecta entry points SvelteKit da build viva."""
    for page in (pages or DISCOVERY_PAGES):
        resp = transport.fetch(page, mode="navigate", timeout=timeout,
                               attempts=2)
        if not resp.ok:
            continue
        page_html = resp.content.decode("utf-8", "ignore")
        found = extract_entry_urls(page_html, page)
        if found:
            if verbose:
                print(f"   [Auto-Detect] {page} -> {found}")
            return found
    return []


def recursive_scan_rounds(output_dir: str, base_url: str,
                          known_urls: Set[str], rounds: int,
                          downloader: Downloader,
                          revalidate: bool) -> None:
    """Varre os .js/.mjs já baixados em busca de imports novos, baixa-os
    e repete até convergir (ou esgotar as rodadas)."""
    scanned: Set[str] = set()
    for round_n in range(1, rounds + 1):
        new_targets: Dict[str, str] = {}
        for dirpath, _, files in os.walk(output_dir):
            for filename in files:
                if not filename.endswith((".js", ".mjs")):
                    continue
                abs_path = os.path.join(dirpath, filename)
                rel_path = norm_rel(os.path.relpath(abs_path, output_dir))
                if rel_path in scanned:
                    continue
                scanned.add(rel_path)
                try:
                    with open(abs_path, "r", encoding="utf-8",
                              errors="ignore") as handle:
                        text = handle.read()
                except OSError:
                    continue
                for resolved, url in extract_import_targets(
                        text, rel_path, base_url).items():
                    if (url in known_urls or is_skippable_url(url)
                            or is_denied_url(url)):
                        continue
                    destino = safe_join(output_dir, resolved)
                    if destino is None:
                        continue
                    known_urls.add(url)
                    new_targets[destino] = url
        if not new_targets:
            print(f"   [Scan] Rodada {round_n}: convergiu (0 URLs novas).")
            break
        print(f"   [Scan] Rodada {round_n}: "
              f"+{len(new_targets)} URLs dinâmicas.")
        downloader.run(new_targets, revalidate=revalidate)


# ---- Integridade e manifest -------------------------------------------


def check_file_integrity(root: str) -> List[Tuple[str, str, int, str]]:
    """Arquivos .js/.mjs/.json vazios ou com payload HTML dentro."""
    issues: List[Tuple[str, str, int, str]] = []
    for dirpath, _, files in os.walk(root):
        for filename in files:
            if not filename.lower().endswith(TEXT_EXTS):
                continue
            abs_path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(abs_path)
            except OSError:
                continue
            if size == 0:
                issues.append((abs_path, "VAZIO", 0, ""))
                continue
            try:
                with open(abs_path, "rb") as handle:
                    head = handle.read(1024)
            except OSError:
                continue
            if looks_like_html(head):
                issues.append((abs_path, "HTML_EM_ARQUIVO_JS", size,
                               head.lstrip().decode("utf-8",
                                                    "ignore").lower()[:60]))
    return issues


def write_manifest(output_dir: str, payload: Dict[str, Any]) -> str:
    manifest_path = os.path.join(output_dir, MANIFEST_NAME)
    atomic_write(manifest_path,
                 json.dumps(payload, ensure_ascii=False, indent=1,
                            default=str).encode("utf-8"))
    return manifest_path


# ---- Configuração e orquestração --------------------------------------


@dataclass
class DownloadConfig:
    entries: List[str] = field(default_factory=list)
    output_dir: str = ""
    workers: int = 24
    per_host: int = 6
    rounds: int = 5
    timeout: float = 20.0
    crawl: bool = True
    crawl_pages: List[str] = field(
        default_factory=lambda: list(DISCOVERY_PAGES))
    discovery_pages: List[str] = field(
        default_factory=lambda: list(DISCOVERY_PAGES))
    revalidate: bool = False
    include_extras: bool = False
    modern_only: bool = False
    only_fixed: bool = False
    include_css: bool = False
    include_i18n: bool = False
    session: bool = True
    jar: str = ""
    impersonate: str = ""

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "DownloadConfig":
        return cls(
            entries=list(args.entries or []),
            output_dir=args.output or "",
            workers=args.workers,
            per_host=args.per_host,
            rounds=args.rounds,
            timeout=args.timeout,
            crawl=not args.no_crawl,
            # getattr: Namespaces programáticos podem não ter o campo
            # (flag nova); via CLI o parser sempre define --pages.
            crawl_pages=(list(getattr(args, "pages", None))
                         if getattr(args, "pages", None)
                         else list(DISCOVERY_PAGES)),
            revalidate=args.revalidate,
            include_extras=bool(args.include_extras),
            modern_only=bool(args.modern_only),
            only_fixed=bool(args.only_fixed),
            include_css=bool(getattr(args, "include_css", False)),
            include_i18n=bool(getattr(args, "include_i18n", False)),
            session=not args.no_session,
            jar=args.jar or "",
            impersonate=args.impersonate or "",
        )


def _fetch_version_json(transport: Transport, timeout: float
                        ) -> Optional[str]:
    """[D1-v10] Probe do build com cache-bust: ?cb=<epoch-ms> muda a
    chave de cache das bordas ATS — a URL fixa pode vir com HORAS de
    atraso (observado ao vivo: 4/4 leituras com 31-66 min de
    edge-stale), o que cega/falseia o detector de build drift. O
    parâmetro é ignorado pela origem (arquivo estático), só troca a
    chave de cache do CDN."""
    try:
        url = ("https://finance.yahoo.com/assets/_app/version.json"
               f"?cb={int(time.time() * 1000)}")
        resp = transport.fetch(url, mode="script", timeout=timeout,
                               attempts=1)
        if resp.ok and resp.content:
            return (json.loads(resp.content.decode("utf-8", "ignore"))
                    or {}).get("version")
    except Exception:
        pass
    return None


def run_download(cfg: DownloadConfig, transport: Transport,
                 retry_pass: int = 1) -> Dict[str, Any]:
    """Uma execução completa do pipeline.

    `retry_pass` = 1 na passada normal e 2 no retry por troca de build.
    Retorna o payload gravado em manifest.json.
    """
    t0 = time.time()
    set_scope(cfg.include_extras, cfg.modern_only, cfg.include_css)
    jar = transport.jar

    sessao: Dict[str, Any] = {"ativada": False,
                              "consent": "desativada (--no-session)"}
    if cfg.session and jar is not None:
        sessao = warm_session(transport, jar, timeout=cfg.timeout)
        sessao["cofre"] = jar.as_dict()
        print(f"[Sessão] A3={'sim' if sessao.get('a3') else 'não'} | "
              f"GUC={'sim' if sessao.get('guc') else 'não'} | "
              f"{sessao.get('consent')}")

    entry_urls: List[str] = []
    detection = "explicit"
    if cfg.entries:
        entry_urls = list(cfg.entries)
        print(f"[Entry] {len(entry_urls)} URLs explícitas (--entries)")
    else:
        entry_urls = discover_live_entries(transport, cfg.discovery_pages,
                                           timeout=cfg.timeout)
        detection = "auto-homepage"
    if not entry_urls:
        raise SystemExit("Auto-detecção do build atual falhou. "
                         "Verifique a rede ou passe --entries.")

    entry_urls = sorted(entry_urls,
                        key=lambda u: (0 if "/entry/start." in u else 1, u))
    for url in entry_urls:
        print(f"   -> {url}")

    primary = entry_urls[0]
    build_hash = extract_build_hash(entry_urls)
    app_hash = next(
        (m.group(1) for url in entry_urls
         for m in [re.search(r"/entry/app\.([A-Za-z0-9_-]+)\.js", url)] if m),
        None)
    # Saída plana: TODO o conteúdo baixado vai direto para
    # finance-yahoo-com/ (sem subpasta bundle_<hash>_v<ver>); o hash do
    # build fica registrado no manifest.json.
    output_dir = os.path.abspath(cfg.output_dir or SITE_ROOT)
    pages_dir = os.path.join(output_dir, "pages")
    os.makedirs(output_dir, exist_ok=True)
    for sub in BUNDLE_SUBDIRS:
        os.makedirs(os.path.join(output_dir, sub), exist_ok=True)
    for dirpath, _, filenames in os.walk(output_dir):
        for filename in filenames:
            if filename.endswith(".part"):
                try:
                    os.remove(os.path.join(dirpath, filename))
                except OSError:
                    pass
    base_url = get_base_url(primary)
    print(f"\nDestino:        {output_dir}")
    print(f"Base CDN:       {base_url}")
    print(f"Build hash:     {build_hash} (start)"
          + (f" | app: {app_hash}" if app_hash else ""))
    print(f"Detecção build: {detection}")
    print("Escopo:         núcleo"
          + (" + extras" if cfg.include_extras else "")
          + (" | só moderno" if cfg.modern_only else "")
          + (" | +CSS" if cfg.include_css else "")
          + (" | +i18n" if cfg.include_i18n else ""))
    if getattr(transport, "ua_mismatch", False):
        print("   [AVISO] target de impersonation sem UA correspondente: "
              "possível mismatch JA3 x User-Agent.")

    downloader = Downloader(transport, workers=cfg.workers,
                            per_host=cfg.per_host, timeout=cfg.timeout)

    version_at_start = _fetch_version_json(transport, cfg.timeout)
    if version_at_start:
        print(f"Versão do build (version.json): {version_at_start}")

    all_records: List[DownloadRecord] = []
    known_urls: Set[str] = set(entry_urls)
    targets_ranked: List[Tuple[str, str, int]] = []
    webcore_discovered: List[str] = []
    all_node_ids: List[List[int]] = []
    node_ids_por_pagina: Dict[str, List[List[int]]] = {}
    manifest_all: List[Tuple[str, str]] = []
    build_info: Dict[str, Any] = {
        "detection": detection,
        "entries": entry_urls,
        "build_hash": build_hash,
        "app_hash": app_hash,
        "sessao": sessao,
    }

    print("\n[1/5] Entries + extração do manifesto m.f...")
    if cfg.only_fixed:
        print("   [--only-fixed] entries e manifesto m.f pulados; a "
              "auto-detecção serviu só para registrar o build no "
              "manifest.json.")
        entry_dl_urls: List[str] = []
    else:
        entry_dl_urls = entry_urls
    for url in entry_dl_urls:
        filename = posixpath.basename(urlparse(url).path)
        destino = (safe_join(output_dir, "entry/" + filename)
                   if re.fullmatch(r"[A-Za-z0-9_.@\-]+\.m?js", filename)
                   else None)
        if destino is None:
            print(f"   [IGNORADO] nome de entry inválido: {filename!r}")
            continue
        resp = transport.fetch(url, mode="script", timeout=cfg.timeout,
                               attempts=3)
        bad = (not resp.ok) or (not resp.content) or looks_like_html(
            resp.content)
        if bad:
            why = (str(resp.error or f"HTTP {resp.status_code}")
                   if not resp.ok else "corpo vazio/HTML")
            print(f"   [FALHA] {filename}: {why}")
            all_records.append(
                DownloadRecord(url=url, path=destino, cls="ERRO_ENTRY",
                               msg=why, status=resp.status_code or None))
            if url == primary:
                raise SystemExit(f"Entry principal ({filename}) não pôde ser "
                                 f"baixado: {why}. Abortando para não gerar "
                                 "um bundle vazio.")
            continue
        atomic_write(destino, resp.content)
        all_records.append(DownloadRecord(
            url=url, path=destino, cls="OK",
            msg=f"{len(resp.content):,}B entry",
            status=resp.status_code, size=len(resp.content),
            sha256=hashlib.sha256(resp.content).hexdigest()))
        manifest_targets = extract_manifest_from_entry(
            resp.content.decode("utf-8", "ignore"), get_base_url(url))
        manifest_all.extend(manifest_targets)
        print(f"   [OK] {filename} ({len(resp.content):,}B) "
              f"-> +{len(manifest_targets)} módulos JS")
        for module_url, module_rel in manifest_targets:
            known_urls.add(module_url)
            module_dest = safe_join(output_dir, module_rel)
            if module_dest:
                targets_ranked.append((module_dest, module_url, 1))
    uniq_rels = sorted({rel for _, rel in manifest_all})
    build_info["manifest_n"] = len(uniq_rels)
    if not uniq_rels and not cfg.only_fixed:
        print("   [AVISO] nenhum módulo no manifesto m.f — o entry mudou "
              "de formato?")

    print("\n[2/5] Assets fixos (sem hash de conteúdo)...")
    fixed_list = list(FIXED_ASSET_URLS)
    fresh_paths: Set[str] = set()
    n_fixed = 0
    for url in fixed_list:
        if not is_real_url(url) or is_skippable_url(url) or is_denied_url(url):
            continue
        rel = safe_rel(map_url_to_relative_path(url))
        destino = safe_join(output_dir, rel) if rel else None
        if not destino:
            continue
        known_urls.add(url)
        targets_ranked.append((destino, url, 2))
        fresh_paths.add(destino)
        n_fixed += 1
    print(f"   {n_fixed} assets fixos enfileirados.")

    if cfg.crawl and not cfg.only_fixed:
        # [F4-v10.1] Um exemplar por arquivo local de página: rotas que
        # mapeiam para o mesmo .html (dois tickers de /quote/<TICKER>/)
        # compartilham o template. Agrupa e crawlea o primeiro URL que
        # responder de cada grupo — elimina a corrida de sobreposição
        # que existia com 8 workers concorrentes.
        grupos: Dict[str, List[str]] = {}
        for url in cfg.crawl_pages:
            grupos.setdefault(page_local_paths(url)[0], []).append(url)
        n_dup = len(cfg.crawl_pages) - len(grupos)
        print(f"\n[3/5] Crawleando {len(cfg.crawl_pages)} rotas SSR "
              f"(webcore dinâmico, revalidate={cfg.revalidate})...")
        if n_dup:
            print(f"   [Dedup páginas] {n_dup} rota(s) colapsam em arquivo"
                  " já coberto — 1 exemplar por template (o primeiro URL"
                  " que responder vence).")
        crawled_scripts: Set[str] = set()
        webcore_urls_set: Set[str] = set()
        crawled_css: Set[str] = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(crawl_page_group, transport, urls, pages_dir,
                                cfg.timeout, cfg.revalidate): urls[0]
                for urls in grupos.values()}
            for future in concurrent.futures.as_completed(futures):
                page = futures[future]
                try:
                    (url, scripts, webcore_urls, status, node_ids,
                     css_urls) = future.result()
                except Exception as exc:
                    print(f"   [ERRO] {page}: {type(exc).__name__}: {exc}")
                    continue
                new_scripts = scripts - crawled_scripts
                crawled_scripts.update(scripts)
                webcore_urls_set.update(webcore_urls)
                crawled_css.update(css_urls)
                if node_ids:
                    all_node_ids.extend(node_ids)
                    node_ids_por_pagina[url] = node_ids
                css_note = (f", +{len(css_urls)} css" if css_urls else "")
                print(f"   [{status}] {url} -> +{len(new_scripts)} scripts, "
                      f"+{len(webcore_urls)} webcore{css_note} | "
                      f"node_ids: {node_ids or '—'}")
        webcore_discovered = sorted(webcore_urls_set)
        print(f"   [Webcore dinâmico] {len(webcore_discovered)} URLs "
              "descobertas")
        # [D3-v10] CSS descoberto nos <link> das páginas crawleadas.
        if crawled_css:
            print(f"   [CSS SSR] {len(crawled_css)} URLs descobertas "
                  "(--include-css)")
        for url in (sorted(crawled_scripts) + webcore_discovered
                    + sorted(crawled_css)):
            if (url in known_urls or is_skippable_url(url)
                    or is_denied_url(url)):
                continue
            rel = safe_rel(map_url_to_relative_path(url))
            destino = safe_join(output_dir, rel) if rel else None
            if destino:
                known_urls.add(url)
                targets_ranked.append((destino, url, 2))
    else:
        motivo = "--only-fixed" if cfg.only_fixed else "--no-crawl"
        print(f"\n[3/5] Crawl SSR desativado ({motivo}): sem webcore "
              "dinâmico.")

    all_targets = dedup_targets(targets_ranked)
    denied_targets = {path for path, url in all_targets.items()
                      if is_denied_url(url)}
    for path in denied_targets:
        del all_targets[path]
    dup_removed = len(targets_ranked) - len(all_targets) - len(denied_targets)
    if dup_removed > 0:
        print(f"\n[Dedup] {dup_removed} entradas repetidas (mesmo caminho) "
              "unificadas.")
    if denied_targets:
        print(f"[Escopo/Denylist] {len(denied_targets)} alvos fora do escopo "
              "na montagem final.")

    print(f"\n[4/5] Baixando {len(all_targets)} arquivos "
          f"({cfg.workers} threads, cap {cfg.per_host}/host, "
          f"timeout {cfg.timeout:g}s)...")
    all_records.extend(downloader.run(all_targets, revalidate=cfg.revalidate,
                                      fresh_paths=fresh_paths))

    # [D4-v10] pacotes de tradução da UI (XHR /xhr/i18n) — opcional.
    i18n_salvos: List[str] = []
    if cfg.include_i18n:
        print(f"\n[i18n] Baixando {len(I18N_FAMILIES)} pacotes de "
              "tradução (/xhr/i18n)...")
        i18n_salvos = fetch_i18n_bundles(transport, version_at_start,
                                         output_dir, cfg.timeout,
                                         cfg.revalidate)
        print(f"   {len(i18n_salvos)}/{len(I18N_FAMILIES)} pacotes gravados "
              "em i18n/")

    if cfg.only_fixed:
        print("\n[5/5] Scan recursivo de imports: pulado (--only-fixed).")
    else:
        print(f"\n[5/5] Scan recursivo de imports (até {cfg.rounds} "
              "rodadas)...")
        n_before = len(downloader.results)
        recursive_scan_rounds(output_dir, base_url, known_urls, cfg.rounds,
                              downloader, cfg.revalidate)
        all_records.extend(downloader.results[n_before:])

    build_drift: Optional[str] = None
    stale_prev = 0
    prev_hash: Optional[str] = None
    manifest_path = os.path.join(output_dir, MANIFEST_NAME)
    if retry_pass == 1 and os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                prev_hash = (json.load(handle).get("build")
                             or {}).get("build_hash")
        except Exception:
            prev_hash = None
        if prev_hash and prev_hash != build_hash:
            print(f"[AVISO] A pasta já contém o build {prev_hash} "
                  f"(agora é {build_hash}).\n        Baixando por cima: "
                  "sobras do build antigo podem permanecer (use "
                  "--revalidate ou uma pasta nova).")
    # version.json não é mais baixado como asset fixo: consulta ao vivo.
    version_at_end = _fetch_version_json(transport, cfg.timeout)
    # Drift só é afirmável com as DUAS leituras válidas. _fetch_version_json
    # faz attempts=1: uma falha transitória no início devolve None, e o
    # teste antigo ("end and end != start") convertia isso em "None -> X",
    # anunciando um drift que ninguém pôde observar e disparando o retry
    # completo com --revalidate (re-download de ~mil arquivos à toa).
    if (version_at_start and version_at_end
            and version_at_end != version_at_start):
        build_drift = f"{version_at_start} -> {version_at_end}"
        print(f"\n[AVISO] O build mudou durante o run (version.json "
              f"{build_drift}). Há chunks de duas versões no bundle.")

    if retry_pass > 1 and os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                prev_files = {r.get("path")
                              for r in (json.load(handle).get("files") or [])}
            now_files = {r.as_dict(output_dir)["path"] for r in all_records
                         if r.cls in ("OK", "CACHE")}
            stale_prev = len(prev_files - now_files)
        except Exception:
            stale_prev = 0
        if stale_prev:
            print(f"   [Retry] {stale_prev} arquivo(s) do build anterior "
                  "ficaram na pasta (não existem mais no build atual).")

    build_info["paginas_offline"] = sorted(
        norm_rel(os.path.relpath(os.path.join(dirpath, filename), output_dir))
        for dirpath, _, filenames in os.walk(pages_dir)
        for filename in filenames)
    if i18n_salvos:
        build_info["i18n"] = i18n_salvos
    issues = check_file_integrity(output_dir)
    classification: Dict[str, int] = {}
    for record in all_records:
        classification[record.cls] = classification.get(record.cls, 0) + 1
    duration = time.time() - t0
    total_files = sum(len(files) for _, _, files in os.walk(output_dir))
    total_bytes = sum(os.path.getsize(os.path.join(dirpath, filename))
                      for dirpath, _, filenames in os.walk(output_dir)
                      for filename in filenames)

    payload: Dict[str, Any] = {
        "schema": "yahoo-bundle-manifest/3",
        "tool": TOOL_ID,
        "created_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "build": {**build_info,
                  "node_ids_vistas": all_node_ids,
                  "node_ids_por_pagina": node_ids_por_pagina,
                  "version_json_inicio": version_at_start,
                  "version_json_fim": version_at_end,
                  # [D1-v10] evidencia no manifest de que o probe de
                  # versão usa cache-bust (não confundir com leitura de
                  # borda possivelmente atrasada).
                  "version_probe": "cache-busted (?cb=epoch-ms)",
                  "build_drift": build_drift,
                  "passada": retry_pass,
                  "hash_anterior_na_pasta": prev_hash,
                  "arquivos_do_build_anterior": stale_prev},
        "escopo": {"extras": bool(cfg.include_extras),
                   "modern_only": bool(cfg.modern_only),
                   "include_css": bool(cfg.include_css),
                   "include_i18n": bool(cfg.include_i18n)},
        "webcore_discovered": webcore_discovered,
        "exclusoes": {"denylist": DENY_STATS.as_dict()},
        "transport": {"backend": transport.backend_name,
                      "accept_encoding": transport.accept_encoding},
        "stats": {"duracao_s": round(duration, 2),
                  "arquivos": total_files,
                  "bytes": total_bytes,
                  "classificacao": classification,
                  "integridade_issues": len(issues)},
        "integridade": [{"path": norm_rel(os.path.relpath(path, output_dir)),
                         "issue": issue, "size": size, "head": head[:40]}
                        for path, issue, size, head in issues[:50]],
        "files": [r.as_dict(output_dir) for r in all_records
                  if r.cls in ("OK", "CACHE")],
        "falhas": [r.as_dict(output_dir) for r in all_records
                   if r.cls not in ("OK", "CACHE", "PULADO_CSS")],
    }
    manifest = write_manifest(output_dir, payload)

    print("\n" + "=" * 80)
    print(f"DOWNLOAD V{TOOL_VERSION} FINALIZADO")
    print("=" * 80)
    print(f"Pasta destino:       {output_dir}")
    print(f"Build hash:          {build_hash}")
    print(f"manifest.json:       {os.path.basename(manifest)}")
    print(f"Tempo total:         {duration:.2f}s")
    print(f"Arquivos em disco:   {total_files} ({total_bytes / 1e6:.1f} MB)")
    print(f"OK: {classification.get('OK', 0)} | "
          f"Cache: {classification.get('CACHE', 0)} | "
          f"Soft-404: {classification.get('SOFT_404_HTML', 0)} | "
          f"404: {classification.get('NAO_EXISTE_404', 0)} | "
          f"Rede: {classification.get('ERRO_REDE', 0)}")
    print(f"Webcore descoberto:  {len(webcore_discovered)} URLs (dinâmico)")
    deny_txt = ", ".join(f"{k}={v}"
                         for k, v in sorted(DENY_STATS.counts.items()))
    print(f"Fora do escopo/deny: {sum(DENY_STATS.counts.values())} "
          f"({deny_txt or '-'})")
    print(f"Integridade:         {len(issues)} problemas")
    print("=" * 80)

    return payload


def cmd_download(args: argparse.Namespace) -> None:
    print("=" * 80)
    print(f"YAHOO FINANCE BUNDLE DOWNLOADER - V{TOOL_VERSION}")
    print("=" * 80)
    cfg = DownloadConfig.from_args(args)
    # [D5-v10] o cofre de sessão e o export Netscape moram no diretório
    # de SAÍDA (antes iam sempre para a pasta do script, criando pastas
    # fantasmas em runs com --output customizado).
    output_dir = os.path.abspath(cfg.output_dir or SITE_ROOT)
    jar = prepare_session(cfg.jar or os.path.join(output_dir, SESSION_FILE),
                          cfg.session)
    transport = Transport(jar=jar, impersonate=cfg.impersonate or None)
    try:
        print(f"[Transport] backend = {transport.backend_name} | "
              f"AE = {transport.accept_encoding} | "
              f"sessão = {(os.path.basename(jar.path) if jar else 'off')}")
        attempts = 2 if args.retry_on_drift else 1
        for passada in range(1, attempts + 1):
            payload = run_download(cfg, transport, retry_pass=passada)
            drift = (payload.get("build") or {}).get("build_drift")
            if not drift:
                break
            if passada < attempts:
                print(f"\n[RETRY] Build trocou durante a passada {passada} "
                      f"({drift}). Refazendo com --revalidate para obter um "
                      "snapshot coerente do build atual...")
                cfg = replace(cfg, revalidate=True)
            elif attempts == 1:
                print(f"\n[AVISO] Build trocou durante o run ({drift}) e o "
                      "retry automático está DESLIGADO (--no-retry-on-drift): "
                      "o bundle pode misturar duas versões.")
            else:
                print(f"\n[AVISO] Build trocou de novo ({drift}) e o retry "
                      "já foi usado. O bundle pode misturar duas versões: "
                      "rode novamente.")
    finally:
        transport.close()
        if jar is not None:
            try:
                print(f"[Sessão] cofre: {jar.save()} "
                      f"({len(jar.cookies)} cookies) | "
                      f"export Netscape: {jar.export_netscape()}")
            except Exception as exc:
                print(f"[Sessão] falha ao salvar o cofre: "
                      f"{type(exc).__name__}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=f"Yahoo Finance Bundle Downloader V{TOOL_VERSION} — "
                    "baixa o núcleo JS do frontend de finance.yahoo.com.")
    parser.add_argument("--workers", type=int, default=24,
                        help="threads de download (padrão: 24)")
    parser.add_argument("--per-host", type=int, default=6,
                        help="conexões simultâneas por host (padrão: 6)")
    parser.add_argument("--rounds", type=int, default=5,
                        help="rodadas máximas do scan de imports (padrão: 5)")
    parser.add_argument("--timeout", type=float, default=20.0,
                        help="timeout HTTP em segundos (padrão: 20)")
    parser.add_argument("--no-crawl", action="store_true",
                        help="pula o crawl SSR das rotas (sem webcore "
                             "dinâmico)")
    parser.add_argument("--revalidate", action="store_true",
                        help="rebaixa mesmo com cache local válido")
    parser.add_argument("--output", default=None,
                        help="pasta de saída (padrão: finance-yahoo-com/, "
                             "na pasta do script)")
    parser.add_argument("--entries", nargs="+", default=None,
                        help="URLs explícitas dos entries (start/app); "
                             "sem isso, auto-deteta na homepage")
    parser.add_argument("--pages", nargs="+", default=None,
                        metavar="URL",
                        help="rotas SSR a crawlear para pages/ (SUBSTITUI a "
                             "lista padrão); o ticker de /quote/<TICKER>/ é "
                             "parâmetro, não diretório: "
                             "--pages https://finance.yahoo.com/quote/META/ "
                             "https://finance.yahoo.com/quote/META/"
                             "earnings-calls/ grava pages/quote/index.html e "
                             "pages/quote/earnings-calls.html")
    parser.add_argument("--include-extras", action="store_true",
                        help="inclui consent/guce/cmp/aaq/safe-frame/SW/"
                             "jsdelivr")
    parser.add_argument("--include-css", action="store_true",
                        help="[v10] baixa também o CSS do núcleo "
                             "(immutable/assets/*.css via <link> do HTML "
                             "SSR + arrays m.f dos chunks; árvore cosaic/ "
                             "dos gráficos). Sem ele o espelho offline não "
                             "renderiza.")
    parser.add_argument("--include-i18n", action="store_true",
                        help="[v10] baixa os pacotes de tradução da UI "
                             "(XHR /xhr/i18n, ~251 KB por família de "
                             "rota) para i18n/")
    parser.add_argument("--modern-only", action="store_true",
                        help="pula os fallbacks .js (nomodule) do srchjs")
    parser.add_argument("--only-fixed", action="store_true",
                        help="baixa SOMENTE os FIXED_ASSET_URLS: pula "
                             "entries/manifesto, crawl SSR e scan recursivo "
                             "de imports")
    parser.add_argument("--no-retry-on-drift", dest="retry_on_drift",
                        action="store_false", default=True,
                        help="não refaz o download quando o build muda no "
                             "meio do run")
    parser.add_argument("--no-session", action="store_true",
                        help="não colhe A3/GUC nem envia cookies de sessão")
    parser.add_argument("--jar", default=None,
                        help="arquivo do cofre de sessão")
    parser.add_argument("--impersonate", default=None,
                        help="target curl_cffi (chrome155, chrome150, "
                             "chrome136...)")
    args = parser.parse_args()
    cmd_download(args)


if __name__ == "__main__":
    main()
