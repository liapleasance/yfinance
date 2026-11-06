#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Captura o fluxo de consentimento (estado csrf da máquina) para virar
transcrição no auth_cookie_a3_crumb.md.

O estado csrf só existe quando o servidor decide que a sessão precisa de
consentimento — a decisão viaja ASSINADA dentro do A3 (tag 05, GUC), então
não dá para forjar nem editar o cookie: só um egress de jurisdição que exija
consentimento (UE/UK) faz a edge emitir uma identidade NOT_CONSENTED.

USO
    python consent_capture.py                 # diagnostica o estado da sessão
    python consent_capture.py --accept        # aceita o consentimento e segue
                                              # (só rode se você concorda com os
                                              #  termos apresentados na página)
    python consent_capture.py --accept --out consent_transcript.md

A saída é um transcript markdown com valores truncados, pronto para eu
transformar em §7.5 do documento.
"""
import argparse
import datetime
import os
import re
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PACOTE = os.path.join(AQUI, "..", "yfinance", "auth_cookie_a3_crumb")
sys.path.insert(0, os.path.abspath(PACOTE))
import yfinance_legacy as yf  # noqa: E402


def tr(valor: str, n: int = 24) -> str:
    """Trunca valores sensíveis mantendo o prefixo reconhecível."""
    if not valor:
        return ""
    return valor[:n] + "..." if len(valor) > n else valor


class Captura:
    def __init__(self) -> None:
        self.linhas = []
        # cofre temporário: não toca no jar do usuário
        self.jar = os.path.join(tempfile.gettempdir(), "consent_capture.json")
        self.sess = yf.YahooFinanceSession(jar_path=self.jar, prefer_cffi=True)
        self.form = None
        self.action = None

    def p(self, texto: str = "") -> None:
        print(texto)
        self.linhas.append(texto)

    # ── 0. sessão e diagnóstico do estado ────────────────────────────────
    def passo0(self) -> bool:
        self.p("## 0. Sessão nova e estado de consentimento\n")
        r = self.sess.transport.request("GET", yf.FC_YAHOO,
                                        headers=self.sess.profile.navigate_headers(),
                                        allow_redirects=False, timeout=15.0)
        self.sess.vault.absorb(self.sess.transport.session)
        self.p(f"- `GET {yf.FC_YAHOO}` → **HTTP {r.status_code}** (404 = normal)")
        for c in r.headers.get("set-cookie", "").split(", "):
            nome = c.split("=", 1)[0]
            if nome in ("A1", "A3", "A1S"):
                self.p(f"- `Set-Cookie: {nome}=` presente")
        a3 = self.sess.vault.a3
        if not a3:
            self.p("\n**SEM A3** — investigar rede/TLS antes de continuar.")
            return False
        d = self.sess.forensics.decode(a3)
        req, motivo = self.sess.forensics.consent_check_required(d)
        self.p(f"\nA3 decodificado (tag 05):")
        self.p(f"- `gucJurisdiction` = **{d.get('gucJurisdiction')}** "
               f"(idx {d.get('gucJurisdiction_idx')})")
        self.p(f"- `gucToS` = **{d.get('gucToS')}** · `gucUserType` = {d.get('gucUserType')}")
        self.p(f"- `gucConsented` = **{d.get('gucConsented')}** · "
               f"`gucConsentVersion` = {d.get('gucConsentVersion')}")
        self.p(f"- gate `isConsentCheckRequired` → **{'SIM' if req else 'NÃO'}** ({motivo})")
        if not req:
            self.p("\n**A sessão não exige consentimento neste egress.** O estado csrf não é")
            self.p("alcançável daqui — rode de um egress de jurisdição UE/UK (o GUC vem do IP).")
            return False
        return True

    # ── 1. rota de consentimento ─────────────────────────────────────────
    def passo1(self) -> None:
        self.p("\n## 1. Rota de consentimento\n")
        self.p("```http")
        self.p("GET https://guce.yahoo.com/consent?src=finance HTTP/2")
        self.p("```")
        url = yf.GUCE_CONSENT
        params = {"src": "finance"}
        for salto in range(1, 6):
            r = self.sess.transport.request(
                "GET", url, params=params,
                headers=self.sess.profile.navigate_headers(),
                allow_redirects=False, timeout=20.0)
            self.sess.vault.absorb(self.sess.transport.session)
            params = None
            loc = r.headers.get("location", "")
            self.p(f"- salto {salto}: **HTTP {r.status_code}**"
                   + (f" → `{tr(loc, 90)}`" if loc else ""))
            if r.status_code in (301, 302, 303, 307, 308) and loc:
                url = yf.urljoin(url, loc) if hasattr(yf, "urljoin") else loc
                continue
            m = self.sess.consent._FORM_RE.search(r.text or "")
            if r.status_code == 200 and m:
                self.action = m.group(1)
                self.form = r.text
                self.p(f"\nPágina de consentimento servida — `<form action=\"{tr(self.action, 80)}\">`")
                self.p("\nInputs hidden encontrados:\n")
                for tag in yf.ConsentHandshaker._INPUT_RE.findall(r.text or ""):
                    mn = yf.ConsentHandshaker._ATTR_NAME_RE.search(tag)
                    mv = yf.ConsentHandshaker._ATTR_VALUE_RE.search(tag)
                    if mn:
                        self.p(f"- `{mn.group(1)}` = `{tr(mv.group(1) if mv else '', 30)}`")
                nomes = {yf.ConsentHandshaker._ATTR_NAME_RE.search(t).group(1)
                         for t in yf.ConsentHandshaker._INPUT_RE.findall(r.text or "")
                         if yf.ConsentHandshaker._ATTR_NAME_RE.search(t)}
                for chave in ("csrfToken", "sessionId", "consentUUID"):
                    self.p(f"- contém `{chave}`: **{'sim' if chave in nomes else 'não'}**")
                break
            self.p("- (sem formulário nesta resposta)")
            break

    # ── 2. aceite ────────────────────────────────────────────────────────
    def passo2(self, aceitar: bool) -> None:
        if not self.form:
            self.p("\n## 2. Aceite\n\nSem formulário — nada a postar (já consentido ou bloqueio).")
            return
        self.p("\n## 2. Aceite (POST no collectConsent)\n")
        if not aceitar:
            self.p("`--accept` não passado: o POST **não** foi executado.")
            self.p(f"Para capturar, rode: `python {os.path.basename(__file__)} --accept`")
            return
        self.p("```http")
        self.p("POST https://consent.yahoo.com/v2/collectConsent HTTP/2")
        self.p("Content-Type: application/x-www-form-urlencoded")
        self.p("Origin: https://guce.yahoo.com")
        self.p("```")
        ok = self.sess.consent._accept(
            yf.HttpResponse(status_code=200, url=yf.GUCE_CONSENT,
                            headers={"content-type": "text/html"},
                            content=self.form.encode()),
            yf.GUCE_CONSENT)
        self.p(f"- aceite postado: **{ok}**")
        self.p(f"- `copyConsent` → **HTTP {self.sess.consent.last_copy_status}**")
        d = self.sess.forensics.decode(self.sess.vault.a3 or "")
        self.p(f"- A3 após o aceite: `gucConsented` = **{d.get('gucConsented')}**, "
               f"`gucConsentVersion` = {d.get('gucConsentVersion')}")

    # ── 3. novo crumb ────────────────────────────────────────────────────
    def passo3(self) -> None:
        self.p("\n## 3. Novo crumb (o anterior morreu com a sessão pré-consentimento)\n")
        for host in yf.QUERY_HOSTS:
            try:
                r = self.sess.transport.request(
                    "GET", f"https://{host}{yf.GETCRUMB_PATH}",
                    headers=self.sess.profile.api_headers(accept="text/plain"),
                    timeout=15.0)
                self.p(f"- `GET https://{host}{yf.GETCRUMB_PATH}` → **HTTP {r.status_code}**"
                       f" · crumb `{tr((r.text or '').strip(), 6)}`")
                if r.status_code == 200:
                    break
            except Exception as e:
                self.p(f"- `{host}` falhou: {e!r}")

    def salvar(self, caminho: str) -> None:
        cab = (f"# Transcrição — estado csrf (consentimento)\n\n"
               f"Gerado por `consent_capture.py`. Valores truncados; sem dados de sessão integrais.\n")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(cab + "\n".join(self.linhas) + "\n")
        print(f"\nTranscrição salva em: {caminho}")
        if os.path.exists(self.jar):
            os.unlink(self.jar)


def main() -> int:
    ap = argparse.ArgumentParser(description="Captura o fluxo de consentimento (estado csrf)")
    ap.add_argument("--accept", action="store_true",
                    help="posta o aceite do consentimento (só rode se concordar com os termos)")
    ap.add_argument("--out", default="consent_transcript.md", help="arquivo da transcrição")
    a = ap.parse_args()

    c = Captura()
    try:
        if not c.passo0():
            c.salvar(a.out)
            return 2
        c.passo1()
        c.passo2(a.accept)
        c.passo3()
        c.salvar(a.out)
        return 0
    finally:
        c.sess.close()


if __name__ == "__main__":
    sys.exit(main())
