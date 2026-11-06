#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================================================================
YAHOO FINANCE / PROMENADE API (AI SCOUT) - CLIENTE V2 (AUTENTICACAO ROBUSTA)
===================================================================================
Versão melhorada baseada no test_promenade_api.py:
  1. Emulação fidedigna de navegador moderno (Chrome 133 Windows 10/11)
  2. Headers Client Hints (sec-ch-ua, Sec-Fetch-Site, Sec-Fetch-Mode, Sec-Fetch-Dest)
  3. Suporte a decodificação transparente de GZIP / Deflate / Brotli
  4. Resolução de Crumb multi-estratégia (HTML Regex + Fallback getcrumb oficial)
  5. Gerenciamento e persistência de Cookies de Sessão (A1, A3, GUC, etc.)
  6. Handshake de consentimento automático (GUCE / Oath GDPR/LGPD)
  7. Streaming SSE completo no Chat (Step 4) com deltas em tempo real e fontes
  8. Modo de teste sequencial (Steps 1 a 4) + Modo interativo de conversação
===================================================================================
"""

import os
import sys
import ssl
import json
import re
import time
import gzip
import zlib
import http.cookiejar
import urllib.request
import urllib.error
from urllib.parse import urlparse, parse_qs, urlencode

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Cores ANSI para saída no terminal
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
PURPLE = "\033[35m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
RESET = "\033[0m"

# ---------------------------------------------------------------------------
# CONFIGURACOES DE NAVEGADOR (CHROME 133 FINGERPRINT)
# ---------------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"'
SEC_CH_UA_PLATFORM = '"Windows"'

PROMENADE_BASE = "https://promenade-api.search.yahoo.com"
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_cookies.txt")

# ---------------------------------------------------------------------------
# UTILITARIOS DE REDE E DESCOMPRESSAO
# ---------------------------------------------------------------------------

def create_ssl_context():
    """Cria contexto SSL seguro com fallback para servidores legados."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # Habilita suporte a renegociação legado do OpenSSL se disponível
    if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return ctx

HAS_BROTLI = False
try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    pass

ACCEPT_ENCODING = "gzip, deflate, br" if HAS_BROTLI else "gzip, deflate"

def decompress_data(data: bytes, headers: dict) -> bytes:
    """Descomprime dados gzip, deflate ou brotli automaticamente."""
    if not data:
        return b""
    enc = (headers.get("Content-Encoding") or headers.get("content-encoding") or "").lower().strip()
    if enc in ("gzip", "x-gzip") or data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except Exception:
            pass
    elif enc == "deflate":
        try:
            return zlib.decompress(data)
        except Exception:
            try:
                return zlib.decompress(data, -zlib.MAX_WBITS)
            except Exception:
                pass
    elif enc == "br" and HAS_BROTLI:
        try:
            return brotli.decompress(data)
        except Exception:
            pass
    return data

