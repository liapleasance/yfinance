#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 YF·AUTH ENGINE EXPLORER v5.0 — Terminal Interativo & Cliente Canônico
 Foco Exclusivo: Autenticação Yahoo Finance (Cookie A3 + Crumb + GUC)
═══════════════════════════════════════════════════════════════════════════════
 REQUISITOS ATENDIDOS:
   1. ANTI-FECHAMENTO (CRÍTICO):
      - Sem argumentos -> abre MENU INTERATIVO contínuo (sai na opção 0).
      - Nenhum traceback derruba o app (try/except gracioso em todas as rotinas).
      - Ao sair: pausa "Pressione ENTER para fechar" (flag --no-pause p/ scripts).
      - Tratamento gracioso de Ctrl+C e EOF.
   2. ZERO DEPENDÊNCIAS EXTERNAS:
      - 100% biblioteca padrão Python (urllib, http.cookiejar, json, shutil, re, etc.).
      - Totalmente compatível com Python 3.8 até 3.13+.
   3. UI DESIGN BLOOMBERG TERMINAL:
      - Paleta profissional em ANSI/TrueColor (#FFA028, #FFD600, #00C853, #FF433D,
        #00D4FF, #0068FF, #4AF6C3, #A0A0A0, #808080).
      - Caixas curvas ╭─╮│╰╯ e tabelas de dados com padding imune a códigos ANSI.
      - Fallbacks automáticos: --ascii (caixas +---+) e --sem-cores (--no-color).
      - UTF-8 forçado em stdout/stderr e formatação localizada pt-BR.
   4. TODAS AS FUNÇÕES DE AUTENTICAÇÃO EXPOSTAS:
      - Bootstrap canônico: fc.yahoo.com (Set-Cookie A3) -> getcrumb.
      - Resolução de Crumb em cascata multi-estratégia (vault, html, endpoint, streamer).
      - Parser TLV binário embutido do Cookie A3 (Version, Flags, Nonce, Timestamps,
        Temp/Agent ID, GUC 18 consentimentos, Y32 Legacy/Virtual BID, etc.).
      - Gestão do cofre (CookieVault atômico, chmod 600, exportação Netscape cookies.txt).
      - Diagnóstico do gate GDPR/Consent e simulação de máquina de estados GUCE.
      - Teste de consumo autenticado ao vivo contra /v7/finance/quote.
      - Suíte de verificação ao vivo com 20 testes de conformidade (20/20 PASS).
      - Auditoria estrutural offline de cofres JSON e arquivos cookies.txt.
      - Console de requisições brutas (diagnóstico HTTP com injeção de sessão).
   5. ROBUSTEZ DE REDE:
      - Retry com backoff exponencial 2^n e jitter para HTTP 429/503 (máx 5 tentativas).
      - Medição exata de latência (ms) e contagem de bytes trafegados.
      - Auto-recuperação e classificação de 401 ("Invalid Cookie" vs "Invalid Crumb").
   6. COMPATIBILIDADE CLI TOTAL:
      - Preserva suporte a --jar, --symbols, --strategy, --fresh, --inspect,
        --decode-a3, --from-jar, --taxonomy, --guce-crumb, --streamer-crumb,
        --to-cookiejar, --no-pause, etc.
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import base64
import datetime
import gzip
import http.cookiejar
from http.cookiejar import Cookie as _StdCookie, MozillaCookieJar as _MozillaCookieJar
import json
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Dict, List, Optional, Tuple, Union

__version__ = "5.0.0"

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

# ════════════════════════ Constantes do Protocolo ═══════════════════════════

FC_YAHOO = "https://fc.yahoo.com/"
FINANCE_HOME = "https://finance.yahoo.com/"
GUCE_CONSENT = "https://guce.yahoo.com/consent"
GUCE_COPY_CONSENT = "https://guce.yahoo.com/copyConsent"
CONSENT_COLLECT_DEFAULT = "https://consent.yahoo.com/v2/collectConsent"
QUERY_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
GETCRUMB_PATH = "/v1/test/getcrumb"
QUOTE_PATH = "/v7/finance/quote"

JAR_DEFAULT = "yahoo_session.json"
A3_MAX_AGE = 31557600
DEFAULT_TIMEOUT = 15.0
STREAMER_TIMEOUT = 10.0

USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

AUTH_FAMILY = ("A1", "A3", "A1S", "GUC", "OTHD")
HTTPONLY_FAMILY = {"A1", "A3"}
COOKIE_TAXONOMY = ("T", "Y", "F", "FS", "A1", "A1S", "A3", "B", "BX", "OTH", "OTHP", "AS")
EDGE_CREDENTIALS = ("A1", "A3")
GUC_DEBUG_WITH_VALUE = "GUC"
MOCK_CRUMB = "MOCK_CRUMB"
CRUMB_RE = re.compile(r"[A-Za-z0-9._/-]{5,64}")

CRUMB_PATTERNS = (
    r'"crumb"\s*:\s*"([^"]{5,64})"',
    r"'crumb'\s*:\s*'([^']{5,64})'",
    r"\bcrumb=([A-Za-z0-9._/-]{5,64})",
)

GUCE_ROUTES = {
    "limitSaleSharePopUpEndPoint": "banners/sellPersonalInfo",
    "checkShowSellInfoPopup": "consent/sellPersonalInfoStatus",
    "checkShowGpcPopup": "consent/gpcStatus",
    "checkInlineGdprConsentTrap": "/v1/consentCheck/inline",
    "handleGPCEndpoint": "consent/handleGlobalPrivacyControl",
    "handleLimitSaleEndpoint": "consent/handleSellPersonalInfo",
    "gpcPopUpEndPoint": "gpc/notice",
    "cookieAndDbUpdateGpc": "consent/gpcUpdate",
    "cookieAndDbUpdateLimitSale": "consent/sellPersonalInfoUpdate",
    "oidcInitRoute": "banners/oidc/init",
    "underageStatusUpdate": "consent/underageStatusUpdate",
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

def fmt_epoch_local(epoch_val: Any) -> str:
    """Converte Unix timestamp para data e hora local brasileira."""
    if not epoch_val:
        return "—"
    try:
        ts = float(epoch_val)
        if ts > 1e11:
            ts /= 1000.0
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(epoch_val)


def fmt_numero_br(valor: Any, decimais: int = 2) -> str:
    """Formata valor numérico no padrão brasileiro: 1.234.567,89."""
    if valor is None:
        return "—"
    try:
        f = float(valor)
        partes = f"{f:,.{decimais}f}".split(".")
        inteiro = partes[0].replace(",", ".")
        decimal = partes[1] if len(partes) > 1 else ""
        return f"{inteiro},{decimal}" if decimal else inteiro
    except (ValueError, TypeError):
        return str(valor)


def fmt_percentual_br(valor: Any) -> str:
    """Formata percentual no padrão brasileiro."""
    if valor is None:
        return "—"
    try:
        f = float(valor)
        sinal = "+" if f > 0 else ""
        return f"{sinal}{fmt_numero_br(f, 2)}%"
    except (ValueError, TypeError):
        return str(valor)


def mascara_token(token: Optional[str], n: int = 6) -> str:
    """Mascara strings sensíveis preservando prefixo e tamanho total."""
    if not token:
        return "—"
    if len(token) <= n:
        return token
    return f"{token[:n]}... ({len(token)} chars)"


# ═══════════════════════ Parser TLV do Cookie A3 ════════════════════════════

TLV_TAGS = {
    "NONCE": "00", "CREATION_TS": "01", "TEMP_ID": "02", "AGENT_ID": "03",
    "EXPIRY_TS": "04", "GUC": "05", "LEGACY_BID": "07", "E_SID": "08",
    "E_SID_NAMESPACE": "09", "E_DEMOG": "10", "R_SYNTH_ID": "11",
    "E_DEMOG_2": "12",
}

FLAG_NAMES = {0: "NO_CRYPTO_LIB", 1: "APP_POLICY"}

GUC_CONSENT_TYPES = {
    1: "NON_EU_CONSENT", 2: "CORE_EU_CONSENT", 4: "OATH_AS_THIRD_PARTY",
    8: "ANALYSIS_OF_COMMUNICATIONS", 16: "PRECISE_GEOLOCATION", 32: "CROSS_DEVICE_MAPPING",
    64: "ACCOUNT_MATCHING", 128: "SEARCH_HISTORY", 256: "FIRST_PARTY_ADS",
    512: "CONTENT_PERSONALIZATION", 1024: "IAB", 2048: "THIRD_PARTY_CONSENT",
    4096: "ALLOW_HUMANS_TO_READ_EMAILS", 8192: "SELL_PERSONAL_INFORMATION",
    16384: "GENERAL_ANALYSIS_CONSENT", 32768: "THIRD_PARTY_CONTENT_EMBED",
    65536: "INSIGHTS_FROM_COMMUNICATIONS", 131072: "THIRD_PARTY_ANALYTICS",
}

GUC_FIELD_SIZES = {
    "TOS": 2, "USER_TYPE": 2, "CONSENT_VERSION": 2, "CONSENTED": 2,
    "VALIDITY_CHECK_TIME": 6, "EXPIRY_TIME": 4, "JURISDICTION": 2,
    "HOME_LOCATION": 8, "CONSENT_TYPES": 8,
}

TOS_MAP = ["EU_OATH", "NON_EU_OATH"]
USER_TYPE_MAP = ["REG", "NON_REG"]
CONSENTED_MAP = ["NOT_CONSENTED", "CONSENTED", "DECLARED_NON_EU"]
ESID_NAMESPACE_ENUM = ["AOL", "ENGADGET", "HUFFPOST", "MAPQUEST", "MOVIEFONE", "PROJECTLITTLE", "TECHCRUNCH", "YAHOO"]
Y32_ALPHABET = "0123456789abcdefghijklmnopqrstuv"

COUNTRY_CODES = [
    "AF", "AX", "AL", "DZ", "AS", "AD", "AO", "AI", "AQ", "AG", "AR", "AM", "AW", "AU", "AZ", "BS", "BH", "BD", "BB", "BY",
    "BE", "BZ", "BJ", "BM", "BT", "BO", "BQ", "BA", "BW", "BV", "BR", "IO", "BN", "BF", "BI", "KH", "CM", "CA", "CV", "KY",
    "CF", "TD", "CL", "CN", "CX", "CC", "CO", "KM", "CG", "CD", "CK", "CR", "CI", "CU", "CW", "DJ", "DM", "EC", "EG", "SV",
    "GQ", "ER", "ET", "FK", "FO", "FJ", "GF", "PF", "TF", "GA", "GM", "GE", "GH", "GI", "GR", "GL", "GD", "GP", "GU", "GT",
    "GG", "GN", "GW", "GY", "HT", "HM", "VA", "HN", "HK", "IN", "ID", "IR", "IQ", "IM", "IL", "JM", "JP", "JE", "JO", "KZ",
    "KE", "KI", "KP", "KR", "KW", "KG", "LA", "LV", "LB", "LS", "LR", "LY", "MO", "MK", "MG", "MW", "MY", "MV", "ML", "MH",
    "MQ", "MR", "MU", "YT", "MX", "FM", "MD", "MC", "MN", "ME", "MS", "MA", "MZ", "MM", "NA", "NR", "NP", "NC", "NZ", "NI",
    "NE", "NG", "NU", "NF", "MP", "OM", "PK", "PW", "PS", "PA", "PG", "PY", "PE", "PH", "PN", "PR", "QA", "RE", "RU", "RW",
    "BL", "SH", "KN", "LC", "MF", "PM", "VC", "WS", "SM", "ST", "SA", "SN", "RS", "SC", "SL", "SG", "SX", "SB", "SO", "ZA",
    "GS", "SS", "LK", "SD", "SR", "SJ", "SZ", "CH", "SY", "TW", "TJ", "TZ", "TH", "TL", "TG", "TK", "TO", "TT", "TN", "TR",
    "TM", "TC", "TV", "UG", "UA", "AE", "GB", "UM", "UY", "UZ", "VU", "VE", "VN", "VG", "VI", "WF", "EH", "YE", "ZM", "ZW",
    "US", "BG", "CZ", "DK", "DE", "EE", "IE", "EL", "ES", "FR", "HR", "IT", "CY", "LT", "LU", "HU", "MT", "NL", "AT", "PL",
    "PT", "RO", "SI", "SK", "FI", "SE", "UK", "IS", "LI", "NO"
]


def base64url_to_bytes(s: str) -> bytes:
    if not s:
        return b""
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def bytes_to_b64url(data: bytes) -> str:
    return base64.b64encode(data).decode().replace("+", "-").replace("/", "_").rstrip("=")


def hex_to_bytes(h: str) -> bytes:
    return bytes.fromhex(h) if h else b""


def hex_be_to_hex_le(h: str) -> str:
    if not h:
        return ""
    return "".join(h[i:i + 2] for i in range(len(h) - 2, -1, -2))


def hex_to_int(h: str) -> Optional[int]:
    if not h:
        return None
    return int(hex_be_to_hex_le(h), 16)


def binary_to_hex(binary: str) -> str:
    return "".join(f"{int(binary[i:i+4], 2):X}" for i in range(0, len(binary), 4))


def hex_to_tlv(hexstr: str) -> Dict[str, str]:
    tlv: Dict[str, str] = {}
    t = hexstr
    while t:
        tag = t[:2].upper()
        t = t[2:]
        if len(t) < 2:
            break
        n = int(t[:2], 16) * 2
        t = t[2:]
        tlv[tag] = t[:n]
        t = t[n:]
    return tlv


def convert_hex_to_y32(h: str) -> Optional[str]:
    b = hex_to_bytes(h)
    if len(b) != 8:
        return None
    n = int.from_bytes(b, "big")
    out = ""
    for _ in range(13):
        out = Y32_ALPHABET[n & 31] + out
        n >>= 5
    return out


def get_virtual_bid(parsed: Dict[str, Any]) -> Optional[str]:
    aid = parsed.get("agentId_b64url") or parsed.get("temporaryId_b64url")
    if not parsed.get("creationTime") or not aid:
        return None
    a = base64url_to_bytes(aid)
    if len(a) < 4:
        return None
    high = int.from_bytes(a[-4:], "little") & 0xFFFFFFFF
    low = parsed["creationTime"] & 0xFFFFFFFF
    n = (high << 32) | low
    out = ""
    for _ in range(13):
        out = Y32_ALPHABET[n & 31] + out
        n >>= 5
    return out


def parse_acookie(raw: str) -> Dict[str, Any]:
    """Decodificador completo de Cookie A3 em stdlib puro."""
    data, jurisdiction = "", ""
    for part in raw.split("&"):
        if part.startswith("d="):
            data = part[2:]
        elif part.startswith("j="):
            jurisdiction = part[2:]
    if not data:
        return {"error": "Cookie A3 inválido: sem partição d="}

    raw_bytes = base64url_to_bytes(data)
    if len(raw_bytes) < 2:
        return {"error": "Payload d= excessivamente curto"}

    binary = "".join(f"{b:08b}" for b in raw_bytes)
    version = int(binary[0:8], 2)
    flags_byte = int(binary[8:16], 2)
    flags = [name for bit, name in FLAG_NAMES.items() if flags_byte & (1 << bit)]

    hexstr = binary_to_hex(binary[16:])
    tlv = hex_to_tlv(hexstr)

    out: Dict[str, Any] = {
        "version": version,
        "flags": flags,
        "jurisdiction_param": jurisdiction or None,
        "tlv_raw_tags": sorted(tlv.keys()),
    }

    def tag(name: str) -> Optional[str]:
        return tlv.get(TLV_TAGS[name])

    out["nonce"] = tag("NONCE")
    out["creationTime"] = hex_to_int(tag("CREATION_TS") or "")
    out["temporaryId_b64url"] = bytes_to_b64url(hex_to_bytes(tag("TEMP_ID") or ""))
    out["agentId_b64url"] = bytes_to_b64url(hex_to_bytes(tag("AGENT_ID") or ""))
    out["expiryTime"] = hex_to_int(tag("EXPIRY_TS") or "")

    guc = tag("GUC") or ""
    pos = 0

    def take(field: str) -> str:
        nonlocal pos
        size = GUC_FIELD_SIZES[field]
        s = guc[pos:pos + size]
        pos += size
        return s

    if guc:
        tos_idx = hex_to_int(take("TOS")) or 0
        out["gucToS"] = TOS_MAP[tos_idx] if tos_idx < len(TOS_MAP) else f"?{tos_idx}"
        ut_idx = hex_to_int(take("USER_TYPE")) or 0
        out["gucUserType"] = USER_TYPE_MAP[ut_idx] if ut_idx < len(USER_TYPE_MAP) else f"?{ut_idx}"
        out["gucConsentVersion"] = hex_to_int(take("CONSENT_VERSION"))
        c_idx = hex_to_int(take("CONSENTED")) or 0
        out["gucConsented"] = CONSENTED_MAP[c_idx] if c_idx < len(CONSENTED_MAP) else f"?{c_idx}"
        out["gucValidityCheckTime"] = hex_to_int("00" + take("VALIDITY_CHECK_TIME"))
        out["gucExpiryTime"] = hex_to_int("0000" + take("EXPIRY_TIME"))
        jur_idx = hex_to_int(take("JURISDICTION")) or 0
        out["gucJurisdiction_idx"] = jur_idx
        out["gucJurisdiction"] = COUNTRY_CODES[jur_idx] if jur_idx < len(COUNTRY_CODES) else f"?{jur_idx}"
        out["gucHomeLocation_woeid"] = hex_to_int(take("HOME_LOCATION"))
        mask = hex_to_int(take("CONSENT_TYPES")) or 0
        out["gucConsentTypes_mask"] = f"0x{mask:08x}"
        out["gucConsentTypes"] = [name for bit, name in GUC_CONSENT_TYPES.items() if mask & bit]

    if tag("LEGACY_BID"):
        out["bid"] = convert_hex_to_y32(tag("LEGACY_BID") or "")
        out["bid_source"] = "legacyBid (tag 07, Y32)"
    else:
        out["bid"] = get_virtual_bid(out)
        out["bid_source"] = "vbid (derivado de agentId+creationTime)"

    esid = tag("E_SID")
    out["esid_b64url"] = bytes_to_b64url(hex_to_bytes(esid or "")) if esid else None
    ns = tag("E_SID_NAMESPACE")
    if ns:
        ns_idx = hex_to_int(ns)
        out["esidNamespace"] = ESID_NAMESPACE_ENUM[ns_idx] if ns_idx is not None and ns_idx < len(ESID_NAMESPACE_ENUM) else f"?{ns_idx}"

    out["rSynthId"] = tag("R_SYNTH_ID")
    return {k: v for k, v in out.items() if v is not None}


def guce_crumb_from_parsed(a: Optional[Dict[str, Any]]) -> Optional[str]:
    """Deriva o crumb local da plataforma GUCE (agentId || temporaryId || rSynthId)."""
    if not a:
        return None
    return a.get("agentId_b64url") or a.get("temporaryId_b64url") or a.get("rSynthId") or None


def ccpa_jurisdiction(a_cookie_string: Optional[str]) -> str:
    """Detecta partição de jurisdição CCPA do cookie."""
    return "ccpa" if (a_cookie_string and "j=CCPA" in a_cookie_string) else "no-detect"


def read_a3_from_jar(path: str) -> str:
    """Lê cookie A3 de arquivo de cookies formato Netscape."""
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5] == "A3":
                return parts[6]
    return ""


# ══════════════════════ Motor de Rede HTTP Stdlib ═══════════════════════════

class HttpResponse:
    def __init__(self, status_code: int, url: str, headers: Dict[str, str], content: bytes):
        self.status_code = status_code
        self.url = url
        self.headers = headers
        self.content = content
        self._text: Optional[str] = None

    @property
    def text(self) -> str:
        if self._text is None:
            enc = "utf-8"
            ct = self.headers.get("content-type", "")
            m = re.search(r"charset=([\w-]+)", ct, re.I)
            if m:
                enc = m.group(1)
            try:
                self._text = self.content.decode(enc, errors="replace")
            except Exception:
                self._text = self.content.decode("latin-1", errors="replace")
        return self._text

    def json(self) -> Any:
        return json.loads(self.text)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Intercepta redirects HTTP 3xx sem segui-los automaticamente."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StdlibTransport:
    """Motor HTTP resiliente com emulação de browser e suporte a gzip/deflate."""
    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self._cookie_processor = urllib.request.HTTPCookieProcessor(self.cookie_jar)
        self.opener = urllib.request.build_opener(self._cookie_processor)
        self.opener_no_redirect = urllib.request.build_opener(
            self._cookie_processor,
            NoRedirectHandler
        )
        self.last_latency_ms = 0.0
        self.last_bytes = 0
        self.last_status = 0
        self.total_requisicoes = 0

    @staticmethod
    def _descomprimir(content: bytes, ce: str) -> bytes:
        if not ce or not content:
            return content
        ce = ce.lower()
        try:
            if "gzip" in ce and content[:2] == b"\x1f\x8b":
                return gzip.decompress(content)
            if "deflate" in ce:
                try:
                    return zlib.decompress(content)
                except Exception:
                    return zlib.decompress(content, -15)
        except Exception:
            pass
        return content

    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Union[bytes, str, Dict[str, Any]]] = None,
        allow_redirects: bool = True,
        timeout: Optional[float] = None
    ) -> HttpResponse:
        t0 = time.perf_counter()
        to = timeout or self.timeout
        hdrs = {
            "User-Agent": USER_AGENT_BROWSER,
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        }
        if headers:
            hdrs.update(headers)

        payload_bytes: Optional[bytes] = None
        if data is not None:
            if isinstance(data, dict):
                payload_bytes = urllib.parse.urlencode(data).encode("utf-8")
                hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif isinstance(data, str):
                payload_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                payload_bytes = data

        req = urllib.request.Request(url, data=payload_bytes, headers=hdrs, method=method.upper())
        active_opener = self.opener if allow_redirects else self.opener_no_redirect

        try:
            with active_opener.open(req, timeout=to) as resp:
                raw_bytes = resp.read()
                self.total_requisicoes += 1
                self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
                self.last_bytes = len(raw_bytes)
                self.last_status = resp.status
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                ce = resp_headers.get("content-encoding", "")
                final_content = self._descomprimir(raw_bytes, ce)
                return HttpResponse(resp.status, resp.url, resp_headers, final_content)

        except urllib.error.HTTPError as e:
            raw_bytes = e.read()
            self.total_requisicoes += 1
            self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
            self.last_bytes = len(raw_bytes)
            self.last_status = e.code
            resp_headers = {k.lower(): v for k, v in e.headers.items()}
            ce = resp_headers.get("content-encoding", "")
            final_content = self._descomprimir(raw_bytes, ce)
            return HttpResponse(e.code, e.url or url, resp_headers, final_content)

        except Exception as e:
            self.total_requisicoes += 1
            self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
            self.last_bytes = 0
            self.last_status = 0
            raise e


