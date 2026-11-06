#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
 yfinance_legacy.py — Yahoo Finance · Autenticação Cookie A3 + Crumb · Referência completa
═══════════════════════════════════════════════════════════════════════════════
 Arquivo único e autocontido: parser TLV do cookie A embutido, 4 fontes de
 crumb, handshake GUCE com máquina de estados, crumb do guce auto-derivado,
 taxonomia de cookies, backoff com jitter, circuit breaker,
 classificação dos 401, acesso thread-safe (RLock), pré-checagem de expiração
 do A3 e degradação sem crumb quando o getcrumb falha. Nenhum import de irmão,
 nenhum pacote obrigatório. Deploy = copiar este arquivo.

 USO:
   python3 yfinance_legacy.py                          # demo completa ao vivo
   python3 yfinance_legacy.py --symbols AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA
   python3 yfinance_legacy.py --inspect                # relatório do jar
   python3 yfinance_legacy.py --decode-a3 'd=...&S=...'  # parser embutido
   python3 yfinance_legacy.py --from-jar cookies.txt   # A3 de jar Netscape
   python3 yfinance_legacy.py --taxonomy               # taxonomia de cookies
   python3 yfinance_legacy.py --guce-crumb             # crumb auto-derivado
   python3 yfinance_legacy.py --streamer-crumb         # caminho do streamer
   python3 yfinance_legacy.py --jar outros.json          # cofre em outro caminho
   python3 yfinance_legacy.py --to-cookiejar cookies.txt  # interop stdlib
   python3 yfinance_legacy.py --fresh --strategy endpoint,streamer

 DEPENDÊNCIAS (todas opcionais — o script se auto-configura):
   python3 -m pip install curl_cffi brotli zstandard   # TLS real + encodings
