#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================================================================
YAHOO FINANCE — BLOOMBERG TERMINAL v2.5 (RESPONSIVE & ANTI-SPAM ENGINE)
===================================================================================
- Imune a quebras de linha em terminais estreitos (responsivo a partir de 80 cols).
- Buffer alternativo de tela cheia (\033[?1049h) — sem rolagem infinita.
- Limpeza estrita de linha por linha (\033[K) — zero sobreposição de texto.
- Decodificação Protobuf nativa (Varint + ZigZag + IEEE-754).
- Linha de comando interativa (+TICKER, -TICKER, :q).
===================================================================================
Dependências: pip install websockets
Uso: python bloomberg_terminal_v2_fixed.py AAPL NVDA TSLA PETR4.SA BTC-USD BRL=X
===================================================================================
"""

import asyncio
import atexit
import base64
import json
import os
import shutil
import struct
import sys
import threading
import time
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
BRIGHT_AMBER = "\033[38;5;220m" # Dourado Brilhante
DARK_AMBER = "\033[38;5;172m"   # Âmbar Escuro (Bordas)
GREEN = "\033[38;5;46m"          # Verde Neon (+)
RED = "\033[38;5;196m"           # Vermelho Carmesim (-)
GRAY = "\033[38;5;242m"
CYAN = "\033[38;5;51m"
WHITE = "\033[38;5;231m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

FLASH_GREEN = "\033[48;5;22m\033[38;5;46m\033[1m"
FLASH_RED = "\033[48;5;52m\033[38;5;196m\033[1m"

INDEX_TAPE = ["^GSPC", "^IXIC", "^VIX", "BTC-USD"]


# ---------------------------------------------------------------------------
# Controle de Terminal (Buffer Alternativo e Cursor)
# ---------------------------------------------------------------------------
def enter_alt_screen():
    # Entra no buffer alternativo, esconde cursor, limpa tela
    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
    sys.stdout.flush()

def exit_alt_screen():
    # Restaura tela original e cursor ao sair
    sys.stdout.write("\033[?25h\033[?1049l")
    sys.stdout.flush()

atexit.register(exit_alt_screen)


# ---------------------------------------------------------------------------
# Decodificador Protobuf Nativo
# ---------------------------------------------------------------------------
def read_varint(buf: bytes, pos: int):
    result, shift = 0, 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7

def zigzag_decode(val: int) -> int:
    return (val >> 1) ^ -(val & 1)

def parse_pricing_protobuf(b64_payload: str) -> dict:
    try:
        raw_bytes = base64.b64decode(b64_payload)
        idx, length = 0, len(raw_bytes)
        fields = {}

        while idx < length:
            tag, idx = read_varint(raw_bytes, idx)
            field_num = tag >> 3
            wire_type = tag & 0x07

            if wire_type == 0:
                val, idx = read_varint(raw_bytes, idx)
                if field_num in (3, 9, 14, 19, 22, 24, 26, 27):
                    val = zigzag_decode(val)
                fields[field_num] = val
            elif wire_type == 5:
                val = struct.unpack("<f", raw_bytes[idx:idx + 4])[0]
                idx += 4
                fields[field_num] = val
            elif wire_type == 1:
                val = struct.unpack("<d", raw_bytes[idx:idx + 8])[0]
                idx += 8
                fields[field_num] = val
            elif wire_type == 2:
                str_len, idx = read_varint(raw_bytes, idx)
                payload = raw_bytes[idx:idx + str_len]
                idx += str_len
                fields[field_num] = payload.decode("utf-8", errors="replace")
            else:
                break

        return fields
    except Exception:
        return {}

def format_volume(vol: int) -> str:
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.2f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.2f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return str(vol) if vol > 0 else "--"


# ---------------------------------------------------------------------------
# Terminal Responsivo
# ---------------------------------------------------------------------------
class BloombergTerminalPro:
    def __init__(self, user_symbols):
        self.user_symbols = list(dict.fromkeys(user_symbols))
        self.all_symbols = list(dict.fromkeys(self.user_symbols + INDEX_TAPE))
        self.url = "wss://streamer.finance.yahoo.com?version=2"

        self.data_store = {}
        self.flash_store = {}
        self.command_input = ""
        self.status_msg = "CONECTADO AO WSS GATEWAY"
        self.is_running = True
        self.dirty = True

        for s in self.all_symbols:
            self._init_symbol_store(s)

    def _init_symbol_store(self, sym):
        self.data_store[sym] = {
            "price": 0.0,
            "change": 0.0,
            "changePercent": 0.0,
            "dayHigh": 0.0,
            "dayLow": 0.0,
            "volume": 0,
            "bid": 0.0,
            "ask": 0.0,
            "marketHours": "REG",
            "priceHint": 2,
            "last_update": "--:--:--"
        }

    def render_screen(self):
        # Mede tamanho real do terminal dinamicamente
        term_cols, term_rows = shutil.get_terminal_size((90, 30))
        width = max(80, min(term_cols - 1, 95))  # Largura segura sem quebra de linha

        out = ["\033[H"]  # Move cursor para o canto superior esquerdo
        now_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S").upper()

        # Cabeçalho da Caixa
        box_top = "┌" + "─" * (width - 2) + "┐"
        box_mid = "├" + "─" * (width - 2) + "┤"
        box_bot = "└" + "─" * (width - 2) + "┘"

        title_line = f"│ BLOOMBERG v2.5 | STREAMER REAL-TIME{' ' * (width - 55)}{now_str} │"
        cmd_head = f"│ <CMD>: MONITOR [{', '.join(self.user_symbols)}]"
        cmd_head = (cmd_head[:width - 7] + " <GO>").ljust(width - 1) + "│"

        out.append(f"{AMBER}{BOLD}{box_top}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{title_line[:width]}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{box_mid}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{cmd_head[:width]}{RESET}\033[K\n")
        out.append(f"{AMBER}{BOLD}{box_bot}{RESET}\033[K\n")

        # Fita Global Superior
        tape_items = []
        for idx in INDEX_TAPE:
            d = self.data_store.get(idx, {})
            name = idx.replace("^", "")
            p = d.get("price", 0.0)
            cp = d.get("changePercent", 0.0)
            color = GREEN if cp >= 0 else RED
            sign = "+" if cp >= 0 else ""
            p_str = f"{p:,.1f}" if p > 0 else "--"
            tape_items.append(f"{BOLD}{WHITE}{name}{RESET} {p_str} {color}{sign}{cp:.1f}%{RESET}")

        tape_line = f" {DARK_AMBER}TAPE:{RESET} " + f" {DARK_AMBER}│{RESET} ".join(tape_items)
        out.append(f"{tape_line}\033[K\n")
        out.append(f"{GRAY}{'─' * width}{RESET}\033[K\n")

        # Cabeçalho da Tabela
        header_cols = f"{AMBER}{BOLD} {'TICKER':<9} {'LAST':>10} {'CHANGE':>9} {'% CHG':>8} {'BID':>8} {'ASK':>8} {'HIGH':>8} {'LOW':>8} {'VOL':>7} {'SES':^5} {'TIME':>8} {RESET}"
        out.append(f"{header_cols}\033[K\n")
        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")

        now = time.time()

        # Linhas de Cotação
        for sym in self.user_symbols:
            d = self.data_store[sym]
            p = d["price"]
            c = d["change"]
            cp = d["changePercent"]
            dh = d["dayHigh"]
            dl = d["dayLow"]
            bid = d["bid"]
            ask = d["ask"]
            vol_str = format_volume(d["volume"])
            ses = d["marketHours"]
            t_str = d["last_update"]
            hint = d.get("priceHint", 2)

            if p == 0.0:
                out.append(f" {BRIGHT_AMBER}{sym:<9}{RESET} {DIM}{'CONNECTING...':>10}{RESET} {'--':>9} {'--':>8} {'--':>8} {'--':>8} {'--':>8} {'--':>8} {'--':>7} {ses:^5} {t_str:>8}\033[K\n")
                continue

            flash_info = self.flash_store.get(sym)
            cell_color = GREEN if cp >= 0 else RED
            p_fmt = f"{p:10.{hint}f}"

            if flash_info and (now - flash_info[1]) < 0.6:
                if flash_info[0] == "UP":
                    price_cell = f"{FLASH_GREEN}{p_fmt}{RESET}"
                else:
                    price_cell = f"{FLASH_RED}{p_fmt}{RESET}"
            else:
                price_cell = f"{BOLD}{WHITE}{p_fmt}{RESET}"

            sign = "+" if cp >= 0 else ""
            c_str = f"{sign}{c:.{hint}f}"
            cp_str = f"{sign}{cp:.2f}%"

            bid_str = f"{bid:.{hint}f}" if bid > 0 else "--"
            ask_str = f"{ask:.{hint}f}" if ask > 0 else "--"
            dh_str = f"{dh:.{hint}f}" if dh > 0 else "--"
            dl_str = f"{dl:.{hint}f}" if dl > 0 else "--"

            row = (
                f" {BRIGHT_AMBER}{sym:<9}{RESET} "
                f"{price_cell} "
                f"{cell_color}{c_str:>9}{RESET} "
                f"{cell_color}{cp_str:>8}{RESET} "
                f"{CYAN}{bid_str:>8}{RESET} "
                f"{CYAN}{ask_str:>8}{RESET} "
                f"{WHITE}{dh_str:>8}{RESET} "
                f"{WHITE}{dl_str:>8}{RESET} "
                f"{GRAY}{vol_str:>7}{RESET} "
                f"{DARK_AMBER}{ses:^5}{RESET} "
                f"{DIM}{t_str:>8}{RESET}"
            )
            out.append(f"{row}\033[K\n")

        # Rodapé e Barra de Comandos
        out.append(f"{DARK_AMBER}{'─' * width}{RESET}\033[K\n")
        status_bar = f" {DARK_AMBER}STATUS:{RESET} {GREEN}{self.status_msg}{RESET} | Comandos: {BOLD}+TICKER{RESET}, {BOLD}-TICKER{RESET}, {BOLD}:q{RESET}"
        out.append(f"{status_bar[:width + 15]}\033[K\n")
        out.append(f" {AMBER}{BOLD}COMMAND LINE <GO>:{RESET} {BRIGHT_AMBER}{self.command_input}{RESET}\033[K\n")
        out.append("\033[J")  # Apaga tudo abaixo, garantindo tela 100% limpa

        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def update_quote(self, fields):
        sym = fields.get(1)
        if not sym or sym not in self.data_store:
            return

        old_p = self.data_store[sym]["price"]
        new_p = fields.get(2, old_p)

        if old_p > 0 and new_p != old_p:
            direction = "UP" if new_p > old_p else "DOWN"
            self.flash_store[sym] = (direction, time.time())

        m_hours_code = fields.get(7, 1)
        session_map = {0: "PRE", 1: "REG", 2: "POST", 3: "EXT", 4: "OVR"}
        ses = session_map.get(m_hours_code, "REG")

        hint = fields.get(27, 2)
        if hint <= 0 or hint > 4:
            hint = 4 if ("=X" in sym) else 2

        self.data_store[sym].update({
            "price": new_p,
            "change": fields.get(12, self.data_store[sym]["change"]),
            "changePercent": fields.get(8, self.data_store[sym]["changePercent"]),
            "dayHigh": fields.get(10, self.data_store[sym]["dayHigh"]),
            "dayLow": fields.get(11, self.data_store[sym]["dayLow"]),
            "volume": fields.get(9, self.data_store[sym]["volume"]),
            "bid": fields.get(23, self.data_store[sym]["bid"]),
            "ask": fields.get(25, self.data_store[sym]["ask"]),
            "marketHours": ses,
            "priceHint": hint,
            "last_update": datetime.now().strftime("%H:%M:%S")
        })
        self.dirty = True

    async def render_loop(self):
        while self.is_running:
            # Redesenha a cada 100ms
            self.render_screen()
            await asyncio.sleep(0.1)

    async def websocket_loop(self, queue):
        headers = {
            "Origin": "https://finance.yahoo.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        while self.is_running:
            try:
                self.status_msg = "CONECTANDO AO WSS..."
                async with websockets.connect(self.url, additional_headers=headers, open_timeout=10) as ws:
                    self.status_msg = "STREAMING ATIVO"
                    await ws.send(json.dumps({"subscribe": self.all_symbols}))

                    async def handle_commands():
                        while self.is_running:
                            cmd = await queue.get()
                            if cmd == ":q":
                                self.is_running = False
                                await ws.close()
                                break
                            elif cmd.startswith("+"):
                                sym = cmd[1:].strip().upper()
                                if sym and sym not in self.all_symbols:
                                    self.user_symbols.append(sym)
                                    self.all_symbols.append(sym)
                                    self._init_symbol_store(sym)
                                    await ws.send(json.dumps({"subscribe": [sym]}))
                                    self.status_msg = f"ATIVO ADICIONADO: {sym}"
                            elif cmd.startswith("-"):
                                sym = cmd[1:].strip().upper()
                                if sym in self.user_symbols:
                                    self.user_symbols.remove(sym)
                                    await ws.send(json.dumps({"unsubscribe": [sym]}))
                                    self.status_msg = f"ATIVO REMOVIDO: {sym}"
                            queue.task_done()

                    cmd_task = asyncio.create_task(handle_commands())

                    try:
                        async for message in ws:
                            if not self.is_running:
                                break
                            try:
                                packet = json.loads(message)
                                b64 = packet.get("message") or packet.get("payload")
                                if b64:
                                    fields = parse_pricing_protobuf(b64)
                                    self.update_quote(fields)
                            except Exception:
                                pass
                    finally:
                        cmd_task.cancel()

            except Exception as e:
                self.status_msg = f"CONEXÃO PERDIDA. RECONECTANDO..."
                await asyncio.sleep(3)


def stdin_reader_thread(queue, loop):
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


async def main():
    default_symbols = ["AAPL", "NVDA", "TSLA", "PETR4.SA", "BTC-USD", "BRL=X"]
    symbols = sys.argv[1:] if len(sys.argv) > 1 else default_symbols

    terminal = BloombergTerminalPro(symbols)
    cmd_queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    enter_alt_screen()

    t = threading.Thread(target=stdin_reader_thread, args=(cmd_queue, loop), daemon=True)
    t.start()

    try:
        await asyncio.gather(
            terminal.render_loop(),
            terminal.websocket_loop(cmd_queue)
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        terminal.is_running = False
        exit_alt_screen()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass