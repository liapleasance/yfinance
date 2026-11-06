#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================================================================
POLYMARKET BLOOMBERG TERMINAL v4.0 (ADVANCED SEARCH & LIVE CLOB ENGINE)
===================================================================================
- Mecanismo de busca avançado por palavras-chave com catálogo visual.
- Tela de resultados dedicada com exibição de probabilidades (% YES / % NO) e volume.
- Conexão direta ao WebSocket CLOB oficial da Polymarket para o mercado selecionado.
- Buffer alternativo de tela cheia (\033[?1049h) anti-flicker e anti-spam.
===================================================================================
Dependências: pip install websockets
Uso: python polymarket_terminal_v4.py
===================================================================================
"""

import asyncio
import atexit
import json
import os
import shutil
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
import websockets

if os.name == "nt":
    os.system("")  # Ativa suporte ANSI/VT100 no Windows

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Paleta de Cores Bloomberg Terminal
# ---------------------------------------------------------------------------
AMBER = "\033[38;5;214m"        # Âmbar (#FFAA00)
BRIGHT_AMBER = "\033[38;5;220m" # Dourado de Destaque
DARK_AMBER = "\033[38;5;172m"   # Âmbar Escuro (Bordas)
GREEN = "\033[38;5;46m"          # Verde Neon (YES / Bids)
RED = "\033[38;5;196m"           # Vermelho Carmesim (NO / Asks)
CYAN = "\033[38;5;51m"          # Ciano Neon
GRAY = "\033[38;5;242m"
WHITE = "\033[38;5;231m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# Endpoints Oficiais da Polymarket
POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"


# ---------------------------------------------------------------------------
# Buffer Alternativo Full-Screen (Anti-Spam / Anti-Scroll)
# ---------------------------------------------------------------------------
def enter_alt_screen():
    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
    sys.stdout.flush()

def exit_alt_screen():
    sys.stdout.write("\033[?25h\033[?1049l")
    sys.stdout.flush()

atexit.register(exit_alt_screen)


def format_volume(vol: float) -> str:
    if vol >= 1_000_000_000:
        return f"${vol / 1_000_000_000:.1f}B"
    if vol >= 1_000_000:
        return f"${vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"${vol / 1_000:.0f}K"
    return f"${vol:.0f}" if vol > 0 else "$0"


# ---------------------------------------------------------------------------
# Motor de Consulta & Catálogo da Polymarket (Gamma API)
# ---------------------------------------------------------------------------
def fetch_active_catalog(limit: int = 100):
    """Baixa os mercados mais ativos e com maior liquidez do mundo."""
    params = {
        "limit": str(limit),
        "active": "true",
        "closed": "false",
        "order": "volume24hr",
        "ascending": "false"
    }
    url = f"{GAMMA_EVENTS_URL}?{urllib.parse.urlencode(params)}"
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    catalog = []

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for item in data:
                ev_title = (item.get("title") or "").strip()
                slug = (item.get("slug") or "").strip()
                markets = item.get("markets", [])

                for m in markets:
                    clob_ids = m.get("clobTokenIds")
                    if isinstance(clob_ids, str):
                        try:
                            clob_ids = json.loads(clob_ids)
                        except Exception:
                            clob_ids = []

                    if not clob_ids or len(clob_ids) == 0:
                        continue

                    q_title = (m.get("question") or "").strip()

                    # Monta o título completo descritivo
                    if q_title and ev_title:
                        if q_title.lower() in ev_title.lower():
                            display_title = ev_title
                        elif ev_title.lower() in q_title.lower():
                            display_title = q_title
                        else:
                            display_title = f"{ev_title} [{q_title}]"
                    else:
                        display_title = q_title or ev_title or "Mercado Preditivo"

                    prices = m.get("outcomePrices", ["0.5", "0.5"])
                    if isinstance(prices, str):
                        try:
                            prices = json.loads(prices)
                        except Exception:
                            prices = ["0.5", "0.5"]

                    yes_price = float(prices[0]) if prices and len(prices) > 0 else 0.5
                    vol_24 = float(m.get("volume24hr") or item.get("volume24hr") or 0.0)
                    liq = float(m.get("liquidity") or 0.0)

                    catalog.append({
                        "display_title": display_title,
                        "token_id_yes": clob_ids[0],
                        "token_id_no": clob_ids[1] if len(clob_ids) > 1 else None,
                        "volume_24h": vol_24,
                        "liquidity": liq,
                        "initial_yes_prob": yes_price,
                        "slug": slug
                    })
    except Exception:
        pass

    return catalog


# ---------------------------------------------------------------------------
# Terminal Bloomberg Polymarket
# ---------------------------------------------------------------------------
class PolymarketBloombergTerminal:
    def __init__(self):
        self.all_markets = []         # Catálogo completo carregado
        self.search_results = []      # Mercados filtrados na busca
        self.search_query = ""
        self.mode = "SEARCH"          # "SEARCH" (mostra lista) ou "LIVE" (mostra orderbook)
        
        self.active_market = None
        self.status_msg = "CONECTANDO À API..."
        self.is_running = True
        self.dirty = True

        # Dados ao vivo do streaming CLOB
        self.live_data = {
            "spot_price": 0.500,
            "implied_prob": 0.500,
            "bids": [],
            "asks": [],
            "last_trade": {
                "price": 0.500,
                "size": 0,
                "side": "BUY",
                "time": "--:--:--"
            }
        }

    def initialize_catalog(self):
        self.status_msg = "BAIXANDO MERCADOS EM ALTA (GAMMA API)..."
        self.all_markets = fetch_active_catalog(limit=100)
        if self.all_markets:
            self.do_search("")  # Inicializa exibindo os maiores mercados
            self.status_msg = f"CATÁLOGO PRONTO ({len(self.all_markets)} MERCADOS DISPONÍVEIS)"
        else:
            self.status_msg = "ERRO AO CARREGAR MERCADOS. VERIFIQUE A CONEXÃO."

    def do_search(self, query: str):
        """Filtra instantaneamente os mercados por palavras-chave."""
        self.search_query = query.strip()
        self.mode = "SEARCH"

        if not self.search_query:
            # Exibe os 8 maiores mercados por volume
            self.search_results = sorted(self.all_markets, key=lambda x: x["volume_24h"], reverse=True)[:8]
            self.status_msg = "EXIBINDO MERCADOS EM ALTA GLOBAIS"
        else:
            terms = self.search_query.lower().split()
            matches = []
            for m in self.all_markets:
                searchable = f"{m['display_title']} {m['slug']}".lower()
                if all(t in searchable for t in terms):
                    matches.append(m)

            matches.sort(key=lambda x: x["volume_24h"], reverse=True)
            self.search_results = matches[:8]
            if self.search_results:
                self.status_msg = f"PESQUISA: {len(self.search_results)} RESULTADOS PARA '{self.search_query}'"
            else:
                self.status_msg = f"NENHUM RESULTADO ENCONTRADO PARA '{self.search_query}'"

        self.dirty = True

    def select_market(self, index: int):
        """Seleciona um mercado da lista de busca e muda para o modo LIVE."""
        if 0 <= index < len(self.search_results):
            self.active_market = self.search_results[index]
            init_prob = self.active_market["initial_yes_prob"]
            self.live_data["spot_price"] = init_prob
            self.live_data["implied_prob"] = init_prob
            self.live_data["bids"] = []
            self.live_data["asks"] = []
            self.live_data["last_trade"] = {
                "price": init_prob,
                "size": 0,
                "side": "BUY",
                "time": datetime.now().strftime("%H:%M:%S")
            }
            self.mode = "LIVE"
            self.status_msg = f"CONECTANDO AO LIVRO DE ORDENS: {self.active_market['display_title'][:30]}..."
            self.dirty = True

    def render_screen(self):
        term_cols, _ = shutil.get_terminal_size((90, 30))
        width = max(80, min(term_cols - 1, 95))

        if self.mode == "SEARCH":
            self._render_search_screen(width)
        else:
            self._render_live_screen(width)

    def _render_search_screen(self, width: int):
        """Renderiza o catálogo de resultados da pesquisa."""
        out = ["\033[H"]
        now_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S").upper()

        box_top = "┌" + "─" * (width - 2) + "┐"
        box_mid = "├" + "─" * (width - 2) + "┤"
        box_bot = "└" + "─" * (width - 2) + "┘"

        title_line = f"│ BLOOMBERG v4.0 | CATALOGO DE PESQUISA POLYMARKET{' ' * max(0, width - 66)}{now_str} │"
        q_label = self.search_query.upper() if self.search_query else "MERCADOS EM ALTA (TRENDING)"
        cmd_head = f"│ <CMD>: PESQUISA [{q_label}] <GO>"
        cmd_head = cmd_head[:width - 1].ljust(width - 1) + "│"

        out.append(f"{AMBER}{BOLD}{box_top}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{title_line[:width]}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{box_mid}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{cmd_head[:width]}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{box_bot}{RESET}\033[K\n")

        # Tabela de Resultados
        out.append(f"{CYAN}{BOLD}RESULTADOS ENCONTRADOS ({len(self.search_results)} TEMAS DISPONÍVEIS):{RESET}\033[K\n")
        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")
        header = f"{AMBER}{BOLD}  {'#':<4} {'MERCADO / PERGUNTA PREDITIVA':<46} {'SIM (YES)':>10} {'NÃO (NO)':>10} {'VOL 24H':>10} {RESET}"
        out.append(f"{header}\033[K\n")
        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")

        if not self.search_results:
            out.append(f"\n  {RED}{BOLD}NENHUM MERCADO ENCONTRADO PARA:{RESET} {WHITE}'{self.search_query}'{RESET}\033[K\n")
            out.append(f"  {DIM}Exemplos de termos com alta liquidez na Polymarket:{RESET}\033[K\n")
            out.append(f"  • {CYAN}/s fed{RESET}       (Cortes de juros do Banco Central dos EUA)\033[K\n")
            out.append(f"  • {CYAN}/s btc{RESET}       (Bitcoin, preços e ETFs)\033[K\n")
            out.append(f"  • {CYAN}/s election{RESET}  (Eleições presidenciais e política)\033[K\n")
            out.append(f"  • {CYAN}/s ai{RESET}        (OpenAI, inteligência artificial, tecnologia)\033[K\n")
            out.append(f"  • {CYAN}/top{RESET}        (Voltar aos mercados mais populares)\033[K\n\n")
        else:
            for i, mkt in enumerate(self.search_results):
                idx_str = f"[{i+1}]"
                title = mkt["display_title"][:45]
                prob_yes = mkt["initial_yes_prob"] * 100
                prob_no = 100.0 - prob_yes
                vol_str = format_volume(mkt["volume_24h"])

                row = (
                    f"  {BRIGHT_AMBER}{idx_str:<4}{RESET} "
                    f"{WHITE}{title:<46}{RESET} "
                    f"{GREEN}{prob_yes:>9.1f}%{RESET} "
                    f"{RED}{prob_no:>9.1f}%{RESET} "
                    f"{GRAY}{vol_str:>10}{RESET}"
                )
                out.append(f"{row}\033[K\n")

        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")
        out.append(f" {DARK_AMBER}STATUS:{RESET} {GREEN}{self.status_msg}{RESET}\033[K\n")
        num_hint = f"1-{len(self.search_results)}" if self.search_results else "--"
        out.append(f" {AMBER}{BOLD}COMANDO <GO>:{RESET} Digite {BOLD}{num_hint}{RESET} para abrir ao vivo │ {BOLD}/s <termo>{RESET} para nova busca │ {BOLD}:q{RESET} sair\033[K\n")
        out.append("\033[J")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def _render_live_screen(self, width: int):
        """Renderiza o livro de ofertas e probabilidades ao vivo do mercado selecionado."""
        out = ["\033[H"]
        now_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S").upper()

        box_top = "┌" + "─" * (width - 2) + "┐"
        box_mid = "├" + "─" * (width - 2) + "┤"
        box_bot = "└" + "─" * (width - 2) + "┘"

        title_line = f"│ BLOOMBERG PROFESSIONAL v4.0 | CLOB REAL-TIME STREAMING{' ' * max(0, width - 69)}{now_str} │"
        m_title = self.active_market["display_title"]
        cmd_head = f"│ <CMD>: PREDICTION MONITOR [{m_title[:width - 45]}] <GO>"
        cmd_head = cmd_head[:width - 1].ljust(width - 1) + "│"

        out.append(f"{AMBER}{BOLD}{box_top}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{title_line[:width]}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{box_mid}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{cmd_head[:width]}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{box_bot}{RESET}\033[K\n")

        # Metadados
        vol_24 = self.active_market["volume_24h"]
        liq = self.active_market["liquidity"]
        token_id = self.active_market["token_id_yes"]

        out.append(f"{BOLD}{CYAN}1. ATIVO MONITORADO:{RESET} {BRIGHT_AMBER}{m_title[:width-25]}{RESET}\033[K\n")
        out.append(f"  • {BOLD}Token:{RESET} {GRAY}{token_id[:35]}...{RESET} │ {BOLD}Vol 24h:{RESET} {format_volume(vol_24)} │ {BOLD}Liquidez:{RESET} {format_volume(liq)}\033[K\n")
        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")

        # Probabilidade Implícita e Barra Visual
        prob = self.live_data["implied_prob"] * 100
        prob_no = 100.0 - prob
        price = self.live_data["spot_price"]

        out.append(f"{BOLD}{CYAN}2. PROBABILIDADE IMPLÍCITA & COTAÇÃO SPOT (SIM / NÃO):{RESET}\033[K\n")
        out.append(f"  • {BOLD}SIM (YES):{RESET} {GREEN}{BOLD}{prob:.1f}%{RESET} (${price:.3f}) │ {BOLD}NÃO (NO):{RESET} {RED}{BOLD}{prob_no:.1f}%{RESET} (${(1-price):.3f})\033[K\n")

        bar_len = max(20, width - 35)
        yes_len = int((prob / 100.0) * bar_len)
        no_len = max(0, bar_len - yes_len)
        bar_str = f"{GREEN}{'█' * yes_len}{RESET}{RED}{'█' * no_len}{RESET}"
        out.append(f"  • {BOLD}Probabilidade:{RESET} [{bar_str}] {GREEN}YES {prob:.1f}%{RESET} / {RED}NO {prob_no:.1f}%{RESET}\033[K\n")
        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")

        # Última Negociação Executada
        lt = self.live_data["last_trade"]
        side_color = GREEN if lt["side"] == "BUY" else RED
        out.append(f"{BOLD}{CYAN}3. ÚLTIMA EXECUÇÃO REALIZADA (CLOB TRADE):{RESET}\033[K\n")
        out.append(f"  • {BOLD}Preço:{RESET} ${lt['price']:.3f} │ {BOLD}Qtd:{RESET} {lt['size']:,} │ {BOLD}Lado:{RESET} {side_color}{lt['side']}{RESET} │ {BOLD}Hora:{RESET} {DIM}{lt['time']}{RESET}\033[K\n")
        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")

        # Livro de Ofertas L2 (Bids & Asks)
        out.append(f"{BOLD}{CYAN}4. LIVRO DE OFERTAS EM TEMPO REAL (ORDER BOOK L2):{RESET}\033[K\n")
        out.append(f"  {GREEN}{BOLD}{'COMPRA (BIDS)':<38}{RESET} │ {RED}{BOLD}{'VENDA (ASKS)':<38}{RESET}\033[K\n")
        out.append(f"  {GRAY}{'Preço':<9} {'Qtd':<12} {'Total($)':<12}{RESET} │ {GRAY}{'Preço':<9} {'Qtd':<12} {'Total($)':<12}{RESET}\033[K\n")
        out.append(f"  {DARK_AMBER}{'─' * 36}┼{'─' * 38}{RESET}\033[K\n")

        bids = self.live_data["bids"][:5]
        asks = self.live_data["asks"][:5]
        max_rows = max(len(bids), len(asks))

        if max_rows == 0:
            out.append(f"  {DIM}Aguardando primeiras ordens do streaming CLOB...{RESET}\033[K\n")
        else:
            for r in range(max_rows):
                b_str = ""
                if r < len(bids):
                    b = bids[r]
                    bp, bs = float(b["price"]), float(b["size"])
                    b_str = f"{GREEN}${bp:<7.3f}{RESET} {bs:<11,.0f} ${bp*bs:<10,.1f}"

                a_str = ""
                if r < len(asks):
                    a = asks[r]
                    ap, asize = float(a["price"]), float(a["size"])
                    a_str = f"{RED}${ap:<7.3f}{RESET} {asize:<11,.0f} ${ap*asize:<10,.1f}"

                out.append(f"  {b_str:<45} │ {a_str}\033[K\n")

        # Rodapé
        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")
        out.append(f" {DARK_AMBER}STATUS:{RESET} {GREEN}{self.status_msg}{RESET}\033[K\n")
        out.append(f" {AMBER}{BOLD}COMANDO <GO>:{RESET} Digite {BOLD}/s <termo>{RESET} para buscar │ {BOLD}/menu{RESET} para ver a lista │ {BOLD}:q{RESET} sair\033[K\n")
        out.append("\033[J")

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def process_ws_message(self, raw_text: str):
        try:
            packet = json.loads(raw_text)
            if isinstance(packet, list):
                for p in packet:
                    self._handle_event(p)
            else:
                self._handle_event(packet)
            self.dirty = True
        except Exception:
            pass

    def _handle_event(self, event: dict):
        ev_type = event.get("event_type")

        if ev_type == "book":
            bids = event.get("bids", [])
            asks = event.get("asks", [])
            self.live_data["bids"] = sorted(bids, key=lambda x: float(x["price"]), reverse=True)
            self.live_data["asks"] = sorted(asks, key=lambda x: float(x["price"]))

            if self.live_data["bids"]:
                best_bid = float(self.live_data["bids"][0]["price"])
                self.live_data["spot_price"] = best_bid
                self.live_data["implied_prob"] = best_bid

        elif ev_type == "price_change":
            price = event.get("price")
            if price:
                p_f = float(price)
                self.live_data["spot_price"] = p_f
                self.live_data["implied_prob"] = p_f

        elif ev_type == "last_trade_price":
            p = float(event.get("price") or self.live_data["spot_price"])
            sz = int(float(event.get("size") or 0))
            sd = event.get("side", "BUY")
            self.live_data["last_trade"] = {
                "price": p,
                "size": sz,
                "side": sd,
                "time": datetime.now().strftime("%H:%M:%S")
            }
            self.live_data["spot_price"] = p
            self.live_data["implied_prob"] = p


# ---------------------------------------------------------------------------
# Entrada de Teclado & Tarefas Assíncronas
# ---------------------------------------------------------------------------
def stdin_thread(queue, loop):
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if line:
                loop.call_soon_threadsafe(queue.put_nowait, line)
        except Exception:
            break


async def render_loop(terminal):
    while terminal.is_running:
        terminal.render_screen()
        await asyncio.sleep(0.1)


async def websocket_loop(terminal, cmd_queue):
    while terminal.is_running:
        # Se estiver em modo SEARCH, não precisa manter conexão WS ativa
        if terminal.mode == "SEARCH" or not terminal.active_market:
            while terminal.is_running and terminal.mode == "SEARCH":
                try:
                    cmd = await asyncio.wait_for(cmd_queue.get(), timeout=0.2)
                    if cmd == ":q":
                        terminal.is_running = False
                        break
                    elif cmd.startswith("/s"):
                        terminal.do_search(cmd[2:].strip())
                    elif cmd in ("/top", "/menu", "/trending"):
                        terminal.do_search("")
                    elif cmd.isdigit():
                        idx = int(cmd) - 1
                        if 0 <= idx < len(terminal.search_results):
                            terminal.select_market(idx)
                            cmd_queue.task_done()
                            break  # Sai do modo SEARCH e abre o WebSocket
                    cmd_queue.task_done()
                except asyncio.TimeoutError:
                    pass
            continue

        # Modo LIVE: conecta ao WebSocket do token selecionado
        active_token = terminal.active_market["token_id_yes"]
        try:
            terminal.status_msg = f"CONECTANDO CLOB ({active_token[:10]}...)"
            async with websockets.connect(POLYMARKET_WS_URL, open_timeout=8) as ws:
                terminal.status_msg = "STREAMING CLOB ATIVO (DADOS REAIS)"
                
                # Inscrição oficial da Polymarket
                await ws.send(json.dumps({
                    "assets_ids": [active_token],
                    "type": "market"
                }))

                async def command_consumer():
                    while terminal.is_running:
                        cmd = await cmd_queue.get()
                        if cmd == ":q":
                            terminal.is_running = False
                            await ws.close()
                            break
                        elif cmd.startswith("/s"):
                            terminal.do_search(cmd[2:].strip())
                            await ws.close()
                            break
                        elif cmd in ("/top", "/menu", "/trending"):
                            terminal.do_search("")
                            await ws.close()
                            break
                        elif cmd.isdigit():
                            idx = int(cmd) - 1
                            if 0 <= idx < len(terminal.search_results):
                                terminal.select_market(idx)
                                await ws.close()
                                break
                        cmd_queue.task_done()

                cmd_task = asyncio.create_task(command_consumer())

                try:
                    async for message in ws:
                        if not terminal.is_running:
                            break
                        terminal.process_ws_message(message)
                finally:
                    cmd_task.cancel()

        except Exception:
            terminal.status_msg = "CONEXÃO OSCILOU. RECONECTANDO..."
            await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    terminal = PolymarketBloombergTerminal()
    cmd_queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    enter_alt_screen()
    terminal.initialize_catalog()

    t = threading.Thread(target=stdin_thread, args=(cmd_queue, loop), daemon=True)
    t.start()

    try:
        await asyncio.gather(
            render_loop(terminal),
            websocket_loop(terminal, cmd_queue)
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        terminal.is_running = False
        exit_alt_screen()
        sys.stdout.write(f"\n{AMBER}Sessão Polymarket Terminal Encerrada.{RESET}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass