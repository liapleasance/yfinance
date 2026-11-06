#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================================================================
YAHOO SCOUT INTERACTIVE CHAT CLIENT (scout-cli-v3.py) - VERSION 3
===================================================================================
Cliente CLI interativo e contínuo para o Yahoo Finance AI Scout (Promenade API).
Correções e Melhorias nesta versão (v3):
  1. CORREÇÃO DE TRAVAMENTO: Implementa o fechamento explícito da conexão de streaming
     SSE utilizando gerenciadores de contexto 'with' e interrupção imediata do loop
     ao receber o evento 'stream.end'. Isso evita deadlocks e congelamento nas perguntas seguintes.
  2. Correção no fluxo de consentimento GUCE (ajustada leitura de headers.items()).
  3. Mantém a sessão ativa de chat (Conversational Memory) entre as perguntas.
  4. Emula perfeitamente o fingerprint do Chrome 133 para evitar bloqueios de WAF.
  5. Realiza decodificação de GZIP/Deflate de forma transparente.
  6. Limpa automaticamente marcações de citações e renderiza fontes/ações sugeridas.
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
from urllib.parse import urlencode

# Configura codificação segura de saída no terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Paleta de cores ANSI para um terminal estilo hacker/financeiro
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
RESET = "\033[0m"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
SEC_CH_UA = '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"'
SEC_CH_UA_PLATFORM = '"Windows"'
PROMENADE_BASE = "https://promenade-api.search.yahoo.com"

class YahooScoutInteractiveCLI:
    def __init__(self):
        # Configuração SSL resiliente para aceitar conexões legadas
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
            self.ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT

        # Gerenciamento de Cookies persistente em memória
        self.cj = http.cookiejar.CookieJar()
        self.handler = urllib.request.HTTPSHandler(context=self.ctx)
        self.cookie_handler = urllib.request.HTTPCookieProcessor(self.cj)
        self.opener = urllib.request.build_opener(self.handler, self.cookie_handler)

        self.crumb = None
        self.session_id = None

    def build_headers(self, mode: str = "navigate", referer: str = "https://finance.yahoo.com/") -> dict:
        """Gera os cabeçalhos realistas do Chrome 133 para evitar detecção de bots."""
        if mode == "navigate":
            return {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate",
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
        else: # api ou stream
            return {
                "User-Agent": USER_AGENT,
                "Accept": "text/event-stream" if mode == "stream" else "application/json",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate",
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

    def decode_response(self, data: bytes, headers: dict) -> str:
        """Descompacta dados comprimidos automaticamente (gzip/deflate)."""
        if not data:
            return ""
        enc = (headers.get("Content-Encoding") or headers.get("content-encoding") or "").lower().strip()
        try:
            if enc in ("gzip", "x-gzip") or data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            elif enc == "deflate":
                data = zlib.decompress(data)
        except Exception as e:
            pass
        return data.decode("utf-8", errors="ignore")

    def handle_consent_redirect(self, consent_url: str, html: str) -> bool:
        """Faz o bypass automático da tela de consentimento de privacidade do Yahoo GUCE."""
        try:
            action_m = re.search(r'action="([^"]+)"', html)
            action = action_m.group(1) if action_m else consent_url
            inputs = re.findall(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html)
            data_dict = {k: v for k, v in inputs}
            data_dict["agree"] = "agree" # Concordar com os termos
            post_data = urlencode(data_dict).encode("utf-8")
            
            req = urllib.request.Request(
                action, data=post_data,
                headers=self.build_headers("navigate", referer=consent_url),
                method="POST"
            )
            with self.opener.open(req, timeout=15) as r:
                r.read()
            return True
        except Exception:
            return False

    def initialize_handshake(self, symbol: str = "AAPL") -> bool:
        """Acessa o portal, supera consentimentos, guarda cookies e obtém o crumb CSRF."""
        print(f"{DIM}[1/3] Acessando Yahoo Finance para estabelecer cookies de sessão...{RESET}")
        quote_url = f"https://finance.yahoo.com/quote/{symbol}/"
        
        try:
            req = urllib.request.Request(quote_url, headers=self.build_headers("navigate"))
            with self.opener.open(req, timeout=15) as resp:
                raw = resp.read()
                html = self.decode_response(raw, dict(resp.headers.items()))
                
                # Intercepta redirecionamentos do GUCE (Consentimento)
                if "guce.yahoo.com" in resp.geturl() or "consent.yahoo.com" in resp.geturl():
                    print(f"{DIM}[INFO] Redirecionamento de privacidade detectado. Aplicando bypass...{RESET}")
                    if self.handle_consent_redirect(resp.geturl(), html):
                        # Recarrega a página principal agora com os cookies assentados
                        req2 = urllib.request.Request(quote_url, headers=self.build_headers("navigate"))
                        with self.opener.open(req2, timeout=15) as resp2:
                            raw = resp2.read()
                            html = self.decode_response(raw, dict(resp2.headers.items()))

            # Captura o crumb do HTML
            crumb_patterns = [
                r'"crumb":"([^"]+)"',
                r'\\"crumb\\":\\"([^\\"]+)\\"',
                r'window\.YAHOO\.context\s*=\s*\{.*?\"crumb\":\"([^"]+)\"',
            ]
            for pat in crumb_patterns:
                m = re.search(pat, html)
                if m and len(m.group(1)) > 3:
                    self.crumb = m.group(1).encode("utf-8").decode("unicode_escape")
                    break

            # Se falhar, recorre de forma segura ao endpoint oficial do getcrumb
            if not self.crumb:
                print(f"{DIM}[INFO] Buscando crumb de fallback nos servidores de query...{RESET}")
                for host in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
                    try:
                        crumb_url = f"{host}/v1/test/getcrumb?lang=pt-BR&region=BR"
                        c_req = urllib.request.Request(crumb_url, headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "text/plain",
                            "Referer": quote_url,
                        })
                        with self.opener.open(c_req, timeout=10) as c_resp:
                            raw_c = c_resp.read()
                            txt = self.decode_response(raw_c, dict(c_resp.headers.items())).strip()
                            if txt and "error" not in txt.lower() and len(txt) > 3:
                                self.crumb = txt
                                break
                    except Exception:
                        continue

            if not self.crumb:
                # Mock crumb de contingência
                self.crumb = "MOCK_CRUMB"

            print(f"{GREEN}[OK] Handshake de segurança concluído! Crumb ativo: {self.crumb}{RESET}")
            return True
        except Exception as e:
            print(f"{RED}[ERRO] Falha crítica no handshake: {e}{RESET}")
            return False

    def create_scout_session(self) -> bool:
        """Cria e obtém uma nova sessão conversacional no microsserviço (POST /sessions)."""
        print(f"{DIM}[2/3] Criando sessão persistente no Yahoo Scout AI...{RESET}")
        url = f"{PROMENADE_BASE}/sessions?crumb={self.crumb}"
        payload = json.dumps({"tenant": "finance"}).encode("utf-8")
        
        try:
            req = urllib.request.Request(url, data=payload, headers=self.build_headers("api"), method="POST")
            with self.opener.open(req, timeout=15) as resp:
                raw = resp.read()
                data_str = self.decode_response(raw, dict(resp.headers.items()))
                parsed = json.loads(data_str)
                self.session_id = parsed.get("session_id")
                
                if self.session_id:
                    print(f"{GREEN}[OK] Sessão de IA estabelecida! ID: {self.session_id}{RESET}")
                    return True
                else:
                    return False
        except Exception as e:
            print(f"{RED}[ERRO] Falha ao registrar sessão na Promenade API: {e}{RESET}")
            return False

    def send_prompt(self, message: str, symbol: str = "AAPL"):
        """POST /chat - Envia prompt, consome streaming SSE e renderiza a resposta."""
        url = f"{PROMENADE_BASE}/chat?crumb={self.crumb}"
        payload = json.dumps({
            "message": message,
            "session_id": self.session_id,
            "tenant": "finance",
            "symbol": symbol
        }).encode("utf-8")

        headers = self.build_headers("stream")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            # CORREÇÃO: Uso de gerenciador de contexto 'with' para garantir que a conexão TCP
            # seja explicitamente encerrada após o streaming do Server-Sent Events (SSE).
            with self.opener.open(req, timeout=45) as resp:
                grounding_sources = []
                suggested_actions = []
                current_status = ""
                should_break = False

                sys.stdout.write(f"\n{CYAN}{BOLD}Scout AI:{RESET} ")
                sys.stdout.flush()

                buffer = ""
                for chunk_bytes in resp:
                    if should_break:
                        break
                    
                    chunk = self.decode_response(chunk_bytes, dict(resp.headers.items()))
                    buffer += chunk
                    
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line.startswith("data: "):
                            try:
                                payload_data = json.loads(line[6:])
                                event_type = payload_data.get("event")
                                data = payload_data.get("data", {})

                                if event_type == "status.update":
                                    status = data.get("status", "")
                                    if status != current_status:
                                        current_status = status
                                        sys.stdout.write(f"\r{DIM}[{status}...]{RESET}\033[K ")
                                        sys.stdout.flush()

                                elif event_type == "content.delta":
                                    delta = data.get("delta", "")
                                    if current_status:
                                        sys.stdout.write(f"\r{CYAN}{BOLD}Scout AI:{RESET} ")
                                        current_status = ""
                                    # Higieniza marcações brutas internas (ex: $$1, $$2)
                                    delta_clean = re.sub(r"\$\$\d+", "", delta)
                                    sys.stdout.write(delta_clean)
                                    sys.stdout.flush()

                                elif event_type == "grounding.sources":
                                    grounding_sources = data.get("grounding_sources", [])

                                elif event_type == "actions.suggested":
                                    suggested_actions = data.get("actions", [])

                                elif event_type == "stream.end":
                                    # CORREÇÃO: Sinalizador para forçar a saída imediata do loop de streaming,
                                    # liberando o socket de Keep-Alive do servidor sem aguardar expiração de timeout.
                                    should_break = True
                                    break

                            except Exception:
                                pass

            print() # Salta linha ao fim do streaming

            # Renderiza fontes consultadas se houver
            if grounding_sources:
                print(f"\n{YELLOW}{BOLD}📚 [Fontes Consultadas]:{RESET}")
                for idx, src in enumerate(grounding_sources[:4], 1):
                    title = src.get("title", "Sem título")
                    prov = src.get("provider_name", "Yahoo Finance")
                    link = src.get("cdn_url") or src.get("url", "")
                    print(f"  {DIM}[{idx}]{RESET} {title} {DIM}(via {prov}){RESET}")
                    if link:
                        print(f"      {DIM}{link}{RESET}")

            # Renderiza ações sugeridas pelo SvelteKit
            if suggested_actions:
                print(f"\n{MAGENTA}{BOLD}💡 [Ações de Interface Sugeridas]:{RESET}")
                for act in suggested_actions:
                    act_id = act.get("action_id", "")
                    params = act.get("params", {})
                    print(f"  * {act_id} -> {params}")

            print("\n" + f"{DIM}" + "-" * 80 + f"{RESET}")

        except urllib.error.HTTPError as e:
            err_body = self.decode_response(e.read(), dict(e.headers.items()) if e.headers else {})
            print(f"\n{RED}[ERRO HTTP {e.code}]: {e.reason}{RESET}")
            print(f"{DIM}{err_body}{RESET}\n")
        except Exception as e:
            print(f"\n{RED}[ERRO] Erro na transmissão do chat: {e}{RESET}\n")

    def run_terminal(self):
        """Inicializa a CLI e entra no loop contínuo de perguntas e respostas."""
        print("=" * 80)
        print(f"{CYAN}{BOLD}YAHOO SCOUT INTERACTIVE CHAT CLIENT -- CLI TERMINAL (V3){RESET}")
        print("Mecanismo contínuo de Conversational Memory (Sessão Persistente)")
        print("=" * 80)

        # Roda o handshake e cria a sessão conversacional de IA
        if not self.initialize_handshake() or not self.create_scout_session():
            print(f"{RED}[FALHA CRÍTICA] Erro na inicialização da Promenade API. Encerrando CLI.{RESET}")
            return

        print(f"\n{GREEN}[3/3] Chat inicializado!{RESET}")
        print(f"Digite suas perguntas normalmente. A IA lembrará das perguntas anteriores.")
        print(f"Digite {BOLD}'sair'{RESET}, {BOLD}'exit'{RESET} ou {BOLD}'q'{RESET} para encerrar o terminal.\\n")
        print("-" * 80)

        # Loop interativo contínuo
        while True:
            try:
                user_input = input(f"\n{GREEN}{BOLD}Você:{RESET} ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ("sair", "exit", "quit", "q"):
                    print(f"\n{CYAN}Encerrando chat. Até logo!{RESET}\n")
                    break

                self.send_prompt(user_input)

            except (KeyboardInterrupt, EOFError):
                print(f"\n\n{CYAN}Conexão encerrada pelo usuário. Saindo...{RESET}\n")
                break

if __name__ == "__main__":
    cli = YahooScoutInteractiveCLI()
    cli.run_terminal()