"""
from __future__ import annotations

import argparse
import base64
import datetime
import gzip
import html as html_lib
import json
import logging
import os
import random
import re
import sys
import tempfile
import threading
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin
from http.cookiejar import Cookie as _StdCookie, MozillaCookieJar as _MozillaCookieJar

__version__ = "4.1.0"

# ════════════════════════════ dependências opcionais ════════════════════════
# O script degrada com graça: curl_cffi (TLS do Chrome real) → requests puro;
# brotli/zstandard ampliam o Accept-Encoding; sem eles, anunciamos menos.

try:
    from curl_cffi import requests as _cffi  # type: ignore
except Exception:
    _cffi = None

try:
    from typing import get_args
    from curl_cffi.requests import BrowserTypeLiteral  # type: ignore
    _CFFI_TARGETS = frozenset(get_args(BrowserTypeLiteral))
except Exception:
    _CFFI_TARGETS = frozenset()

try:
    import brotli as _brotli  # type: ignore
except Exception:
    _brotli = None

try:
    import zstandard as _zstd  # type: ignore
except Exception:
    _zstd = None

try:
    import requests as _requests  # type: ignore
except Exception:
    _requests = None

LOG = logging.getLogger("a3c")

# ═══════════════════════ constantes do protocolo (verificadas) ══════════════

FC_YAHOO = "https://fc.yahoo.com/"                  # 404 é o comportamento normal; vale o Set-Cookie do A3
FINANCE_HOME = "https://finance.yahoo.com/"         # HTML SSR com crumb embutido
GUCE_CONSENT = "https://guce.yahoo.com/consent"     # handshake de consentimento
JAR_DEFAULT = "yahoo_session.json"                  # cofre: relativo ao diretório de execução
CONSENT_COLLECT_DEFAULT = "https://consent.yahoo.com/v2/collectConsent"  # observado
GUCE_COPY_CONSENT = "https://guce.yahoo.com/copyConsent"  # degrau de cópia (401 sem sessão)
CONSENT_HOST_RE = re.compile(r"guce\.yahoo\.com|consent\.yahoo\.com", re.I)  # domínios do fluxo
QUERY_HOSTS = ("query1.finance.yahoo.com",          # intercambiáveis: mesma sessão →
               "query2.finance.yahoo.com")          # mesmo crumb; binding = sessão
GETCRUMB_PATH = "/v1/test/getcrumb"                 # Accept: text/plain; application/json sozinho → 406
QUOTE_PATH = "/v7/finance/quote"                    # exemplo de consumo
A3_MAX_AGE = 31557600                               # Max-Age do A3 no servidor (365,25 dias)

STREAMER_TIMEOUT = 10.0                             # timeout do fetcher do streamer

# Rotas do guce (yimg/oa/consent.js)
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

# Taxonomia do painel de debug (chunks/Debug):
# a família Yahoo é exibida apenas pelo nome; GUC com valor; PRF redigido.
COOKIE_TAXONOMY = ("T", "Y", "F", "FS", "A1", "A1S", "A3", "B", "BX", "OTH", "OTHP", "AS")
EDGE_CREDENTIALS = ("A1", "A3")                     # só A1/A3 autenticam no edge
GUC_DEBUG_WITH_VALUE = "GUC"                        # exibido com valor no painel

MOCK_CRUMB = "MOCK_CRUMB"                           # sentinel do SSR — nunca é crumb real
CRUMB_RE = re.compile(r"[A-Za-z0-9._/-]{5,64}")     # forma observada: 11 chars; alfabeto inclui "." e "/"

CRUMB_PATTERNS: Tuple[str, ...] = (
    r'"crumb"\s*:\s*"([^"]{5,64})"',   # "crumb":"..." (user.crumb do devalue)
    r"'crumb'\s*:\s*'([^']{5,64})'",   # variante de aspas simples
    r"\bcrumb=([A-Za-z0-9._/-]{5,64})",  # query strings pré-montadas no SSR
)

AUTH_FAMILY = ("A1", "A3", "A1S", "GUC", "OTHD")    # família de sessão
HTTPONLY_FAMILY = {"A1", "A3"}                      # A1S é o espelho legível por JS


# ══════════════════════════════════════════════════════════════════════════
# PARSER DO COOKIE A — EMBUTIDO (TLV → GUC → máscara → Y32/vbid)
# Invariante LE: campos multi-byte do GUC são little-endian; com os prefixos
# "00"/"0000", gucValidityCheckTime decodifica de LE(T>>8) e gucExpiryTime
# de LE(T>>16).
# ══════════════════════════════════════════════════════════════════════════

TLV_TAGS = {
    "NONCE": "00", "CREATION_TS": "01", "TEMP_ID": "02", "AGENT_ID": "03",
    "EXPIRY_TS": "04", "GUC": "05", "LEGACY_BID": "07", "E_SID": "08",
    "E_SID_NAMESPACE": "09", "E_DEMOG": "10", "R_SYNTH_ID": "11",
    "E_DEMOG_2": "12",
}

FLAG_NAMES = {0: "NO_CRYPTO_LIB", 1: "APP_POLICY"}  # bit -> nome (consent.js)

# 16 tipos no acookie.js standalone; +2 em consent.js (18) — união aqui:
GUC_CONSENT_TYPES = {
    1: "NON_EU_CONSENT",
    2: "CORE_EU_CONSENT",
    4: "OATH_AS_THIRD_PARTY",
    8: "ANALYSIS_OF_COMMUNICATIONS",
    16: "PRECISE_GEOLOCATION",
    32: "CROSS_DEVICE_MAPPING",
    64: "ACCOUNT_MATCHING",
    128: "SEARCH_HISTORY",
    256: "FIRST_PARTY_ADS",
    512: "CONTENT_PERSONALIZATION",
    1024: "IAB",
    2048: "THIRD_PARTY_CONSENT",
    4096: "ALLOW_HUMANS_TO_READ_EMAILS",
    8192: "SELL_PERSONAL_INFORMATION",
    16384: "GENERAL_ANALYSIS_CONSENT",
    32768: "THIRD_PARTY_CONTENT_EMBED",
    65536: "INSIGHTS_FROM_COMMUNICATIONS",
    131072: "THIRD_PARTY_ANALYTICS",
}

GUC_FIELD_SIZES = {  # tamanho em chars hex
    "TOS": 2, "USER_TYPE": 2, "CONSENT_VERSION": 2, "CONSENTED": 2,
    "VALIDITY_CHECK_TIME": 6, "EXPIRY_TIME": 4, "JURISDICTION": 2,
    "HOME_LOCATION": 8, "CONSENT_TYPES": 8,
}

TOS_MAP = ["EU_OATH", "NON_EU_OATH"]
USER_TYPE_MAP = ["REG", "NON_REG"]
CONSENTED_MAP = ["NOT_CONSENTED", "CONSENTED", "DECLARED_NON_EU"]
ESID_NAMESPACE_ENUM = ["AOL", "ENGADGET", "HUFFPOST", "MAPQUEST", "MOVIEFONE",
                       "PROJECTLITTLE", "TECHCRUNCH", "YAHOO"]
Y32_ALPHABET = "0123456789abcdefghijklmnopqrstuv"

COUNTRY_CODES = ["AF", "AX", "AL", "DZ", "AS", "AD", "AO", "AI", "AQ", "AG", "AR", "AM", "AW", "AU", "AZ", "BS", "BH", "BD", "BB", "BY", "BE", "BZ", "BJ", "BM", "BT", "BO", "BQ", "BA", "BW", "BV", "BR", "IO", "BN", "BF", "BI", "KH", "CM", "CA", "CV", "KY", "CF", "TD", "CL", "CN", "CX", "CC", "CO", "KM", "CG", "CD", "CK", "CR", "CI", "CU", "CW", "DJ", "DM", "EC", "EG", "SV", "GQ", "ER", "ET", "FK", "FO", "FJ", "GF", "PF", "TF", "GA", "GM", "GE", "GH", "GI", "GR", "GL", "GD", "GP", "GU", "GT", "GG", "GN", "GW", "GY", "HT", "HM", "VA", "HN", "HK", "IN", "ID", "IR", "IQ", "IM", "IL", "JM", "JP", "JE", "JO", "KZ", "KE", "KI", "KP", "KR", "KW", "KG", "LA", "LV", "LB", "LS", "LR", "LY", "MO", "MK", "MG", "MW", "MY", "MV", "ML", "MH", "MQ", "MR", "MU", "YT", "MX", "FM", "MD", "MC", "MN", "ME", "MS", "MA", "MZ", "MM", "NA", "NR", "NP", "NC", "NZ", "NI", "NE", "NG", "NU", "NF", "MP", "OM", "PK", "PW", "PS", "PA", "PG", "PY", "PE", "PH", "PN", "PR", "QA", "RE", "RU", "RW", "BL", "SH", "KN", "LC", "MF", "PM", "VC", "WS", "SM", "ST", "SA", "SN", "RS", "SC", "SL", "SG", "SX", "SB", "SO", "ZA", "GS", "SS", "LK", "SD", "SR", "SJ", "SZ", "CH", "SY", "TW", "TJ", "TZ", "TH", "TL", "TG", "TK", "TO", "TT", "TN", "TR", "TM", "TC", "TV", "UG", "UA", "AE", "GB", "UM", "UY", "UZ", "VU", "VE", "VN", "VG", "VI", "WF", "EH", "YE", "ZM", "ZW", "US", "BG", "CZ", "DK", "DE", "EE", "IE", "EL", "ES", "FR", "HR", "IT", "CY", "LT", "LU", "HU", "MT", "NL", "AT", "PL", "PT", "RO", "SI", "SK", "FI", "SE", "UK", "IS", "LI", "NO"]


def base64url_to_bytes(s: str) -> bytes:
    """base64UrlToBase64 + base64ToBytes: '-'->'+', '_'->'/', atob."""
    if not s:
        return b""
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def bytes_to_b64url(data: bytes) -> str:
    """bytes -> base64url (hexToBase64Url): '+'->'-', '/'->'_', remove '='."""
    return base64.b64encode(data).decode().replace("+", "-").replace("/", "_").rstrip("=")


def hex_to_bytes(h: str) -> bytes:
    return bytes.fromhex(h) if h else b""


def hex_be_to_hex_le(h: str) -> str:
    """hexBEToHexLE: inverte a ordem dos pares hex (2 em 2)."""
    if not h:
        return ""
    return "".join(h[i:i + 2] for i in range(len(h) - 2, -1, -2))


def hex_to_int(h: str):
    """hexToInt: parseInt(hexLE, 16) — little-endian por par de bytes."""
    if not h:
        return None
    return int(hex_be_to_hex_le(h), 16)


def binary_to_hex(binary: str) -> str:
    """binaryToHex: grupos de 4 bits -> hex maiúsculo (1 char por grupo)."""
    return "".join(f"{int(binary[i:i+4], 2):X}" for i in range(0, len(binary), 4))


def hex_to_tlv(hexstr: str) -> dict:
    """hexToTlv: Tag(2 chars) + Length(2 chars, em bytes) + Value(length*2 chars)."""
    tlv = {}
    t = hexstr
    while t:
        tag = t[:2].upper()
        t = t[2:]
        n = int(t[:2], 16) * 2  # comprimento em chars hex
        t = t[2:]
        tlv[tag] = t[:n]
        t = t[n:]
    return tlv


def convert_hex_to_y32(h: str):
    """convertHexToY32: 8 bytes BE -> 64 bits -> 13 grupos de 5 bits, alfabeto 0-9a-v."""
    b = hex_to_bytes(h)
    if len(b) != 8:
        return None
    n = int.from_bytes(b, "big")
    out = ""
    for _ in range(13):
        out = Y32_ALPHABET[n & 31] + out
        n >>= 5
    return out


def get_virtual_bid(parsed: dict):
    """getVirtualBid (fallback quando a tag 07 não existe):
    high32 = int32 LE dos últimos 4 bytes do agentId (ou temporaryId);
    low32  = creationTime; vbid = encode32((high << 32) | low)."""
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


def is_consent_check_required(brand_type: str, a_cookie_value: dict, url: str = "",
                              now_s=None, shipped_quirk: bool = True) -> bool:
    """Porta do gate GDPR inline (yimg/oa/consent.js).

    Decide se o fluxo de consentimento (guce) precisa rodar antes do uso.
    ⚠️ Quirk shippado: o gate lê o campo `gucExpiry`, que o builder do
    aCookieValue nunca produz (ele gera `gucExpiryTime` e `expiryTime`) —
    `!i.gucExpiry` é sempre verdadeiro e o braço de vencimento é código morto.
      shipped_quirk=True  → lê `gucExpiry`   (semântica shippada)
      shipped_quirk=False → lê `gucExpiryTime` (semântica "pretensa")
    """
    if now_s is None:
        now_s = int(time.time())
    i = a_cookie_value or {}
    if len(i) < 1:                                   # cookie vazio/ilegível
        return True
    expiry = i.get("gucExpiry") if shipped_quirk else i.get("gucExpiryTime")
    tos = i.get("gucToS")
    ver = i.get("gucConsentVersion")
    expired = isinstance(expiry, (int, float)) and expiry < now_s
    # JS: undefined < o → False; !undefined → true; !0 → true
    sem_flag_e_sem_expiry = (not i.get("APP_POLICY_FLAG")) and (not expiry)
    publico = tos == "EU_OATH" or (i.get("gucUserType") == "NON_REG"
                                   and brand_type in ("eu", "EU", "qc", "QC"))
    janela = expired or (not ver) or (isinstance(ver, (int, float)) and ver < 8)
    guard_search = "search.yahoo" in (url or "")     # f(): guard de propriedade
    regras_tos = (tos == "NON_EU_OATH"
                  or (tos == "EU_OATH" and isinstance(ver, (int, float)) and ver < 2)
                  or (tos == "EU_OATH" and ver == 3)
                  or (isinstance(ver, (int, float)) and ver < 5
                      and i.get("gucJurisdiction") == "FR"))
    return bool(sem_flag_e_sem_expiry and publico and janela
                and guard_search and regras_tos)


def parse_acookie(raw: str) -> dict:
    """Pipeline integral: partições → base64url → bits → cabeçalho →
    TLV → GUC → máscara de 18 → Y32/vbid."""
    # 1) Partições d= / j=
    data, jurisdiction = "", ""
    for part in raw.split("&"):
        if part.startswith("d="):
            data = part[2:]
        elif part.startswith("j="):
            jurisdiction = part[2:]
    if not data:
        return {"error": "sem partição d="}

    # 2) base64url -> bytes -> binário
    raw_bytes = base64url_to_bytes(data)
    binary = "".join(f"{b:08b}" for b in raw_bytes)

    # 3) Cabeçalho: byte 0 = versão, byte 1 = flags
    version = int(binary[0:8], 2)
    flags_byte = int(binary[8:16], 2)
    flags = [name for bit, name in FLAG_NAMES.items() if flags_byte & (1 << bit)]

    # 4) TLV
    hexstr = binary_to_hex(binary[16:])
    tlv = hex_to_tlv(hexstr)

    out = {
        "version": version,
        "flags": flags,
        "jurisdiction_param": jurisdiction or None,
        "tlv_raw_tags": sorted(tlv.keys()),
    }

    # 5) Campos TLV decodificados
    def tag(name):
        return tlv.get(TLV_TAGS[name])

    out["nonce"] = tag("NONCE")
    out["creationTime"] = hex_to_int(tag("CREATION_TS") or "")
    out["temporaryId_b64url"] = bytes_to_b64url(hex_to_bytes(tag("TEMP_ID") or ""))
    out["agentId_b64url"] = bytes_to_b64url(hex_to_bytes(tag("AGENT_ID") or ""))
    out["expiryTime"] = hex_to_int(tag("EXPIRY_TS") or "")

    # 6) Payload GUC (tag 05) — fatias de chars hex
    guc = tag("GUC") or ""
    pos = 0

    def take(field):
        nonlocal pos
        size = GUC_FIELD_SIZES[field]
        s = guc[pos:pos + size]
        pos += size
        return s

    if guc:
        out["gucToS"] = TOS_MAP[hex_to_int(take("TOS")) or 0]
        out["gucUserType"] = USER_TYPE_MAP[hex_to_int(take("USER_TYPE")) or 0]
        out["gucConsentVersion"] = hex_to_int(take("CONSENT_VERSION"))
        out["gucConsented"] = CONSENTED_MAP[hex_to_int(take("CONSENTED")) or 0]
        out["gucValidityCheckTime"] = hex_to_int("00" + take("VALIDITY_CHECK_TIME"))
        out["gucExpiryTime"] = hex_to_int("0000" + take("EXPIRY_TIME"))
        jur_idx = hex_to_int(take("JURISDICTION")) or 0
        out["gucJurisdiction_idx"] = jur_idx
        out["gucJurisdiction"] = (COUNTRY_CODES[jur_idx]
                                  if jur_idx < len(COUNTRY_CODES) else f"?{jur_idx}")
        out["gucHomeLocation_woeid"] = hex_to_int(take("HOME_LOCATION"))
        mask = hex_to_int(take("CONSENT_TYPES")) or 0
        out["gucConsentTypes_mask"] = f"0x{mask:08x}"
        out["gucConsentTypes"] = [name for bit, name in GUC_CONSENT_TYPES.items()
                                  if mask & bit]

    # 7) BID: tag 07 (Y32) ou virtual bid
    if tag("LEGACY_BID"):
        out["bid"] = convert_hex_to_y32(tag("LEGACY_BID"))
        out["bid_source"] = "legacyBid (tag 07, Y32)"
    else:
        out["bid"] = get_virtual_bid(out)
        out["bid_source"] = "vbid (derivado de agentId+creationTime)"

    # 8) Campos restantes
    esid = tag("E_SID")
    out["esid_b64url"] = bytes_to_b64url(hex_to_bytes(esid)) if esid else None
    ns = tag("E_SID_NAMESPACE")
    if ns:
        ns_idx = hex_to_int(ns)
        out["esidNamespace"] = (ESID_NAMESPACE_ENUM[ns_idx]
                                if ns_idx is not None and ns_idx < len(ESID_NAMESPACE_ENUM)
                                else f"?{ns_idx}")
    else:
        out["esidNamespace"] = None
    out["edemog_presente"] = bool(tag("E_DEMOG"))
    out["edemog2_presente"] = bool(tag("E_DEMOG_2"))
    out["rSynthId"] = tag("R_SYNTH_ID")

    # limpeza (como no ACookie.parse: remove undefined)
    return {k: v for k, v in out.items() if v is not None}


def read_a3_from_jar(path: str) -> str:
    """jar Netscape — curl marca cookies HttpOnly com prefixo '#HttpOnly_'."""
    with open(path, encoding="utf-8") as f:
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


# ═════════════════════ crumb do guce + CCPA (auto-derivados) ════════

def guce_crumb_from_parsed(a: Optional[dict]) -> Optional[str]:
    """O 'crumb' do consentimento é AUTO-DERIVADO do cookie A parseado
    (lido do A1S, o espelho sem HttpOnly), não emitido por servidor:

        function A(e) {
          var n = e.ACookie.aCookieValue.agentId;      // tag 03 do TLV
          var t = e.ACookie.aCookieValue.temporaryId;  // tag 02 do TLV
          var o = e.ACookie.aCookieValue.rSynthId;     // tag 11 do TLV
          return n || t || o;                          // preferência nesta ordem
        }

    Aqui devolvemos o identificador na forma b64url — exatamente como o
    parser do bundle o expõe para a query `?crumb=…` das chamadas do guce.
    """
    if not a:
        return None
    return (a.get("agentId_b64url") or a.get("temporaryId_b64url")
            or a.get("rSynthId") or None)


def ccpa_jurisdiction(a_cookie_string: Optional[str]) -> str:
    """Detecção de CCPA por substring na string do cookie A:
        i.ACookieString.includes("j=CCPA") ? "ccpa" : "no-detect"
    A partição `j=` carrega a jurisdição legal."""
    return "ccpa" if (a_cookie_string and "j=CCPA" in a_cookie_string) else "no-detect"


# ═════════════════════ perfil do navegador ════════════════════════

@dataclass(frozen=True)
class ChromeProfile:
    """Fingerprint de APLICAÇÃO do Chrome 133 · Windows 10/11.

    Nota de fidelidade: a string GREASE do sec-ch-ua rotaciona por versão do
    Chrome (a 152 usa "Not?A_Brand";v="24", capturada em DevTools real; a 133
    usa "Not(A:Brand";v="99"). Quando o curl_cffi está ativo, o fingerprint
    TLS (ClientHello/HTTP-2) vem da própria biblioteca — esta classe cobre a
    camada de headers.
    """
    major: int = 133
    user_agent: str = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")
    sec_ch_ua: str = '"Chromium";v="133", "Not(A:Brand";v="99", "Google Chrome";v="133"'
    sec_ch_ua_mobile: str = "?0"
    sec_ch_ua_platform: str = '"Windows"'
    accept_html: str = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/avif,image/webp,image/apng,*/*;q=0.8,"
                        "application/signed-exchange;v=b3;q=0.7")
    accept_language: str = "pt-BR,pt;q=0.9,en-US;q=0.8"

    def hints(self) -> Dict[str, str]:
        """Client Hints de baixa entropia — o Chrome envia em TODO request."""
        return {
            "sec-ch-ua": self.sec_ch_ua,
            "sec-ch-ua-mobile": self.sec_ch_ua_mobile,
            "sec-ch-ua-platform": self.sec_ch_ua_platform,
        }

    def navigate_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        """Headers de um GET de navegação (documento) — ordem do DevTools."""
        h: Dict[str, str] = {}
        h.update(self.hints())
        h["Upgrade-Insecure-Requests"] = "1"
        h["User-Agent"] = self.user_agent
        h["Accept"] = self.accept_html
        h["Sec-Fetch-Site"] = "same-origin" if referer else "none"
        h["Sec-Fetch-Mode"] = "navigate"
        h["Sec-Fetch-User"] = "?1"
        h["Sec-Fetch-Dest"] = "document"
        if referer:
            h["Referer"] = referer
        h["Accept-Language"] = self.accept_language
        return h

    def api_headers(self, accept: str = "*/*", referer: str = FINANCE_HOME,
                    origin: Optional[str] = None) -> Dict[str, str]:
        """Headers de um XHR/fetch same-site para as APIs query1/query2."""
        h: Dict[str, str] = {}
        h["User-Agent"] = self.user_agent
        h["Accept"] = accept
        h["Accept-Language"] = self.accept_language
        h.update(self.hints())
        if origin:
            h["Origin"] = origin            # mutações cross-origin no mesmo site
        if referer:
            h["Referer"] = referer
        h["Sec-Fetch-Site"] = "same-site"   # finance.yahoo.com → query1/query2
        h["Sec-Fetch-Mode"] = "cors"
        h["Sec-Fetch-Dest"] = "empty"
        h["Priority"] = "u=1, i"
        return h

# ═════════════════════ resposta normalizada + transporte ══════════

@dataclass
class HttpResponse:
    """Resposta HTTP normalizada — independente do backend (cffi/requests)."""
    status_code: int
    url: str
    headers: Dict[str, str]          # chaves em minúsculas
    content: bytes
    _text: Optional[str] = field(default=None, repr=False)

    @property
    def text(self) -> str:
        if self._text is None:
            enc = None
            m = re.search(r"charset=([\w-]+)", self.headers.get("content-type", ""), re.I)
            if m:
                enc = m.group(1)
            for e in (enc, "utf-8"):
                if not e:
                    continue
                try:
                    self._text = self.content.decode(e)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if self._text is None:
                self._text = self.content.decode("latin-1")  # nunca falha
        return self._text

    def json(self) -> Any:
        return json.loads(self.text)


class Transport:
    """Camada de transporte: emulação Chrome 133 + decodificação transparente.

    Backends, em ordem de preferência: curl_cffi com impersonate do Chrome 133
    (fingerprint TLS real — ClientHello, ALPN h2, ordem de cifras) e, na
    ausência dele, requests puro (o bloqueio TLS no edge é condicional,
    não muro fixo).
    """

    def __init__(self, profile: ChromeProfile, prefer_cffi: bool = True):
        self.profile = profile
        self._sess = None
        self._cffi_target: Optional[str] = None
        self.backend_name = "requests"
        if prefer_cffi and _cffi is not None:
            for target in self._candidate_targets():
                try:
                    self._sess = _cffi.Session(impersonate=target)
                    self._cffi_target = target
                    self.backend_name = f"curl_cffi({target})"
                    break
                except Exception as e:                       # alvo inexistente nesta versão
                    LOG.debug("curl_cffi: alvo %s indisponível (%s)", target, e)
        if self._sess is None:
            if _requests is None:
                raise RuntimeError("nem curl_cffi nem requests estão instalados")
            self._sess = _requests.Session()
        self.accept_encoding = self._compute_accept_encoding()

    @staticmethod
    def _candidate_targets() -> List[str]:
        """Chrome 133 primeiro (exato → variante 'a' → mais próximos → alias)."""
        prefs = ["chrome133", "chrome133a", "chrome131", "chrome", "chrome124",
                 "chrome120", "chrome116"]
        if _CFFI_TARGETS:                                    # introspecção da lib
            return [t for t in prefs if t in _CFFI_TARGETS]
        return prefs                                         # tenta na ordem

    def _compute_accept_encoding(self) -> str:
        """Anuncia apenas o que sabemos decodificar.

        gzip/deflate: nativos em ambos os backends. brotli: nativo no curl_cffi
        e no urllib3 quando o pacote `brotli` existe. zstd: garantido pela
        camada manual via magic bytes (zstandard presente).
        """
        encs = ["gzip", "deflate"]
        if self.using_cffi or _brotli is not None:
            encs.append("br")
        if _zstd is not None:
            encs.append("zstd")
        return ", ".join(encs)

    @property
    def using_cffi(self) -> bool:
        return self._cffi_target is not None

    @property
    def session(self):
        """Sessão bruta do backend (para absorver/restaurar cookies)."""
        return self._sess

    # ── decodificação manual de defesa (por magic bytes + Content-Encoding) ──
    @staticmethod
    def _transparent_decode(content: bytes, ce: str) -> bytes:
        """Se a lib não descomprimiu (raro), descomprimimos manualmente.

        Heurística segura: só age quando o magic byte casa com o encoding
        declarado — conteúdo já plano (JSON/HTML começa com '{' ou '<') nunca
        casa, e qualquer exceção preserva o conteúdo original.
        """
        if not ce or not content:
            return content
        try:
            if "gzip" in ce and content[:2] == b"\x1f\x8b":
                return gzip.decompress(content)
            if "deflate" in ce and content[:1] == b"\x78":
                try:
                    return zlib.decompress(content)          # wrapper zlib
                except zlib.error:
                    return zlib.decompress(content, -15)     # deflate raw
            if "br" in ce and _brotli is not None:
                return _brotli.decompress(content)           # sem magic: tenta
            if "zstd" in ce and _zstd is not None and content[:4] == b"\x28\xb5\x2f\xfd":
                return _zstd.ZstdDecompressor().decompress(content)
        except Exception:
            pass                                             # já plano — mantém
        return content

    def request(self, method: str, url: str, *, headers: Dict[str, str],
                params: Optional[Dict[str, Any]] = None,
                data: Optional[Union[Dict[str, Any], List[Tuple[str, str]],
                                       str, bytes]] = None,
                allow_redirects: bool = True, timeout: float = 15.0) -> HttpResponse:
        """Executa a requisição e devolve HttpResponse com decode garantido."""
        h = dict(headers)
        h.setdefault("Accept-Encoding", self.accept_encoding)
        raw = self._sess.request(method.upper(), url, params=params, data=data,
                                 headers=h, allow_redirects=allow_redirects,
                                 timeout=timeout)
        ce = (raw.headers.get("content-encoding") or "").lower()
        content = self._transparent_decode(raw.content or b"", ce)
        hd = {str(k).lower(): str(v) for k, v in raw.headers.items()}
        return HttpResponse(status_code=raw.status_code, url=str(raw.url or url),
                            headers=hd, content=content)


def _jar_snapshot(session) -> Dict[str, str]:
    """Fotografa o jar do backend em {nome: valor} — compatível com ambos."""
    try:
        d = session.cookies.get_dict()
        if isinstance(d, dict):
            return {str(k): str(v) for k, v in d.items() if v}
    except Exception:
        pass
    out: Dict[str, str] = {}
    try:
        for c in session.cookies:
            try:
                out[str(c.name)] = str(c.value)
            except Exception:
                pass
    except Exception:
        pass
    return out


# ═════════════════════ cofre de cookies ════════════════════════════════

class CookieVault:
    """Gestão e persistência da família de sessão (A1/A3/A1S) + GUC.

    O par (cookies, crumb) é atômico: salvar/restaurar sempre junto.
    Persistência atômica: escreve em tmp + os.replace (nunca meio-arquivo),
    chmod 600 (contém credenciais de sessão).

    Higiene do jar mínimo: só a família A autentica (A1S sozinho →
    401); o jar mínimo funcional é "Cookie: A3=<valor>" — analytics
    (gpp, AWSALBTG* = stickiness de ALB) e consentimento alheios nunca são
    exigidos pelo esquema.
    """

    SCHEMA = "yahoo-auth-session/2"

    def __init__(self, path: str):
        self.path = path
        self.cookies: Dict[str, str] = {}
        self.crumb: Optional[str] = None
        self.crumb_issued_at: Optional[float] = None
        self.history: List[Dict[str, Any]] = []

    # ── jar do backend ↔ cofre ──────────────────────────────────────────
    def absorb(self, session) -> List[str]:
        """Integra cookies do jar do transporte; devolve os nomes NOVOS."""
        snap = _jar_snapshot(session)
        novos = [n for n, v in snap.items() if v and n not in self.cookies]
        self.cookies.update({n: v for n, v in snap.items() if v})
        return novos

    def restore_into(self, session) -> int:
        """Reinjeta o cofre no jar do transporte (domínio .yahoo.com)."""
        for name, value in self.cookies.items():
            try:
                session.cookies.set(name, value, domain=".yahoo.com", path="/")
            except TypeError:
                session.cookies.set(name, value)
        return len(self.cookies)

    # ── accessors ───────────────────────────────────────────────────────
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

    def event(self, event: str) -> None:
        self.history.append({"ts": int(time.time()), "event": event})
        del self.history[:-100]                              # cap forense

    # ── taxonomia (painel de debug) ────────────────────────
    def classify_cookies(self) -> Dict[str, str]:
        """Classifica os cookies do cofre segundo a taxonomia do painel de
        debug (chunks/Debug): família Yahoo exibida só pelo
        nome (A1/A3 são as únicas credenciais aceitas pelo edge), GUC com
        valor, demais = fora do esquema de auth (analytics/stickiness).

        Devolve {nome: papel} para os cookies PRESENTES no cofre.
        """
        papel: Dict[str, str] = {}
        for name in self.cookies:
            if name in EDGE_CREDENTIALS:
                papel[name] = "credencial-edge (família Yahoo — só o nome no painel)"
            elif name in COOKIE_TAXONOMY:
                papel[name] = "família Yahoo — sem papel de credencial no edge"
            elif name == GUC_DEBUG_WITH_VALUE:
                papel[name] = "consentimento — exibido COM valor no painel"
            else:
                papel[name] = "fora do esquema de auth (analytics/stickiness — nunca exigido)"
        return papel

    # ── persistência ────────────────────────────────────────────────────
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
            os.chmod(tmp, 0o600)                             # credencial em disco
            os.replace(tmp, self.path)                       # atômico
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def load(self) -> bool:
        if not os.path.exists(self.path):
            return False
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            LOG.warning("jar ilegível (%s) — começando do zero", e)
            return False
        if data.get("schema") != self.SCHEMA:
            LOG.warning("jar com schema desconhecido — tentando importar mesmo assim")
        self.cookies = {c["name"]: c["value"] for c in data.get("cookies", [])
                        if c.get("name") and c.get("value")}
        self.crumb = data.get("crumb")
        self.crumb_issued_at = data.get("crumb_issued_at")
        self.history = list(data.get("history", []))
        return bool(self.cookies)

    def export_netscape(self, path: str) -> None:
        """Exportação no formato Netscape — HttpOnly com prefixo #HttpOnly_.

        Convenção curl: expires=0 = cookie de sessão. Consumidores do
        stdlib http.cookiejar devem usar export_stdlib_cookiejar().
        """
        lines = ["# Netscape HTTP Cookie File",
                 "# gerado por yfinance_legacy.py — família A + GUC"]
        for n, v in sorted(self.cookies.items()):
            pre = "#HttpOnly_" if n in HTTPONLY_FAMILY else ""
            # expires=0 → cookie de sessão (o TTL real do A3 é ~1 ano no servidor)
            lines.append(f"{pre}.yahoo.com\tTRUE\t/\tTRUE\t0\t{n}\t{v}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)                                # contém credenciais

    def export_stdlib_cookiejar(self, path: str, horizon_days: int = 90) -> int:
        """Exporta cookies.txt consumível pelo http.cookiejar.MozillaCookieJar
        do stdlib com flags de load padrão.

        Normalização no produtor: todo cookie sai com expiração real
        (agora + horizon_days) — expires=0 da convenção curl faz o load()
        do stdlib devolver jar vazio. O flag HttpOnly é registrado como
        atributo nonstandard "HTTPOnly". O TTL é artefato de
        compatibilidade: a autoridade de expiração é o servidor
        (A3 Max-Age ≈ 1 ano). Para a convenção curl, use export_netscape().
        """
        jar = _MozillaCookieJar()
        expires = int(time.time()) + max(1, int(horizon_days)) * 86400
        for n, v in sorted(self.cookies.items()):
            rest = {"HTTPOnly": ""} if n in HTTPONLY_FAMILY else {}
            jar.set_cookie(_StdCookie(
                version=0, name=n, value=v, port=None, port_specified=False,
                domain=".yahoo.com", domain_specified=True, domain_initial_dot=True,
                path="/", path_specified=True, secure=True, expires=expires,
                discard=False, comment=None, comment_url=None, rest=rest,
                rfc2109=False))
        d = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(d, exist_ok=True)
        jar.save(path, ignore_discard=True, ignore_expires=True)
        os.chmod(path, 0o600)                                # contém credenciais
        return len(self.cookies)


# ═════════════════════ forense do A3 (parser embutido) ══════════════

class A3Forensics:
    """Decodificação e avaliação do cookie A — usa o parser embutido;
    nenhuma dependência externa a este arquivo."""

    def __init__(self):
        self.ref = sys.modules[__name__]     # as funções vivem aqui mesmo

    def decode(self, a3_value: Optional[str]) -> Optional[dict]:
        if not a3_value:
            return None
        try:
            return parse_acookie(a3_value)
        except Exception as e:
            LOG.debug("falha ao decodificar A3: %s", e)
            return None

    def guce_crumb(self, a3_value: Optional[str]) -> Optional[str]:
        """Crumb do guce auto-derivado do A3 (agentId||temporaryId||rSynthId)."""
        return guce_crumb_from_parsed(self.decode(a3_value))

    def consent_check_required(self, a: dict, brand_type: str = "us",
                               property_url: str = "https://finance.yahoo.com/") -> Tuple[bool, str]:
        """Porta do isConsentCheckRequired (yimg/oa/consent.js). Estrutura lógica:

            return cookie_vazio
                || !( APP_POLICY_FLAG || gucExpiry || !sujeitoEU
                      || consentimentoFresco || !emSearch )
                   && ( NON_EU_OATH || regrasEU(versão/jurisdição) )

        onde sujeitoEU = ToS EU_OATH, ou NON_REG em marca eu/qc;
        consentimentoFresco = !(gucExpiry < agora || !versão || versão < 8);
        emSearch = location.href.includes("search.yahoo") — guard de
        propriedade: fora do search, o disjuntor interno
        fica sempre verdadeiro e o gate NUNCA exige consentimento (exceto
        cookie ilegível). brand_type entra na forma do config.brandType
        original ("eu"/"EU"/"qc"/"QC" gateiam).
        """
        if not a:
            return True, "cookie A ilegível/ausente (aCookieValue vazio)"
        if not a.get("gucToS") and not a.get("tlv_raw_tags"):
            return True, "GUC ilegível/ausente no payload do A3"
        now = int(time.time())
        tos = a.get("gucToS") or ""
        utype = a.get("gucUserType") or ""
        ver = a.get("gucConsentVersion") or 0
        exp = a.get("gucExpiryTime")          # None = ausente (semântica do JS)
        app_policy = "APP_POLICY" in (a.get("flags") or [])
        brand = brand_type  # como no JS: a lista contém "eu","EU","qc","QC"
        em_search = "search.yahoo" in (property_url or "")

        sujeito_eu = (tos == "EU_OATH") or (utype == "NON_REG" and brand in ("eu", "EU", "qc", "QC"))
        # gucExpiry < agora com expiry ausente é false no JS (undefined < n)
        vencido = (exp is not None and exp < now) or ver == 0 or ver < 8
        disjuntor = app_policy or bool(exp) or (not sujeito_eu) or (not vencido) or (not em_search)
        regras_eu = ((tos == "EU_OATH" and ver < 2)
                     or (tos == "EU_OATH" and ver == 3)
                     or (ver < 5 and (a.get("gucJurisdiction") or "") == "FR"))
        if disjuntor:
            return False, ("gate inerte nesta propriedade/estado (guard search.yahoo "
                           "ou consentimento vigente) — fluxo curto")
        if tos == "NON_EU_OATH":
            return True, "gating GDPR ativo: ToS NON_EU_OATH sob gating de propriedade"
        if regras_eu:
            return True, (f"gating GDPR ativo: regras EU (ToS={tos}, versão={ver}, "
                          f"jurisdição={a.get('gucJurisdiction')}")
        return False, "consentimento vigente no GUC"

    def expiry_estimate(self, a: dict) -> Optional[int]:
        """Expiração estimada do A3 (epoch): `expiryTime` (tag 04) quando
        presente; senão creationTime + A3_MAX_AGE (Max-Age do servidor)."""
        if not a:
            return None
        if a.get("expiryTime"):
            return int(a["expiryTime"])
        ct = a.get("creationTime")
        return int(ct) + A3_MAX_AGE if ct else None

    def summarize(self, a: dict) -> List[str]:
        ct = a.get("creationTime")
        criado = (datetime.datetime.fromtimestamp(ct, tz=datetime.timezone.utc)
                  .strftime("%Y-%m-%d %H:%M:%S UTC") if ct else "?")
        exp = a.get("gucExpiryTime")
        expira = (datetime.datetime.fromtimestamp(exp, tz=datetime.timezone.utc)
                  .strftime("%Y-%m-%d") if exp else "?")
        tipos = a.get("gucConsentTypes") or []
        return [
            f"versão={a.get('version')} · flags={a.get('flags') or 'nenhuma'} · "
            f"tags TLV={', '.join(a.get('tlv_raw_tags', []))}",
            f"criado em {criado} · GUC expira {expira} · jurisdição={a.get('gucJurisdiction')}",
            f"ToS={a.get('gucToS')} · userType={a.get('gucUserType')} · "
            f"consentido={a.get('gucConsented')} (v{a.get('gucConsentVersion')})",
            f"máscara={a.get('gucConsentTypes_mask')} · {len(tipos)} consentimentos ativos",
            f"bid={a.get('bid')} ({a.get('bid_source', '?')}) · "
            f"temporaryId={'sim' if a.get('temporaryId_b64url') else 'não'} · "
            f"agentId={'sim' if a.get('agentId_b64url') else 'não'}",
        ]


# ═════════════════════ resiliência ═════════════════════════════════════

class ExponentialBackoff:
    """Backoff exponencial com jitter.

    attempt 0→~0.75s · 1→~1.5s · 2→~3s · 3→~6s · 4→~12s · 5→~24s · 6+→cap 60s
    (jitter uniforme em [0.5·teto, teto] — evita re-sincronização de clientes).
    """

    def __init__(self, base: float = 0.75, cap: float = 60.0):
        self.base = base
        self.cap = cap

    def delay(self, attempt: int) -> float:
        ceiling = min(self.cap, self.base * (2 ** max(0, attempt)))
        return random.uniform(0.5 * ceiling, ceiling)


class CircuitBreaker:
    """Circuit breaker por host: CLOSED → OPEN → HALF_OPEN.

    Após `threshold` falhas consecutivas o host "abre" por `recovery_s`
    segundos; em seguida entra em half-open e aceita uma sondagem.
    """

    def __init__(self, threshold: int = 5, recovery_s: float = 60.0):
        self.threshold = threshold
        self.recovery_s = recovery_s
        self._fails: Dict[str, int] = {}
        self._opened_at: Dict[str, float] = {}

    def state(self, host: str) -> str:
        opened = self._opened_at.get(host)
        if opened is None:
            return "closed"
        return "half-open" if time.time() - opened >= self.recovery_s else "open"

    def allow(self, host: str) -> bool:
        return self.state(host) != "open"

    def record_success(self, host: str) -> None:
        self._fails.pop(host, None)
        self._opened_at.pop(host, None)

    def record_failure(self, host: str) -> None:
        self._fails[host] = self._fails.get(host, 0) + 1
        estado_antes = self.state(host)
        if self._fails[host] >= self.threshold:
            # primeira abertura OU sondagem half-open que falhou de novo:
            # reabre por mais um ciclo de recovery
            if estado_antes != "open":
                self._opened_at[host] = time.time()

    def next_recovery(self, hosts: Optional[List[str]] = None) -> float:
        """Instante (epoch) em que o primeiro host aberto reabre."""
        hosts = list(hosts or self._opened_at)
        if not hosts:
            return 0.0
        return min(self._opened_at.get(h, 0.0) + self.recovery_s for h in hosts)


# ═════════════════════ handshake de consentimento (GUCE) ═════════════════

class ConsentHandshaker:
    """Handshake GUCE / Oath — GDPR / LGPD.

    Caminho típico (jurisdições NON_EU_OATH — o caso do Brasil):
      GET guce.yahoo.com/consent?src=finance → 302 + Set-Cookie GUC
      (s=...&g=...) + re-emissão de A1/A3/A1S (Max-Age 365 dias)
      + OTHD=EMPTY já expirado.

    Caminho completo (quando há página de consentimento — típico EU):
      parse do <form> da página → POST do "agree" em
      consent.yahoo.com/v2/collectConsent → degrau de cópia
      (guce.yahoo.com/copyConsent) → re-checagem. Implementado de forma
      defensiva (form genérico via regex + redirects manuais); o payload e o
      degrau de cópia seguem o cliente de comunidade.
    """

    _FORM_RE = re.compile(r"<form[^>]*\baction=[\"']([^\"']+)[\"']", re.I)
    _INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)          # a tag inteira
    _ATTR_NAME_RE = re.compile(r"\bname=[\"']([^\"']+)[\"']", re.I)
    _ATTR_VALUE_RE = re.compile(r"\bvalue=[\"']([^\"']*)[\"']", re.I)

    def __init__(self, transport: Transport, vault: CookieVault, profile: ChromeProfile):
        self.transport = transport
        self.vault = vault
        self.profile = profile
        self.last_copy_status: Optional[int] = None

    # ── navegação com redirects MANUAIS (absorve cookies de cada salto,
    #    sem baixar o destino final quando ele é a homepage inteira) ──────
    def _follow(self, url: str, *, params: Optional[Dict[str, Any]] = None,
                max_hops: int = 6) -> Tuple[HttpResponse, int]:
        hops = 0
        r = self.transport.request("GET", url, params=params,
                                   headers=self.profile.navigate_headers(referer=FINANCE_HOME),
                                   allow_redirects=False, timeout=20.0)
        while r.status_code in (301, 302, 303, 307, 308) and hops < max_hops:
            loc = r.headers.get("location")
            if not loc:
                break
            url = urljoin(url, loc)                # aceita relativas e "//host"
            hops += 1
            r = self.transport.request("GET", url,
                                       headers=self.profile.navigate_headers(referer=FINANCE_HOME),
                                       allow_redirects=False, timeout=20.0)
        return r, hops

    @staticmethod
    def _left_consent(url: str) -> bool:
        """True quando a URL final saiu dos domínios de consentimento."""
        return not ("guce.yahoo.com" in url or "consent.yahoo.com" in url)

    def _accept(self, page: HttpResponse, page_url: str) -> bool:
        """Parseia o form da página e posta o aceite no collectConsent.

        O payload segue o cliente de comunidade: todos os campos do formulário
        (o que carrega `csrfToken` e `sessionId`, quando existem), `agree` duas
        vezes (os dois botões da página) e `consentUUID` default. O degrau de
        cópia (`copyConsent`) fecha o aceite.
        """
        m = self._FORM_RE.search(page.text or "")
        if not m:
            return False
        action = urljoin(page_url, html_lib.unescape(m.group(1)))
        form: Dict[str, str] = {}
        for tag in self._INPUT_RE.findall(page.text or ""):
            mn = self._ATTR_NAME_RE.search(tag)
            if not mn:
                continue
            mv = self._ATTR_VALUE_RE.search(tag)
            form.setdefault(html_lib.unescape(mn.group(1)),
                            html_lib.unescape(mv.group(1) if mv else ""))
        pares: List[Tuple[str, str]] = list(form.items())
        pares += [("agree", "agree"), ("agree", "agree")]        # dois botões
        pares += [("consentUUID", form.get("consentUUID") or "default")]
        headers = self.profile.api_headers(accept=self.profile.accept_html,
                                           referer=page_url,
                                           origin="https://guce.yahoo.com")
        pr = self.transport.request("POST", action, data=pares, headers=headers,
                                    allow_redirects=True, timeout=25.0)
        ok = pr.status_code in (200, 301, 302, 303, 307, 308)
        self._copy_consent(form, page_url)
        return ok

    def _copy_consent(self, form: Dict[str, str],
                      page_url: str) -> Optional[int]:
        """GET guce.yahoo.com/copyConsent — consolida o aceite na sessão de
        consentimento (cliente de comunidade; sem sessão válida responde 401)."""
        params: Dict[str, str] = {"lang": "en-US", "inline": "false"}
        if form.get("sessionId"):
            params["sessionId"] = form["sessionId"]
        try:
            r = self.transport.request(
                "GET", GUCE_COPY_CONSENT, params=params,
                headers=self.profile.api_headers(accept=self.profile.accept_html,
                                                 referer=page_url),
                allow_redirects=True, timeout=25.0)
            self.vault.absorb(self.transport.session)
            self.last_copy_status = r.status_code
            self.vault.event(f"copyConsent:{r.status_code}")
        except Exception as e:
            self.last_copy_status = None
            self.vault.event("copyConsent:erro")
            LOG.warning("copyConsent falhou: %s", e)
        return self.last_copy_status

    def run(self) -> Dict[str, Any]:
        """Executa o handshake e devolve um relatório decidível."""
        rel: Dict[str, Any] = {"ja_consentido": None, "form_postado": False,
                               "guc_presente": bool(self.vault.guc), "detalhe": ""}
        try:
            r, hops = self._follow(GUCE_CONSENT,
                                   params={"src": "finance", "finalDestination": FINANCE_HOME})
        except Exception as e:
            rel["detalhe"] = f"erro de rede no guce: {e}"
            return rel
        self.vault.absorb(self.transport.session)

        if self._left_consent(r.url or ""):
            # 302 para fora do fluxo de consentimento = sessão já consentida
            rel["ja_consentido"] = True
            rel["detalhe"] = (f"redirect após {hops} salto(s) — sessão já "
                              f"consentida (típico NON_EU_OATH)")
        else:
            form = self._FORM_RE.search(r.text or "")
            if r.status_code == 200 and form:
                rel["ja_consentido"] = False
                rel["form_postado"] = self._accept(r, r.url or GUCE_CONSENT)
                self.vault.absorb(self.transport.session)
                r2, _ = self._follow(GUCE_CONSENT, params={"src": "finance"})
                self.vault.absorb(self.transport.session)
                estado = "aceito via collectConsent" if rel["form_postado"] else "falha ao postar o form"
                rel["detalhe"] = f"{estado}; re-checagem HTTP {r2.status_code}"
            else:
                rel["detalhe"] = f"resposta inesperada do guce (HTTP {r.status_code})"
        rel["guc_presente"] = bool(self.vault.guc)
        self.vault.event("consent:" + ("ok" if rel["guc_presente"] else "sem-guc"))
        return rel


# ═════════════════════ máquina de estados do fallback ══════════════════

class ConsentStateMachine:
    """Máquina de estados do fallback de consentimento:

      (1) BASIC        — bootstrap canônico; se a resposta de mercado vier
                         normal, fim;
      (2) CSRF_CONSENT — se houver redirect para guce.yahoo.com/consent (ou
                         corpo HTML de consentimento em vez de JSON): carregar
                         a página, extrair o token CSRF do formulário (input
                         hidden `csrfToken`) e re-submeter TODOS os campos do
                         form mais o botão `agree=agree` ao `action` declarado
                         no <form> (collectConsent); depois, aguardar os
                         cookies GUC/família A atualizados e REPETIR o passo 2
                         do canônico (o crumb antigo morreu com a sessão
                         pré-consentimento);
      (3) PERSIST      — persistir o novo jar.

    O consentimento é ATUALIZADOR DO COOKIE A — o crumb do Finance continua
    sendo obtido exclusivamente via /v1/test/getcrumb.
    """

    BASIC = "basic"
    CSRF_CONSENT = "csrf/consent"
    PERSIST = "persist"

    _CSRF_RE = re.compile(r"<input[^>]*\bname=[\"']csrfToken[\"'][^>]*?"
                          r"\bvalue=[\"']([^\"']+)[\"']", re.I)

    def __init__(self, handshaker: ConsentHandshaker, vault: CookieVault):
        self.handshaker = handshaker
        self.vault = vault
        self.state = self.BASIC
        self.csrf_token: Optional[str] = None

    def run(self, on_consent_complete=None) -> Dict[str, Any]:
        """Roda a máquina; `on_consent_complete` é o passo 2 do canônico
        (normalmente uma renovação forçada de crumb) e roda entre os estados
        CSRF_CONSENT e PERSIST."""
        trilha: List[str] = [self.state]

        # estado 1: BASIC — o handshake (302 já-consentido OU form)
        rel = self.handshaker.run()
        rel["maquina_estados"] = {"estados": trilha, "csrf_encontrado": False}

        if rel.get("ja_consentido"):
            self.state = self.PERSIST            # fluxo curto (NON_EU_OATH)
        else:
            # estado 2: CSRF_CONSENT — só existe quando houve página de form
            self.state = self.CSRF_CONSENT
            trilha.append(self.state)
            # evidência do csrfToken (input hidden) — o form inteiro (todos os
            # campos + agree=agree) já foi re-submetido pelo handshaker
            page = None
            try:
                page, _ = self.handshaker._follow(GUCE_CONSENT, params={"src": "finance"})
            except Exception:
                page = None
            if page is not None:
                m = self._CSRF_RE.search(page.text or "")
                if m:
                    self.csrf_token = html_lib.unescape(m.group(1))
                    rel["maquina_estados"]["csrf_encontrado"] = True
            rel["maquina_estados"]["csrf_token"] = ("presente" if self.csrf_token
                                                    else "não exposto nesta janela")
            rel["maquina_estados"]["coletor"] = CONSENT_COLLECT_DEFAULT
            rel["maquina_estados"]["copia"] = (f"{GUCE_COPY_CONSENT} "
                                               f"(HTTP {self.handshaker.last_copy_status})")
            # repetir o passo 2 do canônico — o crumb antigo morreu
            if on_consent_complete is not None:
                try:
                    on_consent_complete()
                    rel["maquina_estados"]["crumb_renovado"] = True
                except Exception as e:
                    rel["maquina_estados"]["crumb_renovado"] = f"falsou: {e!r}"

        # estado 3: PERSIST — o novo jar vai ao disco (com o crumb renovado)
        self.state = self.PERSIST
        trilha.append(self.state)
        self.vault.save()
        rel["maquina_estados"]["estados"] = trilha
        return rel


# ═════════════════════ classificação dos 401 (bissecção) ════════════════

def consent_gate(r: HttpResponse) -> bool:
    """True quando a resposta é o gate de consentimento do servidor.

    Três formas, todas observáveis: redirect NÃO seguido para um domínio de
    consentimento (Location); redirect seguido — a URL FINAL da resposta é de
    consentimento; ou HTML no lugar do JSON (a página de consentimento
    responde 200 text/html). O consumidor aciona o estado csrf e reenvia.
    """
    if r.status_code in (301, 302, 303, 307, 308):
        if CONSENT_HOST_RE.search(r.headers.get("location", "") or ""):
            return True
    if CONSENT_HOST_RE.search(r.url or ""):
        return True
    ct = (r.headers.get("content-type") or "").lower()
    if r.status_code == 200 and "json" not in ct:
        head = (r.text or "")[:400].lstrip().lower()
        return head.startswith("<!doctype html") or head.startswith("<html")
    return False


def classify_401(body: str) -> str:
    """Os sabores de 401 exigem remédios diferentes:

      "Invalid Cookie"                        → cookie: sessão morreu,
                                                re-bootstrap total
      "Invalid Crumb"                         → crumb: renovar só o crumb
      "User is unable to access this feature" → crumb: idem
      qualquer outra coisa                    → unknown
    """
    if "Invalid Cookie" in body:
        return "cookie"
    if "Invalid Crumb" in body:
        return "crumb"
    if "User is unable to access this feature" in body:
        return "crumb"
    return "unknown"


# ═════════════════════ resolução de crumb (5 fontes) ═════════════════════════

def _crumb_valido(valor: Optional[str]) -> bool:
    """Forma observada: 11 chars; alfabeto inclui alfanuméricos, "." e "/" — aceitamos 5..64 por margem."""
    return bool(valor) and valor != MOCK_CRUMB and bool(CRUMB_RE.fullmatch(valor))


# cache global — análogo Python do window.finWebCore.crumb (inicia vazio:
# a factory da home cria o objeto com crumb "" e o SSR não passa o campo)
_FIN_WEBCORE: Dict[str, Optional[str]] = {"crumb": None}


def streamer_cache_reset() -> None:
    """Zera o cache global (uso: testes e --fresh)."""
    _FIN_WEBCORE["crumb"] = None


class CrumbResolver:
    """Resolução do crumb em cascata — ordem canônica primeiro, rotas
    alternativas depois:

      1. vault     — crumb persistido (renovado sob 401)
      2. html      — regex no crumb injetado pelo SSR (user.crumb;
                     sentinel MOCK_CRUMB descartado)
      3. endpoint  — GET /v1/test/getcrumb com Accept: text/plain
                     (application/json sozinho NUNCA — 406)
      4. streamer  — caminho próprio do streamer: host sorteado entre
                     query1/query2, Content-Type: text/plain como header de
                     REQUEST, timeout 10 s, cache global finWebCore
    """

    STRATEGIES = ("vault", "html", "endpoint", "streamer")
    DEFAULT_ORDER = ("vault", "html", "endpoint")       # comportamento canônico

    def __init__(self, transport: Transport, vault: CookieVault, profile: ChromeProfile,
                 order: Tuple[str, ...] = DEFAULT_ORDER):
        self.transport = transport
        self.vault = vault
        self.profile = profile
        self.order = tuple(s for s in order if s in self.STRATEGIES) or self.DEFAULT_ORDER

    def resolve(self, force: bool = False) -> Tuple[str, str]:
        """Devolve (crumb, origem); registra no cofre e no histórico."""
        erros: List[str] = []
        for nome in self.order:
            if nome == "vault" and (force or not self.vault.crumb):
                continue
            try:
                valor = getattr(self, f"_from_{nome}")()
            except Exception as e:
                erros.append(f"{nome}: {e}")
                LOG.debug("estratégia '%s' falhou: %s", nome, e)
                continue
            if _crumb_valido(valor):
                self.vault.set_crumb(valor, nome)
                return valor, nome
            erros.append(f"{nome}: candidato inválido {valor!r}")
        raise RuntimeError("crumb indisponível em todas as estratégicas — " + " | ".join(erros))

    # ── estratégia 1: cofre persistido ──────────────────────────────────
    def _from_vault(self) -> str:
        if self.vault.crumb:
            return self.vault.crumb
        raise ValueError("cofre sem crumb")

    # ── estratégia 2: regex no HTML SSR da homepage ─────────────────────
    def _from_html(self) -> str:
        r = self.transport.request("GET", FINANCE_HOME,
                                   headers=self.profile.navigate_headers(), timeout=30.0)
        if r.status_code != 200:
            raise RuntimeError(f"homepage HTTP {r.status_code}")
        candidatos: List[str] = []
        for pat in CRUMB_PATTERNS:
            for m in re.finditer(pat, r.text):
                candidatos.append(m.group(1))
        for v in candidatos:
            if _crumb_valido(v):
                return v
        raise ValueError(f"{len(candidatos)} candidato(s) no HTML, nenhum válido")

    # ── estratégia 3: endpoint oficial (regra do Accept) ─────────────────
    def _from_endpoint(self) -> str:
        ultimo = "sem resposta"
        for host in QUERY_HOSTS:                    # intercambiáveis
            r = self.transport.request(
                "GET", f"https://{host}{GETCRUMB_PATH}",
                headers=self.profile.api_headers(accept="text/plain"),  # ← 406-safe
                timeout=10.0)
            if r.status_code == 200 and r.text.strip():
                v = r.text.strip()
                if _crumb_valido(v):
                    return v
                ultimo = f"corpo atípico {v[:20]!r}"
            else:
                ultimo = f"HTTP {r.status_code} @ {host}: {r.text[:60]!r}"
        raise RuntimeError(f"getcrumb falhou — {ultimo}")

    # ── estratégia 4: caminho próprio do streamer ────────────────────────
    def _from_streamer(self) -> str:
        """Caminho próprio do streamer:
          1. window.finWebCore.crumb → cache global, sem rede
          2. host SORTEADO (Math.floor(Math.random()*S.length))
          3. Content-Type: text/plain como header de REQUEST (não é Accept)
          4. timeout 10000 ms
          5. resultado consumido como TEXTO CRU (a condição de parse JSON do
             fetcher olha o objeto de headers do request) e cacheado.
        O boot do streamer é bloqueante: finStreamer.init() só roda depois
        deste M() resolver."""
        cache = _FIN_WEBCORE["crumb"]
        if cache and _crumb_valido(cache):
            return cache                                 # 1. cache global
        host = random.choice(QUERY_HOSTS)                # 2. host sorteado
        headers = self.profile.api_headers(accept="text/plain")
        headers["Content-Type"] = "text/plain"           # 3. header de REQUEST
        r = self.transport.request("GET", f"https://{host}{GETCRUMB_PATH}",
                                   headers=headers, timeout=STREAMER_TIMEOUT)  # 4. 10 s
        if r.status_code == 200 and r.text.strip():
            v = r.text.strip()
            if _crumb_valido(v):
                _FIN_WEBCORE["crumb"] = v                # 5. cacheia no global
                return v
        raise RuntimeError(f"streamer getcrumb HTTP {r.status_code} @ {host}: "
                           f"{r.text[:60]!r}")


# ═════════════════════ orquestrador do par (A3, crumb) ══════════════════════

class YahooFinanceSession:
    """Modelo atômico: cookie A3 de vida longa + crumb de vida curta,
    validados pelo servidor como unidade.

    Ordem canônica: fc.yahoo.com → consentimento → crumb → APIs, com
    failover query1↔query2, backoff com jitter, circuit breaker, máquina
    de estados de consentimento e renovação diferenciada por tipo de 401.
    """

    def __init__(self, jar_path: Optional[str] = None, *,
                 strategy: Tuple[str, ...] = CrumbResolver.DEFAULT_ORDER,
                 lang: str = "en-US", region: str = "US", prefer_cffi: bool = True):
        self.profile = ChromeProfile()
        self.transport = Transport(self.profile, prefer_cffi=prefer_cffi)
        self._lock = threading.RLock()                   # serializa crumb/sessão em threads
        self.vault = CookieVault(jar_path or JAR_DEFAULT)
        self.vault.load()
        if self.vault.has_session():
            self.vault.restore_into(self.transport.session)
            self.vault.event("jar-restaurado")
        self.forensics = A3Forensics()
        self.a3_expiry = self._estimate_a3_expiry()
        self.consent = ConsentHandshaker(self.transport, self.vault, self.profile)
        self.state_machine = ConsentStateMachine(self.consent, self.vault)
        self.crumb_resolver = CrumbResolver(self.transport, self.vault, self.profile,
                                            order=strategy)
        self.backoff = ExponentialBackoff()
        self.breakers = CircuitBreaker()
        self.lang = lang
        self.region = region
        self._host_cursor = 0

    # ── pré-checagem de expiração do A3 ──────────────────────────────────
    def _estimate_a3_expiry(self) -> Optional[int]:
        parsed = self.forensics.decode(self.vault.a3)
        return self.forensics.expiry_estimate(parsed) if parsed else None

    def _a3_expired(self) -> bool:
        """True quando a expiração estimada do A3 já passou."""
        return bool(self.a3_expiry) and self.a3_expiry < time.time()

    # ── bootstrap: A3 (fc.yahoo.com) + consentimento ─────────────────────
    def bootstrap(self, force: bool = False) -> Dict[str, Any]:
        with self._lock:                              # serializa com get_json/get_crumb
            return self._bootstrap_locked(force)

    def _bootstrap_locked(self, force: bool = False) -> Dict[str, Any]:
        info: Dict[str, Any] = {"a3_origem": "jar (reutilizado)", "consent": None,
                                "forense": None}
        if force or not self.vault.has_session() or self._a3_expired():
            r = self.transport.request("GET", FC_YAHOO,
                                       headers=self.profile.navigate_headers(),
                                       allow_redirects=False, timeout=15.0)
            # 404 é o comportamento NORMAL do fc: o que importa é o
            # Set-Cookie A3 que chega junto.
            self.vault.absorb(self.transport.session)
            self.vault.event(f"bootstrap:fc:{r.status_code}")
            info["a3_origem"] = f"fc.yahoo.com (HTTP {r.status_code}, 404 = normal)"
        if not self.vault.has_session():
            raise RuntimeError("bootstrap não produziu cookie A3 — investigar rede/TLS")

        self.a3_expiry = self._estimate_a3_expiry()   # (re)calcula após eventual re-mint
        parsed = self.forensics.decode(self.vault.a3)
        info["forense"] = parsed
        if parsed:
            req, motivo = self.forensics.consent_check_required(parsed)
            info["consent_gate"] = {"requerido": req, "motivo": motivo}
            if not req and self.vault.guc:
                info["consent"] = {"ja_consentido": True,
                                   "guc_presente": True,
                                   "detalhe": f"gate do bundle: {motivo}"}
        if info["consent"] is None or not self.vault.guc:
            # máquina completa: basic → csrf/consent → (renovar crumb) →
            # persist; o passo 2 do canônico roda no callback
            info["consent"] = self.state_machine.run(
                on_consent_complete=lambda: self.get_crumb(force=True))
        self.vault.save()
        return info

    # ── crumb (delegado ao resolver multi-fonte; thread-safe) ───────────
    def get_crumb(self, force: bool = False) -> str:
        with self._lock:
            return self.crumb_resolver.resolve(force=force)[0]

    # ── fontes alternativas de crumb, acionáveis individualmente ────────
    def streamer_crumb(self) -> str:
        """Caminho próprio do streamer (host sorteado, Content-Type
        text/plain de request, 10 s, cache global finWebCore)."""
        v = self.crumb_resolver._from_streamer()
        self.vault.set_crumb(v, "streamer")
        return v

    # ── crumb do guce (auto-derivado) + CCPA ─────────────────────────────
    def guce_crumb(self) -> Optional[str]:
        """agentId || temporaryId || rSynthId — auto-derivado do A3 parseado;
        entra como ?crumb= nas rotas do guce (GUCE_ROUTES)."""
        c = self.forensics.guce_crumb(self.vault.a3)
        if c:
            self.vault.event("guce-crumb-derivado")
        return c

    def guce_api_url(self, route: str, update_type: Optional[str] = None,
                     eval_bucket: Optional[str] = None,
                     extra: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Monta a URL de chamada do guce:
        `https://{consentHost}/{rota}?crumb={derivado}[&updateType=][&evalBucket=][&extras]`."""
        d = self.guce_crumb()
        if not d:
            return None
        url = f"https://guce.yahoo.com/{route.lstrip('/')}?crumb={d}"
        if update_type:
            url += f"&updateType={update_type}"
        if eval_bucket:
            url += f"&evalBucket={eval_bucket}"
        for k, v in (extra or {}).items():
            url += f"&{k}={v}"
        return url

    def ccpa(self) -> str:
        """ccpa_jurisdiction sobre a string INTEIRA do cookie A."""
        return ccpa_jurisdiction(self.vault.a3)

    # ── failover round-robin com circuit breaker ────────────────────────
    def _pick_host(self) -> str:
        ok = [h for h in QUERY_HOSTS if self.breakers.allow(h)]
        if not ok:
            espera = max(0.0, self.breakers.next_recovery(list(QUERY_HOSTS)) - time.time()) + 0.5
            LOG.warning("todos os hosts abertos — aguardando half-open (%.1fs)", espera)
            time.sleep(espera)
            ok = list(QUERY_HOSTS)
        self._host_cursor = (self._host_cursor + 1) % len(ok)
        return ok[self._host_cursor]

    def _rebootstrap(self) -> None:
        """401 'Invalid Cookie' → sessão morreu: recomeça do zero.
        O jar INTEIRO é descartado (cookies + crumb andam juntos)."""
        with self._lock:
            LOG.info("re-bootstrap: descartando cookies e crumb, voltando ao fc.yahoo.com")
            self.vault.cookies.clear()
            self.vault.crumb = None
            self.vault.crumb_issued_at = None
            try:
                self.transport.session.cookies.clear()
            except Exception:
                pass
            self.bootstrap(force=True)

    # ── API genérica com retry/401-refresh ───────────────────────────────
    def get_json(self, pathname: str, params: Optional[Dict[str, Any]] = None, *,
                 method: str = "GET", data: Optional[Union[Dict[str, Any], str, bytes]] = None,
                 crumb: bool = True, max_attempts: int = 4) -> Any:
        q: Dict[str, Any] = {"lang": self.lang, "region": self.region}   # defaults do site
        q.update(params or {})
        refreshes = 2
        consent_tentado = False                      # estado csrf roda uma vez
        ultimo_erro = ""
        for attempt in range(max_attempts):
            host = self._pick_host()
            headers = self.profile.api_headers(
                accept="application/json",
                origin=FINANCE_HOME if method.upper() != "GET" else None)
            if crumb:
                try:
                    q["crumb"] = self.get_crumb()
                except Exception as e:
                    # getcrumb pode falhar (ex.: 429): segue sem crumb e deixa o
                    # endpoint decidir — degradação em vez de abortar a chamada
                    q.pop("crumb", None)
                    LOG.warning("crumb indisponível (%s) — seguindo sem crumb", e)
                else:
                    if method.upper() not in ("GET", "HEAD", "OPTIONS"):
                        headers["x-crumb"] = q["crumb"]   # mutações ganham header
            try:
                r = self.transport.request(method, f"https://{host}{pathname}",
                                           params=q, data=data, headers=headers, timeout=15.0)
            except Exception as e:
                # falha de transporte (DNS, TLS, conexão): entra no circuit
                # breaker e no backoff em vez de abortar a chamada inteira
                ultimo_erro = f"transporte @ {host}: {e!r}"
                self.breakers.record_failure(host)
                if attempt + 1 < max_attempts:
                    time.sleep(self.backoff.delay(attempt))
                continue
            if consent_gate(r):
                # estado csrf: o servidor pediu consentimento antes de servir
                if not consent_tentado:
                    consent_tentado = True
                    LOG.warning("gate de consentimento na resposta (%s) — "
                                "executando o estado csrf", r.url or r.status_code)
                    try:
                        self.state_machine.run(
                            on_consent_complete=lambda: self.get_crumb(force=True))
                        ultimo_erro = "gate de consentimento — estado csrf executado"
                    except Exception as e:
                        ultimo_erro = f"fallback csrf falhou: {e!r}"
                else:
                    ultimo_erro = (f"gate de consentimento persistente após o "
                                   f"estado csrf ({r.url or r.status_code})")
                self.breakers.record_failure(host)
                if attempt + 1 < max_attempts:
                    time.sleep(self.backoff.delay(attempt))
                continue                             # reenvia a chamada
            if r.status_code == 200:
                self.breakers.record_success(host)
                with self._lock:
                    self.vault.absorb(self.transport.session)
                return r.json()
            ultimo_erro = f"HTTP {r.status_code} @ {host}: {r.text[:100]!r}"
            if r.status_code == 401 and refreshes > 0:
                refreshes -= 1
                sabor = classify_401(r.text)              # classifica o 401
                if sabor == "cookie":
                    LOG.warning("401 Invalid Cookie — re-bootstrap da sessão")
                    self._rebootstrap()
                else:
                    # sabores de crumb (e desconhecidos): renovar
                    # SÓ o crumb é o remédio
                    LOG.warning("401 (sabor=%s) — renovando crumb e reenviando", sabor)
                    try:
                        self.get_crumb(force=True)
                    except Exception as e:
                        LOG.warning("renovação de crumb falhou (%s) — reenviando sem crumb", e)
                continue
            self.breakers.record_failure(host)
            if r.status_code == 429:
                LOG.warning("429 @ %s — rate limit, backoff", host)
            if attempt + 1 < max_attempts:
                time.sleep(self.backoff.delay(attempt))
        raise RuntimeError(f"{pathname} falhou após {max_attempts} tentativas — {ultimo_erro}")

    # ── exemplo de consumo: cotações em lotes ───────────────────────────
    def quote(self, symbols: List[str], batch: int = 30) -> List[Dict[str, Any]]:
        """Lotes de 30 = convenção do site; o servidor não impõe
        limite rígido de 30 símbolos."""
        syms = [s.strip().upper() for s in symbols if s.strip()]
        out: List[Dict[str, Any]] = []
        for i in range(0, len(syms), batch):
            chunk = syms[i:i + batch]
            j = self.get_json(QUOTE_PATH, {"symbols": ",".join(chunk)})
            out.extend(j.get("quoteResponse", {}).get("result") or [])
            if i + batch < len(syms):
                time.sleep(1.0)                        # cortesia entre lotes
        return out

    def close(self) -> None:
        self.vault.save()

    def __enter__(self) -> "YahooFinanceSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ═════════════════════════════ CLI / demo ═══════════════════════════════════

