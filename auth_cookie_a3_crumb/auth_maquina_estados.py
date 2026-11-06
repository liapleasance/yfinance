#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Máquina de estados de autenticação Yahoo Finance — estratégias basic <-> csrf.

Implementação de referência do documento auth_maquina_estados.md. Réplica
enxuta da máquina observada no cliente Python oficial (yfinance, data.py):

    basic (default)                    csrf (fallback)
    -----------------                  -------------------------------------
    fc.yahoo.com -> A3                  guce.yahoo.com/consent -> parse form
    query1/getcrumb -> crumb            -> POST consent.yahoo.com/v2/collectConsent
                                       -> GET guce.yahoo.com/copyConsent
                                       -> query2/getcrumb -> crumb

Transições cobertas:
  - aquisição por cada estratégia (colunas basic e csrf);
  - toggle de estratégia quando a aquisição falha;
  - toggle de estratégia + re-aquisição quando a resposta vem >= 400;
  - par (cookie, crumb) atômico: o toggle zera os dois juntos.

Uso:
    python3 auth_maquina_estados.py                     # demonstra as duas colunas
    python3 auth_maquina_estados.py --strategy basic    # só a coluna basic
    python3 auth_maquina_estados.py --strategy csrf     # só a coluna csrf
    python3 auth_maquina_estados.py --symbols AAPL,MSFT,NVDA