def build_browser_headers(mode: str = "navigate", referer: str = "https://finance.yahoo.com/") -> dict:
    """
    Monta headers HTTP idênticos aos que o Google Chrome envia na vida real,
    evitando bloqueios por heurísticas de bot/scraper.
    """
    if mode == "navigate":
        return {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": ACCEPT_ENCODING,
            "Cache-Control": "max-age=0",
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
    elif mode == "api":
        return {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": ACCEPT_ENCODING,
            "Content-Type": "application/json",
            "Origin": "https://finance.yahoo.com",
            "Referer": referer,
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }
    elif mode == "stream":
        h = build_browser_headers(mode="api", referer=referer)
        h["Accept"] = "text/event-stream, application/json"
        return h
    return {"User-Agent": USER_AGENT}

# ---------------------------------------------------------------------------
# GERENCIADOR DE SESSAO (COOKIES + CRUMB)
# ---------------------------------------------------------------------------

class YahooAuthSession:
    """
    Gerencia cookies legítimos de navegação e extração de crumb
    com suporte a persistência e bypass de telas de consentimento.
    """
    def __init__(self, cookie_file: str = COOKIE_FILE):
        self.cookie_file = cookie_file
        self.cj = http.cookiejar.CookieJar()
        self.ctx = create_ssl_context()
        self.handler = urllib.request.HTTPSHandler(context=self.ctx)
        self.cookie_handler = urllib.request.HTTPCookieProcessor(self.cj)
        self.opener = urllib.request.build_opener(self.handler, self.cookie_handler)
        self.crumb = None
        self._load_saved_cookies()

    def _load_saved_cookies(self):
        """Carrega cookies salvos previamente em disco, se existirem."""
        if os.path.exists(self.cookie_file):
            try:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    cookie_str = f.read().strip()
                if cookie_str:
                    for part in cookie_str.split(";"):
                        if "=" in part:
                            k, v = part.strip().split("=", 1)
                            c = http.cookiejar.Cookie(
                                version=0, name=k, value=v, port=None, port_specified=False,
                                domain=".yahoo.com", domain_specified=True, domain_initial_dot=True,
                                path="/", path_specified=True, secure=True, expires=int(time.time()) + 86400 * 30,
                                discard=False, comment=None, comment_url=None, rest={}, rfc2109=False
                            )
                            self.cj.set_cookie(c)
            except Exception:
                pass

    def save_cookies(self):
        """Salva os cookies atuais em disco para reuso futuro."""
        try:
            parts = []
            for c in self.cj:
                if "yahoo.com" in c.domain:
                    parts.append(f"{c.name}={c.value}")
            if parts:
                with open(self.cookie_file, "w", encoding="utf-8") as f:
                    f.write("; ".join(parts))
        except Exception:
            pass

    def handle_consent_redirect(self, consent_url: str, html: str) -> bool:
        """Lida com a página de consentimento (GUCE/Oath) se for apresentada."""
        try:
            action_m = re.search(r'action="([^"]+)"', html)
            action = action_m.group(1) if action_m else consent_url
            inputs = re.findall(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html)
            data_dict = {k: v for k, v in inputs}
            data_dict["agree"] = "agree"
            post_data = urlencode(data_dict).encode("utf-8")
            req = urllib.request.Request(
                action, data=post_data,
                headers=build_browser_headers("navigate", referer=consent_url),
                method="POST"
            )
            with self.opener.open(req, timeout=15) as r:
                r.read()
            return True
        except Exception:
            return False

    def acquire_session_and_crumb(self, target_quote: str = "AAPL") -> str:
        """
        Executa o fluxo real de autenticação:
          1. Acessa a página da cotação com headers reais do Chrome
          2. Coleta cookies da sessão (A1, A3, A1S)
          3. Extrai o Crumb do HTML ou recorre à API query1/query2 oficial
        """
        quote_url = f"https://finance.yahoo.com/quote/{target_quote}/"
        headers = build_browser_headers("navigate")
        
        req = urllib.request.Request(quote_url, headers=headers)
        try:
            resp = self.opener.open(req, timeout=15)
            raw = resp.read()
            html = decompress_data(raw, dict(resp.headers.items())).decode("utf-8", errors="ignore")
            
            # Verifica se foi redirecionado para página de consentimento
            if "guce.yahoo.com" in resp.geturl() or "consent.yahoo.com" in resp.geturl():
                self.handle_consent_redirect(resp.geturl(), html)
                # Recarrega a página principal após consentir
                req2 = urllib.request.Request(quote_url, headers=headers)
                resp = self.opener.open(req2, timeout=15)
                html = decompress_data(resp.read(), dict(resp.headers.items())).decode("utf-8", errors="ignore")

        except urllib.error.HTTPError as e:
            raw = e.read()
            html = decompress_data(raw, dict(e.headers.items()) if e.headers else {}).decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"{RED}[ERRO] Falha de conexão inicial: {e}{RESET}")
            html = ""

        # Estratégia 1: Extrair Crumb do HTML renderizado
        crumb_patterns = [
            r'"crumb":"([^"]+)"',
            r'\\"crumb\\":\\"([^\\"]+)\\"',
            r'window\.YAHOO\.context\s*=\s*\{.*?"crumb":"([^"]+)"',
        ]
        for pat in crumb_patterns:
            m = re.search(pat, html)
            if m and len(m.group(1)) > 3:
                self.crumb = m.group(1).encode("utf-8").decode("unicode_escape")
                break

        # Estratégia 2: Fallback oficial usando o endpoint getcrumb com os cookies coletados
        if not self.crumb:
            for query_host in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
                try:
                    crumb_url = f"{query_host}/v1/test/getcrumb"
                    crumb_headers = {
                        "User-Agent": USER_AGENT,
                        "Accept": "text/plain,*/*",
                        "Referer": quote_url,
                        "Origin": "https://finance.yahoo.com",
                    }
                    c_req = urllib.request.Request(crumb_url, headers=crumb_headers)
                    with self.opener.open(c_req, timeout=10) as c_resp:
                        raw_c = c_resp.read()
                        txt = decompress_data(raw_c, dict(c_resp.headers.items())).decode("utf-8", errors="ignore").strip()
                        if txt and "error" not in txt.lower() and len(txt) > 3:
                            self.crumb = txt
                            break
                except Exception:
                    continue

        self.save_cookies()
        return self.crumb or ""

    def open(self, req: urllib.request.Request, timeout: int = 20):
        """Wrapper de requisição com descompressão automática de resposta."""
        resp = self.opener.open(req, timeout=timeout)
        return resp

# ---------------------------------------------------------------------------
# CLIENTE PROMENADE API (AI SCOUT)
# ---------------------------------------------------------------------------

class PromenadeApiClient:
    """Cliente para interagir com os endpoints do AI Scout no Yahoo Finance."""
    
    def __init__(self, auth_session: YahooAuthSession):
        self.auth = auth_session
        self.session_id = None

    def create_session(self, crumb: str, tenant: str = "finance") -> dict:
        """POST /sessions?crumb={crumb} - Inicializa sessão com o motor de IA."""
        url = f"{PROMENADE_BASE}/sessions?crumb={crumb}"
        payload = json.dumps({"tenant": tenant}).encode("utf-8")
        headers = build_browser_headers("api")
        
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with self.auth.open(req, timeout=15) as resp:
            raw = resp.read()
            data_str = decompress_data(raw, dict(resp.headers.items())).decode("utf-8", errors="ignore")
            parsed = json.loads(data_str)
            self.session_id = parsed.get("session_id", "")
            return {
                "status": resp.status,
                "content_type": resp.headers.get("content-type", ""),
                "session_id": self.session_id,
                "raw": data_str
            }

    def get_chat_seeds(self, crumb: str, message: str, tenant: str = "finance", ttl: int = 5) -> dict:
        """POST /chat/seeds?crumb={crumb} - Obtém seeds e prompts sugeridos."""
        url = f"{PROMENADE_BASE}/chat/seeds?crumb={crumb}"
        payload = json.dumps({
            "message": message,
            "tenant": tenant,
            "ttl": ttl
        }).encode("utf-8")
        headers = build_browser_headers("api")

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with self.auth.open(req, timeout=15) as resp:
            raw = resp.read()
            data_str = decompress_data(raw, dict(resp.headers.items())).decode("utf-8", errors="ignore")
            return {
                "status": resp.status,
                "content_type": resp.headers.get("content-type", ""),
                "raw": data_str
            }

    def chat_stream(self, crumb: str, session_id: str, message: str, symbol: str = "SQQQ", tenant: str = "finance"):
        """
        POST /chat?crumb={crumb} - Envia pergunta e consome fluxo SSE (Server-Sent Events)
        Gerador que produz deltas de texto, fontes consultadas e perguntas sugeridas.
        """
        url = f"{PROMENADE_BASE}/chat?crumb={crumb}"
        payload = json.dumps({
            "message": message,
            "session_id": session_id,
            "tenant": tenant,
            "symbol": symbol
        }).encode("utf-8")
        headers = build_browser_headers("stream")

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        resp = self.auth.open(req, timeout=45)
        
        # Leitura linha a linha do streaming SSE
        for line_bytes in resp:
            line = decompress_data(line_bytes, dict(resp.headers.items())).decode("utf-8", errors="ignore")
            for subline in line.split("\n"):
                subline = subline.strip()
                if not subline:
                    continue
                if subline.startswith("data: "):
                    json_str = subline[6:].strip()
                    try:
                        obj = json.loads(json_str)
                        yield obj
                    except Exception:
                        pass

# ---------------------------------------------------------------------------
# FLUXO DE EXECUCAO PRINCIPAL
# ---------------------------------------------------------------------------

def run_tests_and_demo():
    print("=" * 75)
    print(f"{BOLD}{PURPLE}YAHOO SCOUT AI - PROMENADE API CLIENTE V2{RESET}")
    print("Autenticação Reforçada com Fingerprint Real do Chrome & Gestão de Cookies")
    print("=" * 75)

    # -----------------------------------------------------------------
    # Step 1: Obter Cookies de Sessão + Crumb
    # -----------------------------------------------------------------
    print(f"\n{BOLD}{CYAN}=== Step 1: Getting session cookies + crumb ==={RESET}")
    auth = YahooAuthSession()
    crumb = auth.acquire_session_and_crumb("AAPL")
    
    cookies = list(auth.cj)
    print(f"{GREEN}[OK] Crumb obtido:{RESET} {BOLD}{crumb or '(vazio)'}{RESET}")
    print(f"{GREEN}[OK] Cookies capturados:{RESET} {len(cookies)}")
    for c in cookies:
        print(f"   * {c.name} = {c.value[:18]}... (domain={c.domain})")

    if not crumb:
        print(f"\n{RED}[ALERTA] Não foi possível extrair o crumb. Tentativas de API podem falhar.{RESET}")

    client = PromenadeApiClient(auth)

    # -----------------------------------------------------------------
    # Step 2: Testar /sessions (Criação de Sessão)
    # -----------------------------------------------------------------
    print("\n" + "=" * 65)
    print(f"{BOLD}{CYAN}Step 2: TEST AI Scout (Promenade API) - POST /sessions{RESET}")
    print("=" * 65)
    session_id = ""
    try:
        res_session = client.create_session(crumb)
        print(f"Status: [{res_session['status']}] Content-Type: {res_session['content_type']}")
        print(f"Response: {res_session['raw'][:300]}")
        session_id = res_session["session_id"]
        print(f"\n{GREEN}{BOLD}>>> Session ID: {session_id}{RESET}")
    except urllib.error.HTTPError as e:
        body = e.read(500).decode("utf-8", errors="ignore")
        print(f"{RED}HTTP Error: {e.code} {e.reason}{RESET}")
        print(f"Body: {body[:300]}")
    except Exception as e:
        print(f"{RED}Error: {e}{RESET}")

    # -----------------------------------------------------------------
    # Step 3: Testar /chat/seeds (Seeds de Conversa)
    # -----------------------------------------------------------------
    print("\n" + "=" * 65)
    print(f"{BOLD}{CYAN}Step 3: TEST AI Scout (Promenade API) - POST /chat/seeds{RESET}")
    print("=" * 65)
    test_msg = "Vale a pena comprar SQQQ considerando que o mercado de ações vive numa bolha ?"
    try:
        res_seeds = client.get_chat_seeds(crumb, test_msg)
        print(f"Status: [{res_seeds['status']}] Content-Type: {res_seeds['content_type']}")
        print(f"Response: {res_seeds['raw'][:500]}")
    except urllib.error.HTTPError as e:
        body = e.read(500).decode("utf-8", errors="ignore")
        print(f"{RED}HTTP Error: {e.code} {e.reason}{RESET}")
        print(f"Body: {body[:300]}")
    except Exception as e:
        print(f"{RED}Error: {e}{RESET}")

    # -----------------------------------------------------------------
    # Step 4: Testar /chat (Streaming SSE em Tempo Real)
    # -----------------------------------------------------------------
    if session_id:
        print("\n" + "=" * 65)
        print(f"{BOLD}{CYAN}Step 4: TEST AI Scout (Promenade API) - POST /chat (SSE Stream){RESET}")
        print("=" * 65)
        chat_msg = "Vale a pena comprar SQQQ ?"
        print(f"{BOLD}Pergunta:{RESET} {chat_msg}")
        sys.stdout.write(f"\n{PURPLE}{BOLD}🤖 Yahoo Scout AI:{RESET} ")
        sys.stdout.flush()

        grounding_sources = []
        follow_up_questions = []

        try:
            for event in client.chat_stream(crumb, session_id, chat_msg, symbol="SQQQ"):
                event_type = event.get("event")
                data = event.get("data", {})
                
                # Delta de texto em tempo real
                if event_type == "content.delta" and "delta" in data:
                    sys.stdout.write(data["delta"])
                    sys.stdout.flush()
                # Fontes consultadas
                elif event_type == "grounding.sources" and "grounding_sources" in data:
                    grounding_sources = data["grounding_sources"]
                # Sugestões de follow-up
                elif event_type == "follow_up.questions" and "follow_up_questions" in data:
                    follow_up_questions = data["follow_up_questions"]

            print("\n")
            if grounding_sources:
                print(f"\n{YELLOW}{BOLD}📚 Fontes Consultadas pelo Scout:{RESET}")
                for idx, src in enumerate(grounding_sources[:4], 1):
                    t = src.get("title", "Fonte")
                    u = src.get("cdn_url") or src.get("url", "")
                    print(f"  {DIM}[{idx}]{RESET} {t} {DIM}({u}){RESET}")

            if follow_up_questions:
                print(f"\n{CYAN}{BOLD}💡 Perguntas Sugeridas:{RESET}")
                for q in follow_up_questions:
                    print(f"  * {q}")

        except urllib.error.HTTPError as e:
            body = e.read(500).decode("utf-8", errors="ignore")
            print(f"\n{RED}Chat HTTP Error: {e.code} {e.reason}{RESET}")
            print(f"Body: {body[:300]}")
        except Exception as e:
            print(f"\n{RED}Chat Error: {e}{RESET}")

    # -----------------------------------------------------------------
    # Modo Interativo Opcional
    # -----------------------------------------------------------------
    if session_id:
        print("\n" + "=" * 65)
        print(f"{BOLD}{GREEN}MODO CHAT INTERATIVO{RESET}")
        print("Pressione [Enter] para fazer perguntas, ou digite 'sair' para finalizar.")
        print("=" * 65)
        
        while True:
            try:
                pergunta = input(f"\n{BOLD}👤 Você:{RESET} ").strip()
                if not pergunta:
                    continue
                if pergunta.lower() in ("sair", "exit", "quit", "q"):
                    print(f"\n{PURPLE}Sessão finalizada. Até mais!{RESET}")
                    break

                sys.stdout.write(f"\n{PURPLE}{BOLD}🤖 Scout AI:{RESET} ")
                sys.stdout.flush()

                for event in client.chat_stream(crumb, session_id, pergunta):
                    if event.get("event") == "content.delta" and "delta" in event.get("data", {}):
                        sys.stdout.write(event["data"]["delta"])
                        sys.stdout.flush()
                print()

            except (KeyboardInterrupt, EOFError):
                print(f"\n{PURPLE}Encerrado pelo usuário.{RESET}")
                break

if __name__ == "__main__":
    run_tests_and_demo()