def _h(title: str) -> None:
    print()
    print("═" * 78)
    print(f" {title}")
    print("═" * 78)


def _print_forense(parsed: Optional[dict], forensics: A3Forensics) -> None:
    print("── Forense do A3 (TLV, parser embutido) " + "─" * 33)
    if not parsed:
        print("  (indisponível — A3 ilegível)")
        return
    for linha in forensics.summarize(parsed):
        print(f"  {linha}")
    req, motivo = forensics.consent_check_required(parsed)
    print(f"  gate isConsentCheckRequired → {'SIM' if req else 'NÃO'} ({motivo})")
    gc = guce_crumb_from_parsed(parsed)
    print(f"  crumb do guce (agentId||temporaryId||rSynthId) → {gc!r}")


def cmd_demo(args: argparse.Namespace) -> int:
    estrategia = tuple(s.strip() for s in args.strategy.split(",") if s.strip())
    invalida = [s for s in estrategia if s not in CrumbResolver.STRATEGIES]
    if invalida:
        print(f"estratégias inválidas: {invalida} — use: {', '.join(CrumbResolver.STRATEGIES)}")
        return 2

    sess = YahooFinanceSession(jar_path=args.jar, strategy=estrategia,
                               lang=args.lang, region=args.region,
                               prefer_cffi=not args.no_cffi)
    try:
        info = sess.bootstrap(force=args.fresh)
        p, t = sess.profile, sess.transport

        _h("YAHOO FINANCE · REFERÊNCIA COMPLETA — DEMO AO VIVO")
        print(f"[1/7] Emulação .......... Chrome {p.major} · Windows 10/11 · backend: {t.backend_name}")
        print(f"      UA: {p.user_agent}")
        print(f"[2/7] Client Hints ...... sec-ch-ua: {p.sec_ch_ua}")
        print(f"      Sec-Fetch: navigate→document · cors(same-site)→empty · Priority: u=1, i")
        print(f"[3/7] Decodificação ..... Accept-Encoding: {t.accept_encoding}"
              f" · camada manual por magic bytes: ativa")
        crumb, origem = sess.crumb_resolver.resolve(force=args.fresh)
        idade = sess.vault.crumb_age() or 0.0
        print(f"[4/7] Crumb ............. '{crumb}' via estratégia '{origem}'"
              f" ({len(crumb)} chars, emitido há {idade:.0f}s)")
        familia = ", ".join(n for n in AUTH_FAMILY if sess.vault.cookies.get(n)) or "—"
        exp_txt = ""
        if sess.a3_expiry:
            dt = datetime.datetime.fromtimestamp(sess.a3_expiry, tz=datetime.timezone.utc)
            exp_txt = f" · A3 expira ~{dt.strftime('%Y-%m-%d')}"
        print(f"[5/7] Cookies ........... família presente: {familia}"
              f" · {len(sess.vault.cookies)} no cofre · origem A3: {info['a3_origem']}{exp_txt}")
        cons = info.get("consent") or {}
        me = cons.get("maquina_estados") or {}
        estado = ("já consentido" if cons.get("ja_consentido")
                  else "form de consentimento processado" if cons.get("form_postado")
                  else "verificar detalhe")
        trilha = " → ".join(me.get("estados", ["basic", "persist"]))
        print(f"[6/7] Consentimento ..... {estado} · GUC: "
              f"{'presente' if cons.get('guc_presente') else 'ausente'}")
        print(f"      máquina de estados: {trilha}"
              f" · csrfToken: {me.get('csrf_token', 'n/a (fluxo curto)')}")
        det = cons.get("detalhe") or ""
        if det:
            print(f"      {det}")
        gc = sess.guce_crumb()
        print(f"[7/7] Crumb do guce ..... {gc!r} (auto-derivado)"
              f" · CCPA: {sess.ccpa()}")

        _print_forense(info.get("forense"), sess.forensics)

        _h("MERCADO — /v7/finance/quote (exemplo de consumo)")
        simbolos = [s.strip() for s in args.symbols.split(",") if s.strip()]
        try:
            quotes = sess.quote(simbolos)
        except Exception as e:
            print(f"  (falha: {e})")
            quotes = []
        if not quotes:
            print("  (sem resultados)")
        for q in quotes:
            var = q.get("regularMarketChangePercent")
            var_s = f"{var:+.2f}%" if isinstance(var, (int, float)) else "    —"
            print(f"  {q.get('symbol', '?'):<11} {str(q.get('regularMarketPrice', '—')):>10} "
                  f"{q.get('currency') or '':<4} {var_s:>8}  {(q.get('shortName') or '')[:30]}")

        netscape = sess.vault.path + ".netscape"
        sess.vault.export_netscape(netscape)
        print()
        print(f"OK — sessão persistida (chmod 600): {sess.vault.path}")
        print(f"OK — exportação Netscape:           {netscape}")
        print("      (interop stdlib http.cookiejar: --to-cookiejar ARQUIVO)")
        print(f"Reuso: python3 {os.path.basename(__file__)} "
              f"--symbols AAPL,MSFT,NVDA --jar {sess.vault.path}")
        return 0
    finally:
        sess.close()