Sem dependências obrigatórias: com curl_cffi instalada usa impersonação de
Chrome (JA3/JA4); sem ela degrada para requests com User-Agent de browser.
"""

import argparse
import re
import sys
import threading

try:
    from curl_cffi import requests as backend
    HAS_CFFI = True
except ImportError:
    import requests as backend
    HAS_CFFI = False

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")

FC = "https://fc.yahoo.com"
GUCE = "https://guce.yahoo.com"
COLLECT = "https://consent.yahoo.com/v2/collectConsent"
COPY = "https://guce.yahoo.com/copyConsent"
Q1 = "https://query1.finance.yahoo.com"
Q2 = "https://query2.finance.yahoo.com"


def new_session():
    """Transporte: curl_cffi com fingerprint de Chrome; fallback requests."""
    if HAS_CFFI:
        return backend.Session(impersonate="chrome")
    s = backend.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    return s


def cookie_jar(session):
    """Jar real para ambos os backends (curl_cffi: .cookies.jar)."""
    cookies = session.cookies
    return getattr(cookies, "jar", cookies)


def jar_cookies(session):
    """Itera objetos Cookie (name/value/domain/expires) do jar."""
    return list(cookie_jar(session))


def trace(state, msg):
    print(f"[{state:>13}] {msg}")


class AuthStateMachine:
    """Estados: SEM_SESSAO -> AQUISICAO -> AUTENTICADO (| REJEITADO -> toggle)."""

    def __init__(self):
        self._session = new_session()
        self._strategy = "basic"   # default do cliente oficial
        self._cookie = None        # objeto Cookie A3 do jar (ou True)
        self._crumb = None         # par atômico: zera junto com o cookie
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ basic
    def _get_cookie_basic(self, timeout=15):
        if self._cookie is not None:
            return True
        r = self._session.get(FC, timeout=timeout, allow_redirects=True)
        names = sorted({c.name for c in jar_cookies(self._session)})
        trace("basic", f"GET fc.yahoo.com -> HTTP {r.status_code} "
                      f"(404 esperado; o que vale e o Set-Cookie)")
        trace("basic", f"jar apos bootstrap: {', '.join(names) or '(vazio)'}")
        a3 = next((c for c in jar_cookies(self._session) if c.name == "A3"), None)
        if a3 is not None:
            # o jar (http.cookiejar.Cookie) só carrega http_only, e em minúsculas;
            # SameSite existe apenas no header Set-Cookie da resposta
            rest = getattr(a3, "_rest", None) or {}
            m_same = re.search(r"SameSite=([A-Za-z]+)",
                              r.headers.get("set-cookie") or "")
            trace("basic", f"A3 atributos: Domain={a3.domain} expires={a3.expires} "
                          f"SameSite={m_same.group(1) if m_same else 'n/d'} "
                          f"HttpOnly={rest.get('http_only', 'n/d')} "
                          f"Secure={a3.secure}")
            self._cookie = a3
            return True
        return False

    def _get_crumb_basic(self, timeout=15):
        if self._crumb is not None:
            return self._crumb
        if not self._get_cookie_basic(timeout):
            return None
        r = self._session.get(f"{Q1}/v1/test/getcrumb", timeout=timeout,
                              allow_redirects=True)
        crumb = r.text
        trace("basic", f"GET query1/v1/test/getcrumb -> HTTP {r.status_code} "
                      f"{r.headers.get('content-type', '')}")
        if r.status_code == 200 and crumb and "<html>" not in crumb.lower():
            self._crumb = crumb
            trace("basic", f"crumb = {crumb!r} ({len(crumb)} chars)")
            return crumb
        return None

    # ------------------------------------------------------------------- csrf
    def _get_cookie_csrf(self, timeout=15):
        if self._cookie is not None:
            return True
        try:
            r = self._session.get(f"{GUCE}/consent", timeout=timeout)
        except Exception as e:
            # degradacao identica a do cliente oficial: falha de rede no guce
            # nao aborta — a maquina faz toggle para a outra coluna
            trace("csrf", f"GET guce.yahoo.com/consent falhou ({type(e).__name__})")
            return False
        trace("csrf", f"GET guce.yahoo.com/consent -> HTTP {r.status_code} "
                      f"(URL final: {r.url})")
        # inputs hidden do formulario (csrfToken, sessionId, ...)
        inputs = {}
        for tag in re.findall(r"<input\b[^>]*>", r.text, re.I):
            name = re.search(r'name=["\']([^"\']+)["\']', tag)
            value = re.search(r'value=["\']([^"\']*)["\']', tag)
            if name:
                inputs[name.group(1)] = value.group(1) if value else ""
        trace("csrf", f"inputs hidden: {sorted(inputs)}")
        if "csrfToken" not in inputs or "sessionId" not in inputs:
            trace("csrf", "formulario de consentimento nao encontrado")
            return False
        # payload identico ao do cliente oficial
        data = {
            "agree": ["agree", "agree"],
            "consentUUID": "default",
            "sessionId": inputs["sessionId"],
            "csrfToken": inputs["csrfToken"],
            "originalDoneUrl": inputs.get("originalDoneUrl",
                                          "https://finance.yahoo.com/"),
            "namespace": inputs.get("namespace", "yahoo"),
        }
        pr = self._session.post(
            f"{COLLECT}?sessionId={inputs['sessionId']}",
            data=data, timeout=timeout)
        trace("csrf", f"POST consent.yahoo.com/v2/collectConsent -> "
                      f"HTTP {pr.status_code}")
        cr = self._session.get(
            f"{COPY}?sessionId={inputs['sessionId']}",
            data=data, timeout=timeout)
        trace("csrf", f"GET guce.yahoo.com/copyConsent -> HTTP {cr.status_code}")
        names = sorted({c.name for c in jar_cookies(self._session)})
        trace("csrf", f"jar apos consentimento: {', '.join(names) or '(vazio)'}")
        a3 = next((c for c in jar_cookies(self._session) if c.name == "A3"), None)
        if a3 is not None:
            self._cookie = a3
            return True
        return False

    def _get_crumb_csrf(self, timeout=15):
        if self._crumb is not None:
            return self._crumb
        if not self._get_cookie_csrf(timeout):
            return None
        r = self._session.get(f"{Q2}/v1/test/getcrumb", timeout=timeout)
        crumb = r.text
        trace("csrf", f"GET query2/v1/test/getcrumb -> HTTP {r.status_code} "
                      f"{r.headers.get('content-type', '')}")
        if r.status_code == 200 and crumb and "<html>" not in crumb.lower():
            self._crumb = crumb
            trace("csrf", f"crumb = {crumb!r} ({len(crumb)} chars)")
            return crumb
        return None

    # ----------------------------------------------------------------- toggle
    def _toggle(self):
        """Réplica do _set_cookie_strategy: cookie e crumb zeram JUNTOS."""
        if self._strategy == "csrf":
            # o cliente oficial só limpa quando NÃO há login; o par documentado
            # aqui é o anônimo, então limpar sempre é equivalente
            self._session.cookies.clear()
            self._strategy = "basic"
        else:
            self._strategy = "csrf"
        self._cookie = None
        self._crumb = None
        trace("toggle", f"estrategia -> {self._strategy} "
                       f"(cookie e crumb descartados como par atomico)")

    # ---------------------------------------------------------- orquestrador
    def get_cookie_and_crumb(self, timeout=15):
        """Devolve (crumb, estrategia) — como o `_get_cookie_and_crumb` oficial,
        o chamador sabe qual coluna venceu."""
        with self._lock:
            if self._strategy == "csrf":
                crumb = self._get_crumb_csrf(timeout)
                if crumb is None:               # falha -> outra coluna
                    self._toggle()
                    crumb = self._get_crumb_basic(timeout)
            else:
                crumb = self._get_crumb_basic(timeout)
                if crumb is None:
                    self._toggle()
                    crumb = self._get_crumb_csrf(timeout)
            return crumb, self._strategy

    def get(self, url, params=None, timeout=15):
        """Réplica do _make_request: crumb injetado; >=400 -> toggle + retry."""
        if params and "crumb" in params:
            raise ValueError("crumb é injetado pela máquina, não pelo chamador")
        params = dict(params or {})
        crumb, _ = self.get_cookie_and_crumb(timeout)
        if crumb:
            params["crumb"] = crumb
        r = self._session.get(url, params=params, timeout=timeout)
        if r.status_code >= 400:
            trace("rejeitado", f"HTTP {r.status_code} -> toggle + re-aquisicao")
            self._toggle()
            crumb, _ = self.get_cookie_and_crumb(timeout)
            params.pop("crumb", None)
            if crumb:
                params["crumb"] = crumb
            r = self._session.get(url, params=params, timeout=timeout)
        return r


def quote(machine, symbols, host=Q1):
    r = machine.get(f"{host}/v7/finance/quote",
                    params={"symbols": symbols, "lang": "en-US", "region": "US"})
    ok = r.status_code == 200
    body = r.json() if ok else r.text[:200]
    if ok:
        results = body.get("quoteResponse", {}).get("result") or []
        prices = {q["symbol"]: q.get("regularMarketPrice") for q in results}
        trace("consumo", f"HTTP {r.status_code} | {prices}")
    else:
        trace("consumo", f"HTTP {r.status_code} | {body}")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strategy", choices=["basic", "csrf", "both"],
                    default="both")
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA")
    args = ap.parse_args()

    print(f"transporte: {'curl_cffi (impersonate=chrome)' if HAS_CFFI else 'requests (fallback)'}")

    if args.strategy in ("basic", "both"):
        print("\n=== COLUNA basic: fc.yahoo.com -> query1/getcrumb ===")
        m = AuthStateMachine()
        m._strategy = "basic"
        crumb, via = m.get_cookie_and_crumb()
        trace("estado", f"par adquirido pela coluna '{via}'")
        if crumb:
            quote(m, args.symbols, host=Q1)
            # hosts intercambiaveis: crumb emitido por query2 autenticando query1
            r2 = m._session.get(f"{Q2}/v1/test/getcrumb", timeout=15)
            if r2.status_code == 200 and r2.text:
                trace("basic", f"getcrumb em query2 -> {r2.text!r} "
                              f"({len(r2.text)} chars)")
                rr = m._session.get(
                    f"{Q1}/v7/finance/quote",
                    params={"symbols": args.symbols, "crumb": r2.text,
                            "lang": "en-US", "region": "US"}, timeout=15)
                ok = rr.status_code == 200
                trace("failover", f"crumb de query2 em quote(query1) -> "
                                f"HTTP {rr.status_code} "
                                f"({'intercambiavel' if ok else 'rejeitado'})")

    if args.strategy in ("csrf", "both"):
        print("\n=== COLUNA csrf: guce/consent -> collectConsent -> copyConsent -> query2/getcrumb ===")
        m2 = AuthStateMachine()
        m2._strategy = "csrf"
        crumb2, via2 = m2.get_cookie_and_crumb()
        trace("estado", f"par adquirido pela coluna '{via2}'")
        if crumb2:
            # cookie+crumb de outra sessao -> 401 (par atomico)
            print("\n--- par atomico: crumb de outra sessao + cookie de sessao nova ---")
            m3 = AuthStateMachine()
            m3._strategy = "basic"
            m3._get_cookie_basic()          # so o cookie, sem crumb
            r = m3._session.get(
                f"{Q1}/v7/finance/quote",
                params={"symbols": args.symbols, "crumb": crumb2,
                        "lang": "en-US", "region": "US"}, timeout=15)
            trace("rejeitado" if r.status_code in (401, 403) else "consumo",
                  f"HTTP {r.status_code} | {r.text[:160]}")

            # resposta >= 400: toggle + re-aquisicao + retry (caminho de _make_request)
            print("\n--- resposta >= 400: crumb envenenado -> 401 -> toggle -> retry ---")
            m4 = AuthStateMachine()
            m4._strategy = "basic"
            m4.get_cookie_and_crumb()        # adquire par valido
            m4._crumb = "GARBAGE1234"        # envenena so o crumb (11 chars)
            rr = m4.get(f"{Q1}/v7/finance/quote",
                        params={"symbols": args.symbols,
                                "lang": "en-US", "region": "US"})
            trace("retry", f"apos toggle+re-aquisicao -> HTTP {rr.status_code}")
            if rr.status_code == 200:
                res = rr.json().get("quoteResponse", {}).get("result") or []
                trace("retry", f"recuperado: "
                              f"{ {q['symbol']: q.get('regularMarketPrice') for q in res} }")


if __name__ == "__main__":
    sys.exit(main())