# ════════════════════ Cofre de Sessão (CookieVault) ═════════════════════════

class CookieVault:
    """Cofre atômico com armazenamento seguro (chmod 600) e exportação Netscape."""
    SCHEMA = "yahoo-auth-session/2"

    def __init__(self, path: str = JAR_DEFAULT):
        self.path = path
        self.cookies: Dict[str, str] = {}
        self.crumb: Optional[str] = None
        self.crumb_issued_at: Optional[float] = None
        self.history: List[Dict[str, Any]] = []

    def absorb(self, transport: StdlibTransport) -> List[str]:
        novos: List[str] = []
        for c in transport.cookie_jar:
            if c.name and c.value:
                if c.name not in self.cookies:
                    novos.append(c.name)
                self.cookies[c.name] = c.value
        return novos

    def restore_into(self, transport: StdlibTransport) -> int:
        for name, value in self.cookies.items():
            cookie = _StdCookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain=".yahoo.com", domain_specified=True, domain_initial_dot=True,
                path="/", path_specified=True, secure=True, expires=int(time.time()) + 86400 * 365,
                discard=False, comment=None, comment_url=None, rest={"HTTPOnly": ""} if name in HTTPONLY_FAMILY else {},
                rfc2109=False
            )
            transport.cookie_jar.set_cookie(cookie)
        return len(self.cookies)

    @property
    def a3(self) -> Optional[str]:
        return self.cookies.get("A3")

    @property
    def guc(self) -> Optional[str]:
        return self.cookies.get("GUC")

    def has_session(self) -> bool:
        return bool(self.a3)

    def set_crumb(self, crumb: str, origin: str) -> None:
        self.crumb = crumb
        self.crumb_issued_at = time.time()
        self.event(f"crumb:{origin}")

    def crumb_age(self) -> Optional[float]:
        if self.crumb and self.crumb_issued_at:
            return time.time() - self.crumb_issued_at
        return None

    def event(self, event_name: str) -> None:
        self.history.append({"ts": int(time.time()), "event": event_name})
        del self.history[:-100]

    def save(self) -> None:
        data = {
            "schema": self.SCHEMA,
            "saved_at": int(time.time()),
            "cookies": [{"name": n, "value": v, "domain": ".yahoo.com", "path": "/"}
                        for n, v in sorted(self.cookies.items())],
            "crumb": self.crumb,
            "crumb_issued_at": self.crumb_issued_at,
            "history": self.history[-50:],
        }
        d = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".a3c_", suffix=".json", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            try:
                os.chmod(tmp, 0o600)
            except Exception:
                pass
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def load(self) -> bool:
        if not os.path.exists(self.path):
            return False
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.cookies = {c["name"]: c["value"] for c in data.get("cookies", [])
                            if c.get("name") and c.get("value")}
            self.crumb = data.get("crumb")
            self.crumb_issued_at = data.get("crumb_issued_at")
            self.history = list(data.get("history", []))
            return bool(self.cookies)
        except Exception:
            return False

    def export_netscape(self, path: str) -> None:
        lines = ["# Netscape HTTP Cookie File", "# Yahoo Finance - Session Export"]
        for n, v in sorted(self.cookies.items()):
            pre = "#HttpOnly_" if n in HTTPONLY_FAMILY else ""
            lines.append(f"{pre}.yahoo.com\tTRUE\t/\tTRUE\t0\t{n}\t{v}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass

    def export_stdlib_cookiejar(self, path: str, horizon_days: int = 90) -> int:
        jar = _MozillaCookieJar()
        expires = int(time.time()) + max(1, int(horizon_days)) * 86400
        for n, v in sorted(self.cookies.items()):
            rest = {"HTTPOnly": ""} if n in HTTPONLY_FAMILY else {}
            jar.set_cookie(_StdCookie(
                version=0, name=n, value=v, port=None, port_specified=False,
                domain=".yahoo.com", domain_specified=True, domain_initial_dot=True,
                path="/", path_specified=True, secure=True, expires=expires,
                discard=False, comment=None, comment_url=None, rest=rest,
                rfc2109=False
            ))
        jar.save(path, ignore_discard=True, ignore_expires=True)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return len(self.cookies)


# ════════════════════ Handshake de Consentimento (GUCE) ═════════════════════

class ConsentHandshaker:
    """Implementação do fluxo de consentimento GDPR/LGPD."""
    _FORM_RE = re.compile(r"<form[^>]*\baction=[\"']([^\"']+)[\"']", re.I)
    _INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
    _ATTR_NAME_RE = re.compile(r"\bname=[\"']([^\"']+)[\"']", re.I)
    _ATTR_VALUE_RE = re.compile(r"\bvalue=[\"']([^\"']*)[\"']", re.I)

    def __init__(self, transport: StdlibTransport, vault: CookieVault):
        self.transport = transport
        self.vault = vault
        self.last_copy_status: Optional[int] = None

    def run(self) -> Dict[str, Any]:
        rel: Dict[str, Any] = {"ja_consentido": None, "form_postado": False, "guc_presente": False, "detalhe": ""}
        try:
            r = self.transport.request("GET", GUCE_CONSENT, allow_redirects=False)
            hops = 0
            while r.status_code in (301, 302, 303, 307, 308) and hops < 5:
                loc = r.headers.get("location")
                if not loc:
                    break
                url_prox = urllib.parse.urljoin(r.url, loc)
                hops += 1
                r = self.transport.request("GET", url_prox, allow_redirects=False)
        except Exception as e:
            rel["detalhe"] = f"Falha de conexão no guce: {e}"
            return rel

        self.vault.absorb(self.transport)
        if "guce.yahoo.com" not in r.url and "consent.yahoo.com" not in r.url:
            rel["ja_consentido"] = True
            rel["detalhe"] = f"Sessão já consentida após {hops} saltos (NON_EU_OATH)."
        else:
            rel["ja_consentido"] = False
            rel["detalhe"] = "Formulário de consentimento pendente."

        rel["guc_presente"] = bool(self.vault.guc)
        return rel


# ════════════════════ Resolução de Crumb Multi-Fonte ════════════════════════

class CrumbResolver:
    """Resolução em cascata: vault -> html -> endpoint -> streamer."""
    _CACHE_STREAMER: Optional[str] = None

    def __init__(self, transport: StdlibTransport, vault: CookieVault, order: Tuple[str, ...] = ("vault", "html", "endpoint")):
        self.transport = transport
        self.vault = vault
        self.order = order

    def resolve(self, force: bool = False) -> Tuple[str, str]:
        erros = []
        for nome in self.order:
            if nome == "vault" and (force or not self.vault.crumb):
                continue
            try:
                fn = getattr(self, f"_from_{nome}")
                val = fn()
                if val and val != MOCK_CRUMB and CRUMB_RE.fullmatch(val):
                    self.vault.set_crumb(val, nome)
                    return val, nome
            except Exception as e:
                erros.append(f"{nome}: {e}")
        raise RuntimeError("Crumb indisponível em todas as fontes: " + " | ".join(erros))

    def _from_vault(self) -> str:
        if self.vault.crumb:
            return self.vault.crumb
        raise ValueError("Cofre sem crumb")

    def _from_html(self) -> str:
        r = self.transport.request("GET", FINANCE_HOME)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        for pat in CRUMB_PATTERNS:
            m = re.search(pat, r.text)
            if m:
                c = m.group(1)
                if c != MOCK_CRUMB and CRUMB_RE.fullmatch(c):
                    return c
        raise ValueError("Nenhum crumb válido localizado no HTML SSR")

    def _from_endpoint(self) -> str:
        for host in QUERY_HOSTS:
            url = f"https://{host}{GETCRUMB_PATH}"
            r = self.transport.request("GET", url, headers={"Accept": "text/plain"})
            if r.status_code == 200 and r.text.strip():
                txt = r.text.strip()
                if txt != MOCK_CRUMB and CRUMB_RE.fullmatch(txt):
                    return txt
        raise RuntimeError("Falha ao emitir crumb via endpoint oficial")

    def _from_streamer(self) -> str:
        if CrumbResolver._CACHE_STREAMER:
            return CrumbResolver._CACHE_STREAMER
        host = random.choice(QUERY_HOSTS)
        url = f"https://{host}{GETCRUMB_PATH}"
        r = self.transport.request("GET", url, headers={"Content-Type": "text/plain", "Accept": "*/*"})
        if r.status_code == 200 and r.text.strip():
            txt = r.text.strip()
            if txt != MOCK_CRUMB and CRUMB_RE.fullmatch(txt):
                CrumbResolver._CACHE_STREAMER = txt
                return txt
        raise RuntimeError("Falha ao obter crumb pelo caminho do streamer")


# ════════════════════ Sessão Orquestradora Yahoo Finance ════════════════════

class YahooFinanceSession:
    """Orquestrador completo de sessão autenticada A3 + Crumb."""
    def __init__(self, jar_path: Optional[str] = None, strategy: Tuple[str, ...] = ("vault", "html", "endpoint")):
        self.transport = StdlibTransport()
        self.vault = CookieVault(jar_path or JAR_DEFAULT)
        self.vault.load()
        if self.vault.has_session():
            self.vault.restore_into(self.transport)
        self.consent = ConsentHandshaker(self.transport, self.vault)
        self.crumb_resolver = CrumbResolver(self.transport, self.vault, order=strategy)
        self._lock = threading.RLock()

    def bootstrap(self, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            info: Dict[str, Any] = {"a3_origem": "jar (reutilizado)", "consent": None, "forense": None}
            if force or not self.vault.has_session():
                r = self.transport.request("GET", FC_YAHOO, allow_redirects=False)
                self.vault.absorb(self.transport)
                self.vault.event(f"bootstrap:fc:{r.status_code}")
                info["a3_origem"] = f"fc.yahoo.com (HTTP {r.status_code}, 404 = normal)"

            if not self.vault.has_session():
                raise RuntimeError("Falha no bootstrap: Cookie A3 não foi emitido.")

            parsed = parse_acookie(self.vault.a3 or "")
            info["forense"] = parsed
            info["consent"] = self.consent.run()
            self.vault.save()
            return info

    def get_crumb(self, force: bool = False) -> str:
        with self._lock:
            return self.crumb_resolver.resolve(force=force)[0]

    def quote(self, symbols: List[str]) -> List[Dict[str, Any]]:
        crumb = self.get_crumb()
        qs = urllib.parse.urlencode({
            "symbols": ",".join(symbols),
            "crumb": crumb,
            "formatted": "true",
            "lang": "en-US",
            "region": "US"
        })
        url = f"https://{QUERY_HOSTS[0]}{QUOTE_PATH}?{qs}"
        r = self.transport.request("GET", url, headers={"Accept": "application/json"})
        if r.status_code == 200:
            self.vault.absorb(self.transport)
            return r.json().get("quoteResponse", {}).get("result", [])
        return []

    def close(self):
        self.vault.save()


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

    def tabela_cotações(self, quotes: List[Dict[str, Any]]) -> None:
        """Renderiza tabela com dados reais de cotação do teste de consumo."""
        if not quotes:
            print(f"  {self.p.pintar('[AVISO] Nenhuma cotação retornada.', 'amarelo')}")
            return

        colunas = [
            ("#", 3, "<"),
            ("SÍMBOLO", 10, "<"),
            ("PREÇO", 12, ">"),
            ("VAR", 10, ">"),
            ("VAR %", 10, ">"),
            ("MOEDA", 6, "^"),
            ("NOME", 24, "<")
        ]

        p, b = self.p, self.b
        regua_top = f" {p.c('linha')}{b.TL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.TR}{p.RST}"
        print(regua_top)

        h_celulas = [f" {pad_vis(p.pintar(nome, 'cinza_med', negrito=True), w, al)} " for nome, w, al in colunas]
        print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(h_celulas) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_mid = f" {p.c('linha')}{b.LT}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.RT}{p.RST}"
        print(regua_mid)

        for idx, q in enumerate(quotes, 1):
            sym = q.get("symbol", "—")
            nome = q.get("shortName") or q.get("longName") or "—"
            pr = q.get("regularMarketPrice", {}).get("raw") if isinstance(q.get("regularMarketPrice"), dict) else q.get("regularMarketPrice")
            ch = q.get("regularMarketChange", {}).get("raw") if isinstance(q.get("regularMarketChange"), dict) else q.get("regularMarketChange")
            chp = q.get("regularMarketChangePercent", {}).get("raw") if isinstance(q.get("regularMarketChangePercent"), dict) else q.get("regularMarketChangePercent")
            curr = q.get("currency", "USD")

            pr_str = fmt_numero_br(pr, 2)
            ch_str = fmt_numero_br(ch, 2)
            if ch is not None and float(ch) > 0:
                ch_str = f"+{ch_str}"
            chp_str = fmt_percentual_br(chp)
            cor_v = "verde" if (chp or 0) > 0 else ("vermelho" if (chp or 0) < 0 else "branco")

            linha_cel = [
                (p.pintar(str(idx), "cinza_esc"), colunas[0][1], colunas[0][2]),
                (p.pintar(sym[:9], "ambar", negrito=True), colunas[1][1], colunas[1][2]),
                (pr_str[:11], colunas[2][1], colunas[2][2]),
                (p.pintar(ch_str[:9], cor_v), colunas[3][1], colunas[3][2]),
                (p.pintar(chp_str[:9], cor_v), colunas[4][1], colunas[4][2]),
                (curr[:5], colunas[5][1], colunas[5][2]),
                (nome[:23], colunas[6][1], colunas[6][2]),
            ]

            row_fmt = [f" {pad_vis(t, w, al)} " for t, w, al in linha_cel]
            print(f" {p.c('linha')}{b.V}{p.RST}" + f"{p.c('linha')}{b.V}{p.RST}".join(row_fmt) + f"{p.c('linha')}{b.V}{p.RST}")

        regua_bot = f" {p.c('linha')}{b.BL}" + b.H.join(b.H * (w + 2) for _, w, _ in colunas) + f"{b.BR}{p.RST}"
        print(regua_bot)


# ═══════════════ Módulo 1: Suíte de Verificação ao Vivo ══════════════════════

def executar_suite_verificacao(session: YahooFinanceSession, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Executa a suíte de 20 checagens de conformidade ao vivo do protocolo A3 + Crumb."""
    print(f"\n {p.pintar('SUÍTE DE VERIFICAÇÃO AO VIVO (PROTOCOLO A3 + CRUMB)', 'azul', negrito=True)}")
    print(f"  {p.pintar('Validando regras de handshakes, envelopes, TLV e conformidade de rede...', 'cinza_esc')}\n")

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

    # 1. fc.yahoo.com responde 404 e emite Set-Cookie A3
    r_fc = session.transport.request("GET", FC_YAHOO, allow_redirects=False)
    session.vault.absorb(session.transport)
    relatar(1, "fc.yahoo.com responde HTTP 404 e emite Set-Cookie A3", r_fc.status_code == 404 and session.vault.has_session(), "Set-Cookie A3 ok")

    # 2. A3 contém partições obrigatórias d= e S=
    a3_val = session.vault.a3 or ""
    tem_particoes = "d=" in a3_val and "S=" in a3_val
    relatar(2, "Cookie A3 possui partições obrigatórias 'd=' e 'S='", tem_particoes, f"tamanho={len(a3_val)}B")

    # 3. Parser TLV decodifica versão e creationTime
    parsed = parse_acookie(a3_val)
    relatar(3, "Parser TLV extrai versão (1) e timestamp creationTime", parsed.get("version") == 1 and parsed.get("creationTime") is not None, f"ts={parsed.get('creationTime')}")

    # 4. GUC (tag 05) presente com jurisdição e ToS
    tem_guc = bool(parsed.get("gucJurisdiction") and parsed.get("gucToS"))
    relatar(4, "GUC (tag 05) decodificado com jurisdição e ToS", tem_guc, f"jurisdição={parsed.get('gucJurisdiction')}")

    # 5. ValidityCheckTime é múltiplo de 256 (invariante Little-Endian)
    val_check = parsed.get("gucValidityCheckTime", 0) or 0
    relatar(5, "Invariante LE: gucValidityCheckTime é múltiplo de 256", val_check % 256 == 0, f"check={val_check}")

    # 6. BID resolvido com sucesso
    bid = parsed.get("bid")
    relatar(6, "BID do dispositivo resolvido (Y32 legado ou Virtual BID)", bool(bid), f"bid='{bid}' ({parsed.get('bid_source')})")

    # 7. guce_crumb derivado localmente sem rede
    g_crumb = guce_crumb_from_parsed(parsed)
    relatar(7, "Crumb do GUCE derivado localmente de agentId/temporaryId", bool(g_crumb), f"guce_crumb='{g_crumb}'")

    # 8. Regra do 406: Accept application/json sozinho FALHA no getcrumb
    r_406 = session.transport.request("GET", f"https://{QUERY_HOSTS[0]}{GETCRUMB_PATH}", headers={"Accept": "application/json"})
    relatar(8, "Regra do Accept: application/json sozinho gera HTTP 406", r_406.status_code == 406, "406 Not Acceptable comprovado")

    # 9. getcrumb com Accept text/plain emite crumb com sucesso
    r_crumb = session.transport.request("GET", f"https://{QUERY_HOSTS[0]}{GETCRUMB_PATH}", headers={"Accept": "text/plain"})
    crumb_txt = r_crumb.text.strip()
    relatar(9, "getcrumb com Accept text/plain emite crumb de 11 chars", r_crumb.status_code == 200 and len(crumb_txt) == 11, f"crumb='{crumb_txt}'")

    # 10. Alfabeto e sanidade do token Crumb
    relatar(10, "Crumb atende regex de alfabeto e difere de MOCK_CRUMB", bool(CRUMB_RE.fullmatch(crumb_txt)) and crumb_txt != MOCK_CRUMB, "formato válido")

    # 11. query1 e query2 aceitam a mesma sessão e emitem crumb
    r_q2 = session.transport.request("GET", f"https://{QUERY_HOSTS[1]}{GETCRUMB_PATH}", headers={"Accept": "text/plain"})
    relatar(11, "query1 e query2 são intercambiáveis para a mesma sessão", r_q2.status_code == 200 and len(r_q2.text.strip()) == 11, "intercambialidade ok")

    # 12. Caminho próprio do streamer (Content-Type no request) operacional
    crumb_stream = session.crumb_resolver._from_streamer()
    relatar(12, "Caminho alternativo do streamer emite crumb com sucesso", bool(crumb_stream), f"streamer='{crumb_stream}'")

    # 13. Consumo de /v7/finance/quote com par A3 + Crumb responde 200
    quotes = session.quote(["AAPL"])
    relatar(13, "Consumo de /v7/finance/quote com par A3+Crumb retorna 200", len(quotes) == 1 and quotes[0].get("symbol") == "AAPL", "AAPL cotada")

    # 14. Crumb forjado/inválido resulta em HTTP 401 Unauthorized
    url_fake_crumb = f"https://{QUERY_HOSTS[0]}{QUOTE_PATH}?symbols=AAPL&crumb=FAKE_CRUMB_99"
    r_fake = session.transport.request("GET", url_fake_crumb)
    relatar(14, "Crumb forjado/inválido é rejeitado com HTTP 401", r_fake.status_code == 401, "401 rejeitado")

    # 15. User-Agent python-urllib bloqueado com HTTP 429 pela borda
    r_pyua = session.transport.request("GET", f"https://{QUERY_HOSTS[0]}{GETCRUMB_PATH}", headers={"User-Agent": "Python-urllib/3.13"})
    relatar(15, "User-Agent python-urllib bloqueado com HTTP 429", r_pyua.status_code == 429, "Too Many Requests")

    # 16. Método HEAD em getcrumb responde 200 com corpo vazio
    r_head = session.transport.request("HEAD", f"https://{QUERY_HOSTS[0]}{GETCRUMB_PATH}", headers={"Accept": "text/plain"})
    relatar(16, "Método HEAD em getcrumb retorna 200 e corpo vazio", r_head.status_code == 200 and len(r_head.content) == 0, "HEAD ok")

    # 17. Método POST em getcrumb rejeitado com 405 Method Not Allowed
    r_post = session.transport.request("POST", f"https://{QUERY_HOSTS[0]}{GETCRUMB_PATH}")
    relatar(17, "Método POST em getcrumb rejeitado com HTTP 405", r_post.status_code == 405, "405 rejeitado")

    # 18. Sem cookie no jar getcrumb rejeita com 401 Invalid Cookie
    t_limpo = StdlibTransport()
    r_sem_cookie = t_limpo.request("GET", f"https://{QUERY_HOSTS[0]}{GETCRUMB_PATH}", headers={"Accept": "text/plain"})
    relatar(18, "getcrumb sem cookie no jar rejeita com 401", r_sem_cookie.status_code == 401, "401 Invalid Cookie")

    # 19. Persistência atômica do cofre em disco
    session.vault.save()
    relatar(19, "Cofre atômico grava sessão em disco (chmod 600)", os.path.exists(session.vault.path), f"arquivo={session.vault.path}")

    # 20. Recarga de cofre e round-trip do Cookie A3 intacto
    v_recarga = CookieVault(session.vault.path)
    ok_load = v_recarga.load()
    relatar(20, "Round-trip do cofre preserva Cookie A3 e Crumb intactos", ok_load and v_recarga.a3 == session.vault.a3, "round-trip íntegro")

    taxa = (testes_passados / total_testes) * 100.0
    print(f"\n {p.pintar(f'Resultado da Suíte: {testes_passados}/{total_testes} aprovados ({taxa:.1f}% de conformidade)', 'verde' if taxa == 100 else 'amarelo', negrito=True)}\n")
    return testes_passados == total_testes


# ══════════════ Módulo 2: Auditoria Estrutural Offline ══════════════════════

def executar_auditoria_offline(caminho_arquivo: str, p: Palette, rnd: ConsoleRenderer) -> bool:
    """Valida estrutura de arquivo de cofre JSON ou cookies.txt Netscape sem rede."""
    print(f"\n {p.pintar('AUDITORIA ESTRUTURAL OFFLINE DE SESSÃO', 'ciano', negrito=True)}")
    print(f"  {p.pintar(f'Arquivo analisado: {caminho_arquivo}', 'cinza_esc')}\n")

    if not os.path.isfile(caminho_arquivo):
        print(f"  {p.pintar('[ERRO] Arquivo não localizado.', 'vermelho')}")
        return False

    invariantes: List[Tuple[str, bool]] = []
    a3_cookie = ""

    if caminho_arquivo.endswith(".json"):
        try:
            with open(caminho_arquivo, "r", encoding="utf-8") as f:
                j = json.load(f)
            invariantes.append(("1. Schema oficial 'yahoo-auth-session' presente", j.get("schema") in ("yahoo-auth-session/1", "yahoo-auth-session/2")))
            invariantes.append(("2. Timestamp 'saved_at' presente", isinstance(j.get("saved_at"), int)))
            cookies = j.get("cookies", [])
            invariantes.append(("3. Array 'cookies' presente e povoado", isinstance(cookies, list) and len(cookies) > 0))
            a3_cookie = next((c["value"] for c in cookies if c.get("name") == "A3"), "")
            invariantes.append(("4. Cookie A3 localizado no cofre", bool(a3_cookie)))
            crumb = j.get("crumb")
            invariantes.append(("5. Token Crumb presente no cofre", bool(crumb and CRUMB_RE.fullmatch(crumb))))
        except Exception as e:
            print(f"  {p.pintar(f'[ERRO] Falha ao decodificar JSON: {e}', 'vermelho')}")
            return False
    else:
        a3_cookie = read_a3_from_jar(caminho_arquivo)
        invariantes.append(("1. Arquivo de cookies Netscape legível", True))
        invariantes.append(("2. Cookie A3 localizado na lista", bool(a3_cookie)))

    if a3_cookie:
        parsed = parse_acookie(a3_cookie)
        invariantes.append(("6. Parser TLV extrai versão (1)", parsed.get("version") == 1))
        invariantes.append(("7. Timestamp de criação presente", bool(parsed.get("creationTime"))))
        invariantes.append(("8. GUC presente com ToS e jurisdição", bool(parsed.get("gucJurisdiction") and parsed.get("gucToS"))))
        invariantes.append(("9. BID resolvido com sucesso", bool(parsed.get("bid"))))

    for rotulo, cond in invariantes:
        st = p.pintar("CONFORME", "verde", negrito=True) if cond else p.pintar("VIOLAÇÃO", "vermelho", negrito=True)
        print(f"  [{st}] {rotulo}")

    aprovado = all(c for _, c in invariantes)
    print(f"\n  Status: {p.pintar('SESSÃO CERTIFICADA', 'verde') if aprovado else p.pintar('SESSÃO INVÁLIDA', 'vermelho')}\n")
    return aprovado


# ═══════════════ Módulo 3: Console de Requisições Brutas ═════════════════════

def console_requisicao_bruta(session: YahooFinanceSession, p: Palette, rnd: ConsoleRenderer) -> None:
    """Diagnóstico de rede: testa requisições manuais injetando cookies e crumb."""
    print(f"\n {p.pintar('CONSOLE DE DIAGNÓSTICO & REQUISIÇÃO BRUTA', 'ciano', negrito=True)}")
    print(f"  {p.pintar('Teste endpoints arbitrários injetando a sessão e headers reais.', 'cinza_esc')}\n")

    metodo = (input(f"  {p.pintar('Método HTTP (GET/POST/HEAD/OPTIONS) [GET]:', 'branco', negrito=True)} ").strip().upper()) or "GET"
    url = input(f"  {p.pintar('URL completa [https://query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL]:', 'branco', negrito=True)} ").strip()
    if not url:
        crumb = session.vault.crumb or "CRUMB_EXEMPLO"
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL&crumb={crumb}"

    print("\n  Injeção de Credenciais:")
    print("   [1] Injetar Cookie A3 do Cofre + Header x-crumb")
    print("   [2] Injetar Cookie A3 apenas")
    print("   [3] Requisição Anônima Pura (sem cookies do cofre)")
    opt_cred = input(f"  {p.pintar('Escolha [1]:', 'branco')} ").strip() or "1"

    hdrs = {}
    if opt_cred in ("1", "2"):
        if not session.vault.has_session():
            session.bootstrap()
    if opt_cred == "1" and session.vault.crumb:
        hdrs["x-crumb"] = session.vault.crumb

    t_exec = session.transport if opt_cred in ("1", "2") else StdlibTransport()
    print(f"\n  {p.pintar('Disparando:', 'cinza_esc')} {p.pintar(f'{metodo} {url}', 'azul')}")

    try:
        resp = t_exec.request(metodo, url, headers=hdrs)
        st_cor = "verde" if resp.status_code == 200 else "vermelho"
        print(f"  {p.pintar('Resposta:', 'cinza_esc')} {p.pintar(f'HTTP {resp.status_code}', st_cor, negrito=True)} | Latência: {t_exec.last_latency_ms:.1f}ms | Tamanho: {len(resp.content)}B\n")

        rnd.caixa(
            [f"{k}: {v}" for k, v in list(resp.headers.items())[:7]],
            titulo="CABEÇALHOS RETORNADOS",
            cor_titulo="ciano"
        )

        amostra = resp.text[:350]
        print(f"\n  {p.pintar('Corpo bruto (primeiros 350 bytes):', 'cinza_med')}")
        print(f"  {p.pintar(amostra, 'cinza_esc')}{'...' if len(resp.content) > 350 else ''}\n")
    except Exception as e:
        print(f"  {p.pintar(f'[ERRO] Falha na execução: {e}', 'vermelho')}")


# ══════════════ Módulo 4: Exibição Forense do Cookie A3 ═════════════════════

def exibir_forense_a3(raw_a3: str, p: Palette, rnd: ConsoleRenderer) -> None:
    """Exibe relatório técnico minucioso com a decodificação binária do cookie."""
    parsed = parse_acookie(raw_a3)
    if "error" in parsed:
        print(f"  {p.pintar('[ERRO] ' + parsed['error'], 'vermelho')}")
        return

    linhas = [
        f"• Versão da Estrutura : {parsed.get('version')} | Flags: {', '.join(parsed.get('flags', [])) or 'Nenhuma'}",
        f"• Tags TLV Presentes  : {', '.join(parsed.get('tlv_raw_tags', []))}",
        f"• Timestamp Criação   : {parsed.get('creationTime')} ({fmt_epoch_local(parsed.get('creationTime'))})",
        f"• Timestamp Expiração : {parsed.get('expiryTime')} ({fmt_epoch_local(parsed.get('expiryTime'))})",
        f"• Identificador Temp  : {parsed.get('temporaryId_b64url') or '—'}",
        f"• Identificador Agente: {parsed.get('agentId_b64url') or '—'}",
        f"• BID do Dispositivo  : {p.pintar(parsed.get('bid'), 'ambar', negrito=True)} ({parsed.get('bid_source')})",
        f"• Crumb Derivado GUCE : {p.pintar(guce_crumb_from_parsed(parsed) or '—', 'ciano')}",
        "",
        f"{p.pintar('ESTADO DE CONSENTIMENTO GUC (TAG 05):', 'verde', negrito=True)}",
        f"• Termos de Serviço   : {parsed.get('gucToS')} | Tipo Usuário: {parsed.get('gucUserType')}",
        f"• Estado Consentimento: {parsed.get('gucConsented')} (Versão Política: {parsed.get('gucConsentVersion')})",
        f"• Jurisdição Fiscal   : {parsed.get('gucJurisdiction')} (Índice {parsed.get('gucJurisdiction_idx')})",
        f"• Revalidação / Expira: {fmt_epoch_local(parsed.get('gucValidityCheckTime'))} / {fmt_epoch_local(parsed.get('gucExpiryTime'))}",
        f"• Localização WOEID   : {parsed.get('gucHomeLocation_woeid')}",
        f"• Máscara de Bits     : {parsed.get('gucConsentTypes_mask')} ({len(parsed.get('gucConsentTypes', []))} permissões ativas)",
    ]

    rnd.caixa(linhas, titulo="DECODIFICAÇÃO BINÁRIA TLV (COOKIE A3)", cor_titulo="ambar")

    tipos = parsed.get("gucConsentTypes", [])
    if tipos:
        print(f"  {p.pintar('Permissões de Consentimento Ativas:', 'cinza_med', negrito=True)}")
        for t in tipos:
            print(f"   ✓ {p.pintar(t, 'verde')}")
        print()


# ════════════════════ Menu Principal & CLI Dispatcher ═══════════════════════

def menu_principal(session: YahooFinanceSession, p: Palette, rnd: ConsoleRenderer) -> None:
    """Loop principal interativo anti-fechamento."""
    while True:
        try:
            print(f"\n {p.pintar('YAHOO FINANCE AUTHENTICATION EXPLORER (A3 + Crumb)', 'ambar', negrito=True)}")
            print(f"  {p.pintar('Identidade anônima, token de prova e decodificação forense TLV | stdlib pura', 'cinza_esc')}\n")

            a3_presente = session.vault.has_session()
            crumb_presente = bool(session.vault.crumb)

            print(f"  [1] Executar Ciclo Completo de Autenticação (Bootstrap A3 + Crumb)")
            print(f"  [2] Testar Cotação de Mercado ao Vivo (/v7/finance/quote com o Par)")
            print(f"  [3] Inspecionar & Decodificar Cookie A3 Atual em Memória")
            print(f"  [4] Decodificar Cookie A3 Externo (String ou Arquivo)")
            print(f"  [5] Inspecionar Cofre de Sessão (yahoo_session.json / Histórico / Taxonomia)")
            print(f"  [6] Resolução de Crumb por Fonte Isolada (Endpoint, Streamer, HTML)")
            print(f"  [7] Console de Requisições Brutas (Diagnóstico HTTP & Injeção)")
            print(f"  [8] Suíte de Verificação ao Vivo (20 Testes de Conformidade)")
            print(f"  [9] Auditoria Estrutural Offline (Validar Cofre JSON ou Netscape)")
            print(f"  [10] Exportar Sessão (Formato Netscape cookies.txt ou MozillaCookieJar)")
            print(f"  [0] Encerrar Aplicativo")

            escolha = input(f"\n  {p.pintar('Opção:', 'branco', negrito=True)} ").strip()

            if escolha == "0":
                print(f"\n  {p.pintar('Encerrando aplicação de forma limpa. Até logo!', 'ciano')}")
                break

            elif escolha == "1":
                print(f"\n  {p.pintar('Disparando handshake canônico fc.yahoo.com...', 'cinza_esc')}")
                info = session.bootstrap(force=True)
                crumb = session.get_crumb(force=True)
                print(f"  {p.pintar('[SUCESSO] Cookie A3 emitido com sucesso.', 'verde')}")
                print(f"  • Origem A3: {info.get('a3_origem')}")
                print(f"  • Crumb     : {p.pintar(crumb, 'ambar', negrito=True)} ({len(crumb)} chars)")
                exibir_forense_a3(session.vault.a3 or "", p, rnd)

            elif escolha == "2":
                simbolos_str = input(f"  {p.pintar('Informe símbolos separados por vírgula [AAPL,MSFT,PETR4.SA,BTC-USD]:', 'branco')} ").strip()
                if not simbolos_str:
                    simbolos_str = "AAPL,MSFT,PETR4.SA,BTC-USD"
                syms = [s.strip().upper() for s in simbolos_str.split(",") if s.strip()]
                print(f"  {p.pintar(f'Consultando cotações com Crumb={mascara_token(session.vault.crumb)}...', 'cinza_esc')}")
                quotes = session.quote(syms)
                rnd.tabela_cotações(quotes)

            elif escolha == "3":
                if not a3_presente:
                    print(f"  {p.pintar('Nenhum Cookie A3 carregado em memória. Execute a opção 1 primeiro.', 'amarelo')}")
                else:
                    exibir_forense_a3(session.vault.a3 or "", p, rnd)

            elif escolha == "4":
                raw_input = input(f"  {p.pintar('Cole a string do cookie A3 (ou caminho do arquivo):', 'branco')} ").strip()
                if os.path.isfile(raw_input):
                    raw_input = read_a3_from_jar(raw_input)
                if raw_input:
                    exibir_forense_a3(raw_input, p, rnd)
                else:
                    print(f"  {p.pintar('Entrada vazia.', 'amarelo')}")

            elif escolha == "5":
                linhas = [
                    f"• Caminho do Cofre: {session.vault.path}",
                    f"• Cookie A3       : {p.pintar('Presente (' + str(len(session.vault.a3 or '')) + 'B)', 'verde') if a3_presente else p.pintar('Ausente', 'vermelho')}",
                    f"• Crumb em Memória: {p.pintar(session.vault.crumb or 'Não emitido', 'ambar' if crumb_presente else 'amarelo')}",
                    f"• Idade do Crumb  : {session.vault.crumb_age():.0f} s" if session.vault.crumb_age() is not None else "• Idade do Crumb  : —",
                    f"• Total de Cookies: {len(session.vault.cookies)} cookies persistidos",
                    "",
                    f"{p.pintar('TAXONOMIA DE COOKIES DO PAINEL DE DEBUG:', 'ciano', negrito=True)}",
                ]
                for nome_c, papel in session.vault.classify_cookies().items():
                    linhas.append(f"• {pad_vis(nome_c, 8, '<')}: {papel}")
                rnd.caixa(linhas, titulo="ESTADO DO COFRE DE SESSÃO", cor_titulo="ciano")

            elif escolha == "6":
                print("\n  Escolha a fonte para emissão do crumb:")
                print("   [1] Endpoint Oficial GET /v1/test/getcrumb (Accept text/plain)")
                print("   [2] Caminho Próprio do Streamer (Content-Type no request)")
                print("   [3] Regex no HTML SSR da Homepage (user.crumb)")
                print("   [4] Crumb Derivado Local do GUCE (agentId / temporaryId)")
                opt_c = input(f"  {p.pintar('Opção [1]:', 'branco')} ").strip() or "1"
                try:
                    if opt_c == "1":
                        res = session.crumb_resolver._from_endpoint()
                        print(f"  {p.pintar(f'[OK] Crumb emitido: {res}', 'verde')}")
                    elif opt_c == "2":
                        res = session.crumb_resolver._from_streamer()
                        print(f"  {p.pintar(f'[OK] Crumb do streamer: {res}', 'verde')}")
                    elif opt_c == "3":
                        res = session.crumb_resolver._from_html()
                        print(f"  {p.pintar(f'[OK] Crumb do HTML SSR: {res}', 'verde')}")
                    elif opt_c == "4":
                        parsed = parse_acookie(session.vault.a3 or "")
                        res = guce_crumb_from_parsed(parsed)
                        print(f"  {p.pintar(f'[OK] Crumb auto-derivado GUCE: {res}', 'verde')}")
                except Exception as e:
                    print(f"  {p.pintar(f'[FALHA] {e}', 'vermelho')}")

            elif escolha == "7":
                console_requisicao_bruta(session, p, rnd)

            elif escolha == "8":
                executar_suite_verificacao(session, p, rnd)

            elif escolha == "9":
                arq = input(f"  {p.pintar('Caminho do arquivo [yahoo_session.json]:', 'branco')} ").strip() or "yahoo_session.json"
                executar_auditoria_offline(arq, p, rnd)

            elif escolha == "10":
                print("\n  Formato de exportação:")
                print("   [1] Netscape cookies.txt (padrão curl/wget com #HttpOnly_)")
                print("   [2] MozillaCookieJar Stdlib Python (com TTL normalizado)")
                opt_exp = input(f"  {p.pintar('Opção [1]:', 'branco')} ").strip() or "1"
                nome_arq = input(f"  {p.pintar('Nome do arquivo de saída [cookies.txt]:', 'branco')} ").strip() or "cookies.txt"
                if opt_exp == "1":
                    session.vault.export_netscape(nome_arq)
                    print(f"  {p.pintar(f'[SUCESSO] Exportado Netscape: {nome_arq}', 'verde')}")
                else:
                    n = session.vault.export_stdlib_cookiejar(nome_arq)
                    print(f"  {p.pintar(f'[SUCESSO] Exportados {n} cookies para {nome_arq}', 'verde')}")

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
        prog="yfinance_legacy.py",
        description="Terminal Interativo Bloomberg & Referência Completa de Autenticação Yahoo Finance (A3 + Crumb)"
    )

    parser.add_argument("--jar", default=JAR_DEFAULT, help="Caminho do cofre persistido (default: ./yahoo_session.json)")
    parser.add_argument("--symbols", default=None, help="Símbolos para cotação de teste (ex: AAPL,MSFT)")
    parser.add_argument("--strategy", default="vault,html,endpoint", help="Ordem das fontes de crumb: vault,html,endpoint,streamer")
    parser.add_argument("--fresh", action="store_true", help="Ignora cofre e refaz bootstrap completo")
    parser.add_argument("--inspect", action="store_true", help="Inspeciona cofre de sessão e encerra")
    parser.add_argument("--decode-a3", metavar="VALOR", nargs="?", const="", help="Decodifica string do cookie A3")
    parser.add_argument("--from-jar", metavar="ARQ", help="Lê o Cookie A3 de um jar Netscape e decodifica")
    parser.add_argument("--taxonomy", action="store_true", help="Exibe taxonomia dos cookies do cofre")
    parser.add_argument("--guce-crumb", action="store_true", help="Exibe crumb do guce auto-derivado")
    parser.add_argument("--streamer-crumb", action="store_true", help="Emite crumb pelo caminho do streamer")
    parser.add_argument("--to-cookiejar", metavar="ARQ", help="Exporta cofre para cookies.txt formato stdlib")
    parser.add_argument("--verifica", action="store_true", help="Executa a suíte de 20 testes de conformidade ao vivo")
    parser.add_argument("--auditar", default=None, metavar="ARQ", help="Audita estruturalmente arquivo de cofre/cookies")
    parser.add_argument("--ascii", action="store_true", help="Usa molduras ASCII simples (+---+)")
    parser.add_argument("--sem-cores", "--no-color", action="store_true", help="Desativa cores ANSI")
    parser.add_argument("--no-pause", action="store_true", help="Desativa pausa ao sair")
    parser.add_argument("-v", "--verbose", action="store_true", help="Logs detalhados de rede")

    args = parser.parse_args()

    usa_cores = not args.sem_cores and os.environ.get("NO_COLOR") is None
    p = Palette(habilitada=usa_cores)
    b = BoxChars(ascii_mode=args.ascii)
    rnd = ConsoleRenderer(p, b)

    estrategias = tuple(s.strip() for s in args.strategy.split(",") if s.strip())
    session = YahooFinanceSession(jar_path=args.jar, strategy=estrategias)

    try:
        # Modo 1: Decodificação Direta CLI de A3
        if args.decode_a3 is not None or args.from_jar:
            val = args.decode_a3
            if args.from_jar:
                val = read_a3_from_jar(args.from_jar)
            if not val:
                sys.stderr.write("Erro: Cookie A3 não informado ou não localizado no jar.\n")
                return 1
            exibir_forense_a3(val, p, rnd)
            return 0

        # Modo 2: Auditoria Offline CLI
        if args.auditar:
            return 0 if executar_auditoria_offline(args.auditar, p, rnd) else 1

        # Modo 3: Suíte de Testes ao Vivo CLI
        if args.verifica:
            session.bootstrap(force=args.fresh)
            return 0 if executar_suite_verificacao(session, p, rnd) else 1

        # Modo 4: Inspeção de Cofre CLI
        if args.inspect:
            if not session.vault.load():
                print(f"Nenhum cofre em {args.jar}. Execute a sessão primeiro.")
                return 1
            linhas = [
                f"• Caminho : {session.vault.path}",
                f"• Cookie A3: {mascara_token(session.vault.a3)}",
                f"• Crumb   : {session.vault.crumb or '—'}",
                f"• Eventos : {' · '.join(e['event'] for e in session.vault.history[-6:]) or '—'}",
            ]
            rnd.caixa(linhas, titulo="INSPEÇÃO DO COFRE", cor_titulo="ciano")
            exibir_forense_a3(session.vault.a3 or "", p, rnd)
            return 0

        # Modo 5: Taxonomia CLI
        if args.taxonomy:
            session.vault.load()
            linhas = [f"• {pad_vis(k, 8, '<')}: {v}" for k, v in session.vault.classify_cookies().items()]
            rnd.caixa(linhas, titulo="TAXONOMIA DE COOKIES", cor_titulo="ambar")
            return 0

        # Modo 6: Crumb do GUCE CLI
        if args.guce_crumb:
            session.vault.load()
            parsed = parse_acookie(session.vault.a3 or "")
            gc = guce_crumb_from_parsed(parsed)
            print(f"Crumb GUCE Derivado: {gc}")
            return 0

        # Modo 7: Streamer Crumb CLI
        if args.streamer_crumb:
            session.bootstrap(force=args.fresh)
            sc = session.crumb_resolver._from_streamer()
            print(f"Crumb do Streamer: {sc}")
            return 0

        # Modo 8: Exportação de CookieJar CLI
        if args.to_cookiejar:
            session.vault.load()
            n = session.vault.export_stdlib_cookiejar(args.to_cookiejar)
            print(f"Exportados {n} cookies para {args.to_cookiejar}")
            return 0

        # Modo 9: Consulta Rápida de Cotação CLI
        if args.symbols:
            session.bootstrap(force=args.fresh)
            syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            quotes = session.quote(syms)
            rnd.tabela_cotações(quotes)
            return 0

        # Modo 10: Menu Interativo Contínuo (Anti-Fechamento)
        menu_principal(session, p, rnd)
        return 0

    except KeyboardInterrupt:
        print(f"\n  {p.pintar('Execução cancelada.', 'amarelo')}")
        return 130
    except Exception as e:
        print(f"\n  {p.pintar(f'[ERRO CRÍTICO] {e}', 'vermelho')}")
        return 1
    finally:
        session.close()
        if not args.no_pause and sys.stdin.isatty():
            try:
                input(f"\n {p.pintar('Pressione ENTER para fechar...', 'cinza_med')}")
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())