def cmd_inspect(args: argparse.Namespace) -> int:
    v = CookieVault(args.jar)
    if not v.load():
        print(f"nenhum jar em {args.jar} — rode a demo primeiro")
        return 1
    _h(f"INSPEÇÃO DO JAR — {args.jar}")
    salvo = v.history[-1].get("ts") if v.history else None
    if salvo:
        quando = datetime.datetime.fromtimestamp(salvo, tz=datetime.timezone.utc)
        print(f"último evento: {quando.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"cookies ({len(v.cookies)}): {', '.join(sorted(v.cookies)) or '—'}")
    if v.crumb:
        print(f"crumb: {v.crumb!r} (emitido há {(v.crumb_age() or 0):.0f}s)")
    else:
        print("crumb: —")
    print(f"eventos recentes: {' · '.join(e['event'] for e in v.history[-8:]) or '—'}")
    f = A3Forensics()
    parsed = f.decode(v.a3)
    est = f.expiry_estimate(parsed) if parsed else None
    if est:
        quando = datetime.datetime.fromtimestamp(est, tz=datetime.timezone.utc)
        estado = "EXPIADO" if est < time.time() else "vigente"
        print(f"A3 expira (estimado): {quando.strftime('%Y-%m-%d')} ({estado})")
    print()
    print_taxonomy(v)
    print()
    _print_forense(parsed, f)
    return 0


def cmd_decode_a3(args: argparse.Namespace) -> int:
    a3_value = args.decode_a3
    if args.from_jar:
        a3_value = read_a3_from_jar(args.from_jar)
        if not a3_value:
            print(f"ERRO: cookie A3 não encontrado no jar {args.from_jar}")
            return 2
    if not a3_value:
        print("ERRO: informe --decode-a3 VALOR ou --from-jar ARQUIVO")
        return 2
    f = A3Forensics()
    parsed = f.decode(a3_value)
    if not parsed:
        print("decode falhou — valor inválido")
        return 1
    print(json.dumps(parsed, indent=2, ensure_ascii=False))
    req, motivo = f.consent_check_required(parsed)
    print(f"\ngate isConsentCheckRequired → {'SIM' if req else 'NÃO'} ({motivo})")
    gc = guce_crumb_from_parsed(parsed)
    print(f"crumb do guce (auto-derivado) → {gc!r}")
    print(f"CCPA (partição j=) → {ccpa_jurisdiction(a3_value)}")
    return 0


def cmd_crumbs(args: argparse.Namespace, fonte: str) -> int:
    """Exercita UMA fonte alternativa de crumb (--streamer-crumb)
    sobre o cofre indicado."""
    sess = YahooFinanceSession(jar_path=args.jar, strategy=("endpoint",),
                               prefer_cffi=not args.no_cffi)
    try:
        if not sess.vault.has_session():
            sess.bootstrap(force=True)
        _h(f"FONTE DE CRUMB — {fonte}")
        if fonte == "streamer":
            v = sess.streamer_crumb()
            extra = f"cache global finWebCore: {_FIN_WEBCORE['crumb']!r} (2ª chamada viria daqui)"
        else:
            raise ValueError(f"fonte desconhecida: {fonte}")
        print(f"  crumb: {v!r} ({len(v)} chars)")
        print(f"  {extra}")
        print(f"  cofre atualizado (histórico: crumb:{fonte})")
        return 0
    except Exception as e:
        print(f"  falhou: {e}")
        return 1
    finally:
        sess.close()


def cmd_to_cookiejar(args: argparse.Namespace) -> int:
    """Exporta o cofre para um cookies.txt Netscape escrito pelo próprio
    http.cookiejar.MozillaCookieJar do Python, com expiração normalizada
    (agora + horizon_days). Auto-verificação: recarrega o arquivo com
    flags padrão e confirma contagem + A3 byte-idêntico. NÃO imprime
    valores de cookie (higiene de credenciais).
    """
    v = CookieVault(args.jar)
    if not v.load():
        print(f"nenhum jar em {args.jar} — rode a demo primeiro")
        return 1
    _h("SHIM DE INTEROPERABILIDADE STDLIB — --to-cookiejar")
    n = v.export_stdlib_cookiejar(args.to_cookiejar,
                                  horizon_days=args.cookiejar_horizon_days)
    httponly = sorted(HTTPONLY_FAMILY & set(v.cookies))
    print(f"  cookies exportados: {n} → {args.to_cookiejar}")
    print(f"  escritor: http.cookiejar.MozillaCookieJar (Python {sys.version.split()[0]})")
    print(f"  #HttpOnly_ reemitido em: {', '.join(httponly) or '—'} (família A)")
    print(f"  TTL aplicado: agora + {args.cookiejar_horizon_days} dias "
          f"(artefato de compatibilidade)")
    try:
        j = _MozillaCookieJar()
        j.load(args.to_cookiejar)                        # FLAGS PADRÃO (a prova real)
        nomes = sorted(c.name for c in j)
        a3_ok = any(c.name == "A3" and c.value == v.a3 for c in j)
        ok = bool(nomes) and len(nomes) == n and a3_ok
    except Exception as e:
        print(f"  auto-verificação FALHOU: {type(e).__name__}: {e}")
        return 2
    print(f"  auto-verificação (load flags padrão): {len(nomes)}/{n} cookies → "
          f"{', '.join(nomes) or '—'}")
    print(f"  A3 byte-idêntico no round-trip stdlib: {'SIM' if a3_ok else 'NÃO'}")
    print("  consumidor: j = MozillaCookieJar(); j.load(arquivo)  # sem flags extras")
    return 0 if ok else 2


def cmd_guce_crumb(args: argparse.Namespace) -> int:
    """Mostra o crumb auto-derivado + monta as 11 rotas do guce."""
    v = CookieVault(args.jar)
    if not v.load():
        print(f"nenhum jar em {args.jar} — rode a demo primeiro")
        return 1
    _h("CRUMB DO GUCE — AUTO-DERIVADO DO COOKIE A")
    parsed = A3Forensics().decode(v.a3)
    if not parsed:
        print("  A3 ilegível no cofre")
        return 1
    d = guce_crumb_from_parsed(parsed)
    fonte = ("agentId (tag 03)" if parsed.get("agentId_b64url")
             else "temporaryId (tag 02)" if parsed.get("temporaryId_b64url")
             else "rSynthId (tag 11)" if parsed.get("rSynthId") else "?")
    print(f"  crumb derivado: {d!r}  ← fonte: {fonte}")
    print(f"  preferência do bundle: agentId → temporaryId → rSynthId (nunca servidor)")
    print(f"  CCPA (includes \"j=CCPA\"): {ccpa_jurisdiction(v.a3)}")
    print()
    print("  ── 11 rotas do guce (yimg/oa/consent.js) com o crumb montado ──")
    for nome, rota in GUCE_ROUTES.items():
        url = f"https://guce.yahoo.com/{rota.lstrip('/')}?crumb={d}"
        print(f"  {nome:<28} {url[:96]}{'…' if len(url) > 96 else ''}")
    print()
    print("  formato da chamada (função T do módulo): POST com withCredentials"
          " e Content-Type: application/x-www-form-urlencoded, corpo vazio.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="yfinance_legacy.py",
        description="Yahoo Finance — autenticação Cookie A3 + Crumb: parser TLV "
                    "embutido, 5 fontes de crumb, handshake GUCE com máquina de "
                    "estados, crumb do guce auto-derivado, taxonomia e mapa de "
                    "módulos, backoff/circuit breaker e classificação de 401. "
                    "Arquivo único, sem dependências obrigatórias.",
        epilog="Especificação completa: auth_cookie_a3_crumb.md")
    ap.add_argument("--jar", default=JAR_DEFAULT,
                    help="caminho do cofre persistido (default: ./yahoo_session.json, "
                         "relativo ao diretório de execução)")
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA",
                    help="símbolos para a demo de cotação (vírgula-separados)")
    ap.add_argument("--strategy", default="vault,html,endpoint",
                    help="ordem das fontes de crumb: vault,html,endpoint,streamer")
    ap.add_argument("--fresh", action="store_true",
                    help="ignora o jar salvo e faz bootstrap completo")
    ap.add_argument("--no-cffi", action="store_true",
                    help="desativa o curl_cffi (usa requests puro)")
    ap.add_argument("--lang", default="en-US")
    ap.add_argument("--region", default="US")
    ap.add_argument("--inspect", action="store_true", help="relatório do jar salvo")
    ap.add_argument("--decode-a3", metavar="VALOR", nargs="?", const="",
                    help="decodificação forense standalone de um cookie A3 (parser embutido)")
    ap.add_argument("--from-jar", metavar="ARQUIVO",
                    help="lê o A3 de um jar Netscape e decodifica (pode ser usado sozinho)")
    ap.add_argument("--taxonomy", action="store_true",
                    help="taxonomia de cookies do painel de debug")
    ap.add_argument("--guce-crumb", action="store_true",
                    help="crumb do guce auto-derivado + 11 rotas")
    ap.add_argument("--streamer-crumb", action="store_true",
                    help="emite crumb pelo caminho próprio do streamer")
    ap.add_argument("--to-cookiejar", metavar="ARQUIVO",
                    help="exporta o cofre p/ cookies.txt Netscape consumível pelo "
                         "http.cookiejar do stdlib com flags padrão")
    ap.add_argument("--cookiejar-horizon-days", type=int, default=90, metavar="N",
                    help="TTL em dias da exportação stdlib (default 90; "
                         "expires=0 da convenção curl esvazia o jar no stdlib)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    if not args.verbose:
        logging.getLogger().setLevel(logging.WARNING)

    if args.decode_a3 is not None or args.from_jar:
        return cmd_decode_a3(args)
    if args.taxonomy:
        v = CookieVault(args.jar)
        v.load()
        print_taxonomy(v if v.cookies else None)
        return 0
    if args.guce_crumb:
        return cmd_guce_crumb(args)
    if args.streamer_crumb:
        return cmd_crumbs(args, "streamer")
    if args.to_cookiejar:
        return cmd_to_cookiejar(args)
    if args.inspect:
        return cmd_inspect(args)
    return cmd_demo(args)


if __name__ == "__main__":
    sys.exit(main())
