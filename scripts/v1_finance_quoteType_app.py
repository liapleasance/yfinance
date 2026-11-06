#!/usr/bin/env python3
"""
v1_finance_quoteType_app.py - app de terminal e cliente CLI para GET /v1/finance/quoteType/{symbol}.

Só biblioteca padrão. Não exige crumb nem cookie.

O QUE FOI VERIFICADO NO BUNDLE (leitura do código do cliente web):
- caminho /v1/finance/quoteType/{símbolo} (convenção path, usada pelo carregador);
- convenção query /v1/finance/quoteType/?symbol=... com barra final (usada pelo gráfico);
- parâmetros: formatted, mockPrivateCompany, mockOvernightPrice, enablePrivateCompany,
  overnightPrice (este último só com a flag enableOvernight);
- regra de caracteres: [a-zA-Z0-9^.$_+=*&:@~-];
- pool público de hosts: query1 e query2 (o gráfico sorteia um por chamada);
- timeout de 15 s no carregador e de 30 s no gráfico; 3 tentativas em timeout no gráfico;
- cache de 60 s do quoteType (cabeçalhos x-cache / x-cache-ttl, com a flag enableQuoteTypeCaching);
- o cliente não envia crumb nesta chamada.

O QUE NÃO FOI VERIFICADO (depende do servidor; não há rede neste ambiente):
- conteúdo real da resposta, comportamento de formatted, ignorar crumb, 429 por User-Agent,
  existência pública do host iquery, sufixo de messageBoardId por idioma, headers de cache.
  Esses pontos estão no documento de engenharia reversa e não foram confirmados aqui.

BUG DO CLIENTE OFICIAL (verificado com node):
- a regra de caracteres tem a flag g. Em JavaScript, test() com essa flag guarda lastIndex
  entre chamadas, então um símbolo inválido pode passar logo depois de um símbolo rejeitado.
  Este script não reproduz o bug: a validação não tem estado.

Uso:
    python3 v1_finance_quoteType_app.py            (abre o terminal interativo; duplo-clique funciona)
    python3 v1_finance_quoteType_app.py --ascii --sem-cores --no-pause
    python3 v1_finance_quoteType_app.py AAPL
    python3 v1_finance_quoteType_app.py AAPL --convencao query
    python3 v1_finance_quoteType_app.py "ES=F" --overnight
    python3 v1_finance_quoteType_app.py AAPL --json
    python3 v1_finance_quoteType_app.py --autoteste
"""
import argparse
import io
import json
import re
import os
import random
import shutil
import sys
import time
import datetime
import urllib.error
import urllib.parse
import urllib.request

HOSTS_PUBLICOS = [
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]
HOST_INTERNO = "https://iquery.finance.yahoo.com"  # fora do pool público do cliente

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

TIMEOUT_CARREGADOR = 15  # s
TENTATIVAS_TIMEOUT = 3   # tentativas no mesmo host em timeout (como o gráfico)

_INVALIDO = re.compile(r"[^a-zA-Z0-9^.$_+=*&:@~-]")  # sem flag g: sem estado
CODIGOS_SEM_TROCA_DE_HOST = {400, 404, 405}  # tratados como determinísticos aqui (escolha deste script)


class ErroQuoteType(RuntimeError):
    """Falha na chamada ou resposta inesperada."""


def simbolo_valido(simbolo):
    """True se o símbolo só usa caracteres da regra do cliente (após decodificar)."""
    if not simbolo:
        return False
    return _INVALIDO.search(urllib.parse.unquote(simbolo)) is None


def montar_parametros(convencao, lang, region, overnight, mock_private, enable_private, mock_overnight):
    if convencao == "query":  # o mesmo conjunto que o gráfico envia
        p = {"lang": lang, "region": region,
             "enablePrivateCompany": "true" if enable_private else "false"}
        if overnight:
            p["overnightPrice"] = "true"
        return p
    p = {"formatted": "true"}  # o carregador envia formatted=true
    if mock_private:
        p["mockPrivateCompany"] = "true"
    if mock_overnight:
        p["mockOvernightPrice"] = "true"
    if enable_private:
        p["enablePrivateCompany"] = "true"
    if overnight:
        p["overnightPrice"] = "true"
    p["lang"] = lang
    p["region"] = region
    return p


def montar_url(host, simbolos, convencao, parametros):
    if convencao == "path":
        # Símbolos já passaram em simbolo_valido: todos são seguros no caminho, sem codificar.
        caminho = "/v1/finance/quoteType/" + ",".join(simbolos)
        return f"{host}{caminho}?{urllib.parse.urlencode(parametros)}"
    if convencao == "query":
        dados = {"symbol": ",".join(simbolos), **parametros}
        return f"{host}/v1/finance/quoteType/?{urllib.parse.urlencode(dados)}"
    raise ValueError(f"convenção desconhecida: {convencao}")


ULTIMA = {}  # última resposta bem-sucedida: url, bytes crus, ms (usado pelo app)


def _requisitar(url, timeout):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        bruto = resp.read()
    ULTIMA.update(url=url, bytes=bruto, ms=(time.monotonic() - t0) * 1000)
    return bruto.decode("utf-8", "replace")


def buscar_envelope(simbolos, *, convencao="path", lang="en-US", region="US",
                    overnight=False, mock_private=False, enable_private=False,
                    mock_overnight=False, hosts=None, timeout=TIMEOUT_CARREGADOR,
                    tentativas=TENTATIVAS_TIMEOUT):
    """Devolve o envelope cru. Lança ValueError (símbolo inválido) ou ErroQuoteType (rede/servidor)."""
    if not simbolos:
        raise ValueError("nenhum símbolo informado")
    for s in simbolos:
        if not simbolo_valido(s):
            raise ValueError(f"símbolo {s!r} tem caractere fora de [a-zA-Z0-9^.$_+=*&:@~-]")

    parametros = montar_parametros(convencao, lang, region, overnight,
                                   mock_private, enable_private, mock_overnight)
    ultimo_erro = None
    for host in (hosts or HOSTS_PUBLICOS):
        url = montar_url(host, simbolos, convencao, parametros)
        for _ in range(tentativas):
            try:
                corpo = _requisitar(url, timeout)
            except urllib.error.HTTPError as e:
                corpo = e.read().decode("utf-8", "replace")
                if e.code in CODIGOS_SEM_TROCA_DE_HOST:
                    raise ErroQuoteType(f"HTTP {e.code} de {host}: {corpo[:200]}") from e
                ultimo_erro = f"HTTP {e.code} de {host}: {corpo[:120]}"
                break  # troca de host
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                ultimo_erro = f"{host}: {e}"
                if isinstance(e, TimeoutError) or "timed out" in str(e):
                    continue  # tenta de novo no mesmo host
                break  # erro de conexão: troca de host
            try:
                return json.loads(corpo)
            except json.JSONDecodeError as e:
                raise ErroQuoteType(f"resposta não é JSON de {host}: {corpo[:120]!r}") from e
    raise ErroQuoteType(f"todos os hosts falharam; último erro: {ultimo_erro}")


def resolver(simbolos, **kwargs):
    """Devolve (encontrados, faltantes). Símbolos que o servidor omite ficam em faltantes."""
    envelope = buscar_envelope(simbolos, **kwargs)
    erro_fin = (envelope.get("finance") or {}).get("error")
    if erro_fin:
        raise ErroQuoteType(f"erro do servidor: {erro_fin}")
    bloco = envelope.get("quoteType") or {}
    if bloco.get("error"):
        raise ErroQuoteType(f"erro do servidor: {bloco['error']}")
    encontrados = {}
    for item in bloco.get("result") or []:
        s = (item.get("symbol") or "").upper()
        if s:
            encontrados[s] = item
    faltantes = [s.upper() for s in simbolos if s.upper() not in encontrados]
    return encontrados, faltantes


def _imprimir(encontrados, faltantes):
    if not encontrados:
        print("nenhum símbolo resolvido")
    for simbolo, meta in encontrados.items():
        print(f"{simbolo} [{meta.get('quoteType')}] {meta.get('shortName', '')}")
        print(f"  exchange={meta.get('exchange')}  market={meta.get('market')}  "
              f"tz={meta.get('exchangeTimezoneName')} ({meta.get('exchangeTimezoneShortName')})  "
              f"gmtOff={meta.get('gmtOffSetMilliseconds')} ms")
        if "headSymbol" in meta or "underlyingSymbol" in meta:
            print(f"  futuro: underlying={meta.get('underlyingSymbol')} "
                  f"@ {meta.get('underlyingExchangeSymbol')}")
        if "messageBoardId" in meta:
            print(f"  messageBoardId={meta['messageBoardId']}  "
                  f"quartrId={meta.get('quartrId', '(ausente)')}")
    if faltantes:
        print("sem resultado (o servidor omite): " + ", ".join(faltantes))


def autoteste():
    global _requisitar
    falhas = []

    def checa(nome, cond):
        print(("OK    " if cond else "FALHA ") + nome)
        if not cond:
            falhas.append(nome)

    # 1. Validação sem estado
    checa("'A,B' é rejeitado (vírgula)", not simbolo_valido("A,B"))
    checa("'C,D' é rejeitado logo após 'A,B' (bug do cliente não reproduzido)", not simbolo_valido("C,D"))
    checa("'AAPL' é aceito", simbolo_valido("AAPL"))
    checa("'^GSPC' é aceito", simbolo_valido("^GSPC"))
    checa("'ES=F' é aceito", simbolo_valido("ES=F"))
    checa("'PETR4.SA' é aceito", simbolo_valido("PETR4.SA"))
    checa("vazio é rejeitado", not simbolo_valido(""))
    checa("espaço é rejeitado", not simbolo_valido("A B"))

    # 2. Montagem de URL
    u1 = montar_url(HOSTS_PUBLICOS[0], ["ES=F"], "path", {"formatted": "true"})
    checa("convenção path mantém ES=F no caminho",
          u1.startswith("https://query1.finance.yahoo.com/v1/finance/quoteType/ES=F?"))
    u2 = montar_url(HOSTS_PUBLICOS[0], ["^GSPC"], "query", {"lang": "en-US"})
    checa("convenção query usa barra final e codifica ^ como %5E",
          "/v1/finance/quoteType/?symbol=%5EGSPC" in u2)

    # 3. Failover e retry com transporte simulado (sem rede)
    chamadas = []

    def falso_ok_no_query2(url, timeout):
        chamadas.append(url)
        if "query1" in url:
            raise urllib.error.URLError(TimeoutError("timed out"))
        return json.dumps({"quoteType": {"result": [{"symbol": "AAPL", "quoteType": "EQUITY"}],
                                         "error": None}})

    original = _requisitar
    _requisitar = falso_ok_no_query2
    try:
        env = buscar_envelope(["AAPL"], tentativas=2)
        checa("failover para query2 após timeouts",
              env["quoteType"]["result"][0]["symbol"] == "AAPL" and any("query2" in c for c in chamadas))
        checa("retry no mesmo host antes de trocar (2 tentativas em query1)",
              sum("query1" in c for c in chamadas) == 2)
    finally:
        _requisitar = original

    # 4. Símbolo inválido não toca a rede
    chamadas.clear()
    _requisitar = falso_ok_no_query2
    try:
        try:
            buscar_envelope(["A,B"])
            ok = False
        except ValueError:
            ok = True
        checa("símbolo inválido lança ValueError sem rede", ok and not chamadas)
    finally:
        _requisitar = original

    # 5. HTTP 404 não troca de host
    chamadas.clear()

    def falso_404(url, timeout):
        chamadas.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b"Not Found"))

    _requisitar = falso_404
    try:
        try:
            buscar_envelope(["AAPL"])
            ok = False
        except ErroQuoteType:
            ok = True
        checa("HTTP 404 gera erro sem trocar de host", ok and len(chamadas) == 1)
    finally:
        _requisitar = original

    # 6. Resposta vazia vira "faltante"
    _requisitar = lambda url, timeout: json.dumps({"quoteType": {"result": [], "error": None}})
    try:
        enc, falt = resolver(["ZZZZ"])
        checa("símbolo omitido pelo servidor vai para faltantes", enc == {} and falt == ["ZZZZ"])
    finally:
        _requisitar = original

    print()
    print(f"{len(falhas)} falha(s)" if falhas else "todos os testes offline passaram")
    return 1 if falhas else 0


def main_cli(argv=None):
    ap = argparse.ArgumentParser(description="GET /v1/finance/quoteType/{symbol}")
    ap.add_argument("simbolos", nargs="?", help="símbolo ou lista separada por vírgula")
    ap.add_argument("--convencao", choices=["path", "query"], default="path",
                    help="path = como o carregador; query = como o gráfico (padrão: path)")
    ap.add_argument("--lang", default="en-US")
    ap.add_argument("--region", default="US")
    ap.add_argument("--overnight", action="store_true", help="envia overnightPrice=true")
    ap.add_argument("--mock-private", action="store_true")
    ap.add_argument("--enable-private", action="store_true")
    ap.add_argument("--mock-overnight", action="store_true")
    ap.add_argument("--host", choices=["query1", "query2", "iquery"],
                    help="usa só um host (iquery não faz parte do pool público)")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_CARREGADOR)
    ap.add_argument("--json", action="store_true", help="imprime o envelope cru")
    ap.add_argument("--autoteste", action="store_true", help="roda os testes offline")
    args = ap.parse_args(argv)

    if args.autoteste:
        return autoteste()
    if not args.simbolos:
        ap.error("informe o símbolo")

    simbolos = [s.strip() for s in args.simbolos.split(",") if s.strip()]
    hosts = None
    if args.host:
        hosts = [{"query1": HOSTS_PUBLICOS[0], "query2": HOSTS_PUBLICOS[1],
                  "iquery": HOST_INTERNO}[args.host]]
    kwargs = dict(convencao=args.convencao, lang=args.lang, region=args.region,
                  overnight=args.overnight, mock_private=args.mock_private,
                  enable_private=args.enable_private, mock_overnight=args.mock_overnight,
                  hosts=hosts, timeout=args.timeout)
    try:
        if args.json:
            print(json.dumps(buscar_envelope(simbolos, **kwargs), indent=1, ensure_ascii=False))
            return 0
        encontrados, faltantes = resolver(simbolos, **kwargs)
    except (ValueError, ErroQuoteType) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    _imprimir(encontrados, faltantes)
    return 0



# =====================================================================================
# TERMINAL INTERATIVO (estilo Bloomberg). Sem argumentos abre o terminal e só fecha com SAIR;
# ao sair espera ENTER (use --no-pause para desligar). Com argumentos, o CLI antigo continua
# igual (main_cli).
#
# O que o app cobre do endpoint (lido no bundle):
# - símbolo único ou lote por vírgula, validado pela regra do cliente antes de tocar a rede;
# - convenção path (carregador) e query (gráfico); lang, region e as flags overnightPrice,
#   enablePrivateCompany, mockPrivateCompany e mockOvernightPrice;
# - host sorteado entre query1, query2 e iquery a cada chamada, com failover para os outros;
# - timeout de 15 s e 3 tentativas em timeout; cache local opcional de 60 s (TTL do cliente);
# - derivados que o cliente faz com a resposta: fuso do gráfico (mapa de 26 aliases),
#   arquivo de calendário de pregão a partir de `market` e cripto sem calendário.
#
# Sem renovação de credenciais: o cliente web não envia crumb nem cookie neste endpoint.
# Backoff em 429/503 e a medição de latência são escolhas deste app, não do cliente oficial.
# =====================================================================================

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ESTILO = {"cor": True, "ascii": False}

# Paleta (referência de design): tons truecolor e aproximação de 256 cores.
PALETA = {
    "ambar": ((255, 160, 40), 214), "amarelo": ((255, 214, 0), 220), "verde": ((0, 200, 83), 41),
    "vermelho": ((255, 67, 61), 203), "ciano": ((0, 212, 255), 45), "branco": ((255, 255, 255), 15),
    "cinza": ((160, 160, 160), 248), "cinza2": ((128, 128, 128), 244), "linha": ((74, 74, 74), 240),
    "fundo": ((28, 28, 28), 234), "preto": ((0, 0, 0), 16),
}
_ALIAS_COR = {"azul": "ciano", "magenta": "ambar", "laranja": "ambar"}

ASSET_CALENDARIO = "https://s.yimg.com/uc/finance/cosaic/temporaryAssets/{market}_6.0.55.json"
# Mapa de fuso aplicado pelo gráfico antes de usar o calendário (26 aliases, lidos no bundle).
ALIAS_FUSO = {
    "America/Toronto": "America/New_York", "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
    "America/Montreal": "America/New_York", "America/Lima": "America/Bogota", "Asia/Manila": "Asia/Taipei",
    "Asia/Singapore": "Asia/Kuala_Lumpur", "Asia/Calcutta": "Asia/Kolkata", "Asia/Colombo": "Asia/Kolkata",
    "Asia/Jakarta": "Asia/Bangkok", "Asia/Qatar": "Asia/Riyadh", "Asia/Kuwait": "Asia/Riyadh",
    "Europe/Paris": "Europe/Amsterdam", "Europe/Rome": "Europe/Amsterdam",
    "Europe/Copenhagen": "Europe/Amsterdam", "Europe/Dublin": "Europe/London",
    "Europe/Stockholm": "Europe/Amsterdam", "Europe/Madrid": "Europe/Brussels",
    "Europe/Zurich": "Europe/Berlin", "Europe/Lisbon": "Europe/London", "Europe/Oslo": "Europe/Kaliningrad",
    "Europe/Budapest": "Europe/Belgrade", "Europe/Prague": "Europe/Belgrade",
    "Europe/Warsaw": "Europe/Belgrade", "Europe/Riga": "Europe/Helsinki",
    "Europe/Tallinn": "Europe/Helsinki", "Europe/Vilnius": "Europe/Helsinki",
}
TTL_CACHE = 60  # s, mesmo TTL do cliente (x-cache-ttl 60000)

HOSTS_ALVO = {"query1": HOSTS_PUBLICOS[0], "query2": HOSTS_PUBLICOS[1], "iquery": HOST_INTERNO}
CFG = {"convencao": "path", "lang": "en-US", "region": "US", "overnight": False,
       "mock_private": False, "enable_private": False, "mock_overnight": False,
       "cache": False, "timeout": TIMEOUT_CARREGADOR, "user_agent": USER_AGENT}
ESTADO = {"bruto": None, "simbolos": "META", "status": None}
CACHE = {}
_dormir = time.sleep


class Saida(Exception):
    """Entrada encerrada (EOF): sai do terminal sem traceback."""


def habilitar_terminal():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if os.name == "nt":
        os.system("")  # ativa sequências VT no console do Windows


# ---------- cor e desenho ----------
def _truecolor():
    return os.name == "nt" or os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def _codigo(cor, fundo=False):
    cor = _ALIAS_COR.get(cor, cor)
    if cor == "negrito":
        return "1"
    rgb, c256 = PALETA.get(cor, PALETA["branco"])
    base = 48 if fundo else 38
    return f"{base};2;{rgb[0]};{rgb[1]};{rgb[2]}" if _truecolor() else f"{base};5;{c256}"


def pintar(t, cor):
    if not ESTILO["cor"]:
        return str(t)
    return f"\x1b[{_codigo(cor)}m{t}\x1b[0m"


def tag(t, cor):
    """Tecla de função: texto preto em negrito sobre fundo colorido."""
    if not ESTILO["cor"]:
        return f"[{str(t).strip()}]"
    return f"\x1b[1;{_codigo('preto')};{_codigo(cor, True)}m{t}\x1b[0m"


def larg(t):
    return len(ANSI_RE.sub("", str(t)))


def preencher(t, n):
    return str(t) + " " * max(0, n - larg(t))


def cortar(t, n):
    plano = ANSI_RE.sub("", str(t))
    return plano if len(plano) <= n else plano[:max(1, n - 1)] + "…"


def largura():
    return max(60, min(shutil.get_terminal_size((100, 30)).columns, 120))


def _caixa_chars():
    return ("+", "+", "+", "+", "-", "|") if ESTILO["ascii"] else ("┌", "┐", "└", "┘", "─", "│")


def caixa(titulo, linhas, total=None, cor="linha"):
    """Painel de bordas retas. `total` fixa a largura externa (para painéis lado a lado)."""
    tl, tr, bl, br, h, v = _caixa_chars()
    corpo = [str(x) for x in linhas]
    titulo = titulo.upper()
    if total is None:
        w = max([larg(titulo) + 2] + [larg(x) for x in corpo])
        w = min(w, max(24, largura() - 4))
    else:
        w = max(20, total - 4)
    corpo = [x if larg(x) <= w else cortar(x, w) for x in corpo]
    interno = w + 2
    topo = (pintar(tl + h + " ", cor) + pintar(titulo, "ambar") +
            pintar(" " + h * max(0, interno - 3 - larg(titulo)) + tr, cor))
    out = [topo]
    for x in corpo:
        out.append(pintar(v, cor) + " " + preencher(x, w) + " " + pintar(v, cor))
    out.append(pintar(bl + h * interno + br, cor))
    return "\n".join(out)


def tabela(cabecalho, linhas, maximo=36):
    sep, cruz, h = (" | ", "-+-", "-") if ESTILO["ascii"] else (" │ ", "─┼─", "─")
    dados = [[c if larg(c) <= maximo else cortar(c, maximo) for c in l] for l in linhas]
    n = len(cabecalho)
    ws = [max(larg(x) for x in [cabecalho[i]] + [l[i] for l in dados]) for i in range(n)]
    out = [sep.join(pintar(preencher(cabecalho[i].upper(), ws[i]), "cinza2") for i in range(n)),
           pintar(cruz.join(h * ws[i] for i in range(n)), "linha")]
    for l in dados:
        out.append(sep.join(preencher(l[i], ws[i]) for i in range(n)))
    return "\n".join(out)


def lado_a_lado(a, b, folga=1):
    la, lb = a.split("\n"), b.split("\n")
    wa = max(larg(x) for x in la)
    n = max(len(la), len(lb))
    la += [" " * wa] * (n - len(la))
    lb += [""] * (n - len(lb))
    return "\n".join(preencher(x, wa) + " " * folga + y for x, y in zip(la, lb))


def barra(esq, dir_):
    """Barra de largura total: âmbar com texto preto (cabeçalho)."""
    w = largura()
    txt = (esq + " " * max(1, w - len(esq) - len(dir_)) + dir_)[:w]
    if not ESTILO["cor"]:
        return txt
    return f"\x1b[1;{_codigo('preto')};{_codigo('ambar', True)}m{txt}\x1b[0m"


def barra_status(segmentos, dir_):
    """Barra escura com segmentos coloridos [(texto, cor)] e texto à direita."""
    w = largura()
    plano = "".join(t for t, _ in segmentos)
    folga = " " * max(1, w - len(plano) - len(dir_))
    if not ESTILO["cor"]:
        return (plano + folga + dir_)[:w]
    bg = _codigo("fundo", True)
    partes = [f"\x1b[{bg};{_codigo(c)}m{t}" for t, c in segmentos]
    partes.append(f"\x1b[{bg};{_codigo('cinza2')}m{folga}{dir_}\x1b[0m")
    return "".join(partes)


def limpar():
    if ESTILO["cor"] and sys.stdout.isatty():
        print("\x1b[2J\x1b[H", end="")
    else:
        print()


# ---------- formatação pt-BR ----------
def fmt_num(v, casas=0):
    s = f"{v:,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_pct(v, casas=2):
    return fmt_num(v, casas) + "%"


def fmt_epoch(v):
    if v > 1e11:  # milissegundos
        v = v / 1000.0
    return datetime.datetime.fromtimestamp(v).strftime("%d/%m/%Y %H:%M:%S")


def to_int(v):
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return None


def fmt_valor(chave, v):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, str) and chave.endswith("Milliseconds") and to_int(v) is not None:
        v = to_int(v)  # a resposta real traz o offset como string ("-14400000")
    if isinstance(v, (int, float)):
        if chave.endswith("Milliseconds"):
            horas = f"{v / 3600000:+.1f}".replace(".", ",")
            return f"{fmt_num(v)} ms ({horas} h)"
        low = chave.lower()
        if ("time" in low or "date" in low) and 9e8 < v < 4e12:  # heurística de epoch
            return fmt_epoch(v)
        return fmt_num(v, 0 if isinstance(v, int) else 2)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


# ---------- entrada ----------
def ler(prompt, padrao=""):
    try:
        r = input(prompt)
    except EOFError:
        raise Saida()
    r = r.strip()
    return r or padrao


def ler_simbolos():
    bruto = ler(f"Símbolos separados por vírgula [{ESTADO['simbolos']}]: ", ESTADO["simbolos"])
    ESTADO["simbolos"] = bruto
    return [s.strip() for s in bruto.replace(" ", ",").split(",") if s.strip()]


def aviso(msg):
    print(pintar(msg, "amarelo"))


def erro(msg):
    print(pintar(msg, "vermelho"))


def ok(msg):
    print(pintar(msg, "verde"))


def _registrar_status(ok_, msg="", origem="rede"):
    if not ok_:
        ESTADO["status"] = {"ok": False, "msg": msg}
    elif origem == "cache":
        ESTADO["status"] = {"ok": True, "origem": "cache"}
    elif ULTIMA.get("bytes") is not None:
        ESTADO["status"] = {"ok": True, "origem": "rede", "ms": ULTIMA.get("ms", 0),
                            "bytes": len(ULTIMA["bytes"]),
                            "host": urllib.parse.urlparse(ULTIMA.get("url", "")).netloc or "—"}


def acao(fn):
    """Executa uma ação sem derrubar o app e atualiza a barra de status."""
    ULTIMA.clear()
    ESTADO["origem"] = "rede"
    try:
        fn()
        _registrar_status(True, origem=ESTADO.get("origem", "rede"))
    except Saida:
        raise
    except KeyboardInterrupt:
        print()
        aviso("Ação cancelada (Ctrl+C).")
    except (ValueError, ErroQuoteType) as e:
        erro(f"ERRO: {e}")
        _registrar_status(False, str(e))
    except Exception as e:  # rede, I/O, qualquer outra coisa: nunca fecha o app
        erro(f"FALHA inesperada ({type(e).__name__}): {e}")
        _registrar_status(False, f"{type(e).__name__}: {e}")
        if os.environ.get("QT_DEBUG"):
            import traceback
            traceback.print_exc()


# ---------- rede ----------
def _kw():
    """Parâmetros da consulta. O host inicial é sorteado entre os 3 a cada chamada;
    os outros dois ficam como failover (buscar_envelope percorre a lista na ordem)."""
    hosts = list(HOSTS_ALVO.values())
    random.shuffle(hosts)
    return dict(convencao=CFG["convencao"], lang=CFG["lang"], region=CFG["region"],
                overnight=CFG["overnight"], mock_private=CFG["mock_private"],
                enable_private=CFG["enable_private"], mock_overnight=CFG["mock_overnight"],
                hosts=hosts, timeout=CFG["timeout"])


def com_backoff(fn, tentativas=5):
    """Repete em 429/503 com espera 2^n s (1, 2, 4, 8). Escolha deste app."""
    for n in range(tentativas):
        try:
            return fn()
        except ErroQuoteType as e:
            m = str(e)
            if n < tentativas - 1 and ("HTTP 429" in m or "HTTP 503" in m):
                espera = 2 ** n
                aviso(f"  {cortar(m, 70)} -> nova tentativa em {espera}s ({n + 2}/{tentativas})")
                _dormir(espera)
                continue
            raise


def _chave_cache(simbolo):
    return (simbolo.upper(), CFG["lang"], CFG["region"], CFG["overnight"], CFG["enable_private"],
            CFG["convencao"])


def obter(simbolos):
    """Devolve (encontrados, faltantes, do_cache). Com o cache ligado, símbolos consultados há
    menos de 60 s não vão à rede."""
    agora = time.monotonic()
    achados, pendentes = {}, []
    for s in simbolos:
        ent = CACHE.get(_chave_cache(s)) if CFG["cache"] else None
        if ent and agora - ent[0] < TTL_CACHE:
            achados[s.upper()] = ent[1]
        else:
            pendentes.append(s)
    do_cache = set(achados)
    faltantes = []
    if pendentes:
        enc, faltantes = com_backoff(lambda: resolver(pendentes, **_kw()))
        ESTADO["bruto"] = ULTIMA.get("bytes", ESTADO["bruto"])
        for k, v in enc.items():
            CACHE[_chave_cache(k)] = (agora, v)
        achados.update(enc)
    else:
        ESTADO["origem"] = "cache"
    ordem = []
    for s in simbolos:
        if s.upper() in achados and s.upper() not in [o.upper() for o in ordem]:
            ordem.append(s.upper())
    return {k: achados[k] for k in ordem}, faltantes, do_cache


# ---------- derivados do cliente ----------
def fuso_grafico(tz):
    return ALIAS_FUSO.get(tz, tz) if tz else tz


def calendario(meta):
    """Arquivo de calendário que o gráfico carregaria; cripto não aplica calendário."""
    if meta.get("quoteType") == "CRYPTOCURRENCY":
        return "nenhum (cripto, 24 h)"
    mercado = meta.get("market")
    return f"{mercado}_6.0.55.json" if mercado else "—"


def hora_na_bolsa(gmt_ms):
    if gmt_ms is None:
        return "—"
    agora = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(milliseconds=gmt_ms)
    return agora.strftime("%H:%M:%S")


# ---------- telas ----------
def _kv(rotulo, valor, cor="branco"):
    return pintar(f"{rotulo:<19}", "cinza") + pintar(valor, cor)


def _flag(v):
    if v is None:
        return pintar("—", "cinza2")
    if ESTILO["ascii"]:
        return pintar("[x] SIM", "verde") if v else pintar("[ ] NÃO", "cinza2")
    return pintar("● SIM", "verde") if v else pintar("○ NÃO", "cinza2")


def _kvf(rotulo, v):
    return pintar(f"{rotulo:<19}", "cinza") + _flag(v)


CAMPOS_CONHECIDOS = {"symbol", "quoteType", "shortName", "longName", "exchange", "market",
                     "exchangeTimezoneName", "exchangeTimezoneShortName", "gmtOffSetMilliseconds",
                     "isEsgPopulated", "hasSelerityEarnings", "selerityIsGaap", "messageBoardId",
                     "quartrId", "headSymbol", "underlyingSymbol", "underlyingExchangeSymbol"}


def cartao(simbolo, m, do_cache=False):
    gmt = to_int(m.get("gmtOffSetMilliseconds"))
    tz = m.get("exchangeTimezoneName")
    ident = [_kv("Tipo", str(m.get("quoteType", "—")), "amarelo"),
             _kv("Nome curto", str(m.get("shortName", "—"))),
             _kv("Nome legal", str(m.get("longName", "(ausente)"))),
             _kv("Exchange", str(m.get("exchange", "—"))),
             _kv("Mercado", str(m.get("market", "—"))),
             _kv("messageBoardId", str(m.get("messageBoardId", "(ausente)"))),
             _kv("quartrId", str(m.get("quartrId", "(ausente)")))]
    if any(k in m for k in ("headSymbol", "underlyingSymbol", "underlyingExchangeSymbol")):
        ident += [_kv("headSymbol", str(m.get("headSymbol", "—"))),
                  _kv("underlyingSymbol", str(m.get("underlyingSymbol", "—"))),
                  _kv("underlyingExchange", str(m.get("underlyingExchangeSymbol", "—")))]
    graf = fuso_grafico(tz)
    sessao = [_kv("Fuso da bolsa", str(tz or "—")),
              _kv("Abreviação", str(m.get("exchangeTimezoneShortName", "—"))),
              _kv("Offset GMT", fmt_valor("gmtOffSetMilliseconds", gmt) if gmt is not None else "—"),
              _kv("Hora na bolsa", hora_na_bolsa(gmt), "ciano"),
              _kv("Fuso no gráfico", str(graf or "—") + (" (alias)" if tz and graf != tz else "")),
              _kv("Calendário", calendario(m)),
              _kvf("ESG populado", m.get("isEsgPopulated")),
              _kvf("Earnings Selerity", m.get("hasSelerityEarnings")),
              _kvf("Selerity GAAP", m.get("selerityIsGaap"))]
    for k, v in m.items():
        if k not in CAMPOS_CONHECIDOS:
            sessao.append(_kv(k, fmt_valor(k, v)))
    nome = m.get("longName") or m.get("shortName") or ""
    titulo = (pintar(simbolo, "ambar") + "  " + pintar(nome, "branco") + "  " +
              tag(f" {m.get('quoteType', '?')} ", "amarelo") +
              ("  " + pintar("cache", "cinza2") if do_cache else ""))
    meio = (largura() - 1) // 2
    altura = max(len(ident), len(sessao))
    ident += [""] * (altura - len(ident))
    sessao += [""] * (altura - len(sessao))
    esq, dir_ = caixa("Identificação", ident, total=meio), caixa("Sessão e flags", sessao, total=meio)
    corpo = lado_a_lado(esq, dir_) if largura() >= 90 else esq + "\n" + dir_
    return titulo + "\n" + corpo


def resumo(encontrados):
    linhas = []
    for s, m in encontrados.items():
        gmt = m.get("gmtOffSetMilliseconds")
        linhas.append([pintar(s, "ambar"), str(m.get("quoteType", "—")), str(m.get("shortName", "—")),
                       str(m.get("exchange", "—")), str(m.get("market", "—")),
                       str(m.get("exchangeTimezoneName", "—")),
                       fmt_valor("gmtOffSetMilliseconds", gmt) if gmt is not None else "—"])
    return tabela(["Símbolo", "Tipo", "Nome", "Exchange", "Mercado", "Fuso", "GMT"], linhas)


def mostrar_resultado(encontrados, faltantes, do_cache=()):
    if len(encontrados) > 3:
        print(resumo(encontrados))  # lote grande: tabela compacta
    for s, m in (encontrados.items() if len(encontrados) <= 3 else []):
        print(cartao(s, m, s in do_cache))
        print()
    for s in faltantes:
        print(pintar("✖ " if not ESTILO["ascii"] else "x ", "vermelho") + pintar(s, "ambar") +
              pintar("  sem resultado (o cliente trataria como 404)", "cinza"))


def tela_consulta(simbolos=None):
    simbolos = simbolos or ler_simbolos()
    enc, falt, do_cache = obter(simbolos)
    mostrar_resultado(enc, falt, do_cache)


def tela_comparador(simbolos=None):
    simbolos = simbolos if simbolos and len(simbolos) > 1 else ler_simbolos()
    if len(simbolos) < 2:
        raise ValueError("informe pelo menos 2 símbolos")
    enc, falt, _ = obter(simbolos)
    cols = list(enc)
    if not cols:
        aviso("Nenhum símbolo resolvido.")
    else:
        chaves = []
        for s in cols:
            for k, v in enc[s].items():
                if not isinstance(v, (dict, list)) and k not in chaves:
                    chaves.append(k)
        linhas = []
        for k in chaves:
            vals = [fmt_valor(k, enc[s].get(k)) for s in cols]
            dif = len(set(vals)) > 1
            cel = [pintar(cortar(v, 28), "ambar" if dif else "branco") for v in vals]
            linhas.append([pintar(k, "ambar" if dif else "cinza")] + cel)
        print(tabela(["Campo"] + cols, linhas, 40))
    for s in falt:
        print(pintar("✖ " if not ESTILO["ascii"] else "x ", "vermelho") + pintar(s, "ambar") +
              pintar("  sem resultado", "cinza"))


def tela_exportar():
    if ESTADO["bruto"] is None:
        raise ValueError("nada para exportar: faça uma consulta na rede primeiro")
    padrao = "quoteType_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    caminho = ler(f"Arquivo [{padrao}]: ", padrao)
    with open(caminho, "wb") as f:
        f.write(ESTADO["bruto"])  # bytes idênticos aos da resposta
    ok(f"Salvo: {os.path.abspath(caminho)} ({fmt_num(len(ESTADO['bruto']))} bytes)")


def tela_config():
    itens = [("convencao", "Convenção", "escolha", ("path", "query")),
             ("lang", "lang", "texto", None), ("region", "region", "texto", None),
             ("overnight", "overnightPrice", "bool", None),
             ("enable_private", "enablePrivateCompany", "bool", None),
             ("mock_private", "mockPrivateCompany", "bool", None),
             ("mock_overnight", "mockOvernightPrice", "bool", None),
             ("cache", "Cache local 60 s", "bool", None),
             ("timeout", "Timeout (s)", "int", None),
             ("user_agent", "User-Agent", "texto", None),
             ("cor", "Cores", "estilo", None), ("ascii", "Caixas ASCII", "estilo", None)]
    while True:
        linhas = []
        for i, (k, nome, tipo, _) in enumerate(itens, 1):
            v = ESTILO[k] if tipo == "estilo" else CFG[k]
            if tipo in ("bool", "estilo"):
                txt = _flag(bool(v))
            else:
                txt = pintar(cortar(v, 60), "branco")
            linhas.append(pintar(f"{i:>2}  ", "amarelo") + pintar(f"{nome:<22}", "cinza") + txt)
        print(caixa("Configurações", linhas, total=min(largura(), 80)))
        n = ler("Número para alterar (ENTER volta): ")
        if not n:
            return
        if not n.isdigit() or not 1 <= int(n) <= len(itens):
            aviso("Número inválido.")
            continue
        k, nome, tipo, opcoes = itens[int(n) - 1]
        if tipo == "bool":
            CFG[k] = not CFG[k]
        elif tipo == "estilo":
            ESTILO[k] = not ESTILO[k]
        elif tipo == "escolha":
            novo = ler(f"{nome} {list(opcoes)}: ", CFG[k])
            if novo in opcoes:
                CFG[k] = novo
            else:
                aviso("Valor fora das opções.")
        elif tipo == "int":
            novo = ler("Segundos: ")
            if novo.isdigit() and int(novo) > 0:
                CFG[k] = int(novo)
            else:
                aviso("Informe um inteiro positivo.")
        else:
            CFG[k] = ler(f"{nome}: ", CFG[k])
        print()


# ---------- cabeçalho, status e laço ----------
def cabecalho(titulo):
    seta = ">" if ESTILO["ascii"] else "▸"
    agora = datetime.datetime.now().strftime("%H:%M:%S")
    esq = f" YAHOO FINANCE {seta} QUOTETYPE {seta} {titulo} "
    dir_ = f" {CFG['convencao'].upper()} | {CFG['region']}/{CFG['lang']} | {agora} "
    teclas = "   ".join([
        tag(" CMP ", "amarelo") + pintar(" A B", "cinza"),
        tag(" CFG ", "amarelo") + pintar(" ajustes", "cinza"),
        tag(" EXP ", "amarelo") + pintar(" exportar", "cinza"),
        tag(" SAIR ", "vermelho"),
        tag(" ENTER ", "verde") + pintar(" GO", "cinza")])
    return "\n".join([barra(esq, dir_), teclas, pintar("─" * largura() if not ESTILO["ascii"] else "-" * largura(), "linha")])


def rodape_status():
    s = ESTADO.get("status")
    bolha = "*" if ESTILO["ascii"] else "●"
    if s is None:
        seg = [(f" {bolha} PRONTO", "cinza")]
    elif not s["ok"]:
        seg = [(f" {bolha} ERRO ", "vermelho"), (cortar(s["msg"], largura() - 50), "branco")]
    elif s["origem"] == "cache":
        seg = [(f" {bolha} CACHE ", "amarelo"), ("local, menos de 60 s", "cinza")]
    else:
        seg = [(f" {bolha} OK ", "verde"), (f" {fmt_num(s['ms'])} ms  {fmt_num(s['bytes'])} B  ", "branco"),
               (s["host"], "ciano")]
    return barra_status(seg, "host sorteado entre query1 · query2 · iquery ")


def tela_inicial():
    print(pintar("Digite um ticker e pressione ENTER.", "branco"))
    print(pintar("META   ^GSPC   ES=F   PETR4.SA   BTC-USD   AAPL,MSFT", "cinza2"))


COMANDOS_SIMPLES = {"CFG": "CFG", "EXP": "EXP", "SAIR": "SAIR", "EXIT": "SAIR", "QUIT": "SAIR", "0": "SAIR"}


def interpretar(linha):
    """Devolve (comando, símbolos). Linha vazia repete a última consulta."""
    tokens = linha.replace(",", " ").split()
    if not tokens:
        return "QT", []
    primeiro = tokens[0].upper()
    if len(tokens) == 1 and primeiro in COMANDOS_SIMPLES:
        return COMANDOS_SIMPLES[primeiro], []
    if len(tokens) > 1 and tokens[-1].upper() == "QT":  # 'CMP QT' consulta o ticker CMP
        return "QT", tokens[:-1]
    if primeiro == "CMP" and len(tokens) > 1:
        return "CMP", tokens[1:]
    if primeiro == "QT" and len(tokens) > 1:
        return "QT", tokens[1:]
    return "QT", tokens


def executar(comando, simbolos):
    if simbolos:
        ESTADO["simbolos"] = ",".join(simbolos)
    padrao = [s for s in ESTADO["simbolos"].split(",") if s]
    limpar()
    if comando == "QT":
        print(cabecalho("QT " + ",".join(padrao)))
        print()
        acao(lambda: tela_consulta(padrao))
    elif comando == "CMP":
        print(cabecalho("CMP " + ",".join(padrao)))
        print()
        acao(lambda: tela_comparador(padrao))
    elif comando == "CFG":
        print(cabecalho("CFG"))
        print()
        acao(tela_config)
    elif comando == "EXP":
        print(cabecalho("EXP"))
        print()
        acao(tela_exportar)
    print()
    print(rodape_status())


def terminal():
    ESTADO["status"] = None
    seta = ">" if ESTILO["ascii"] else "▸"
    limpar()
    print(cabecalho("INÍCIO"))
    print()
    tela_inicial()
    print()
    print(rodape_status())
    try:
        while True:
            primeiro = ESTADO["simbolos"].split(",")[0] or "TICKER"
            try:
                linha = ler(pintar(f"{primeiro} {seta} ", "ambar"))
            except KeyboardInterrupt:
                print()
                aviso("Ctrl+C: digite SAIR para encerrar.")
                continue
            comando, simbolos = interpretar(linha)
            if comando == "SAIR":
                return
            executar(comando, simbolos)
    except Saida:
        print()


menu = terminal  # nome antigo


# ---------- testes offline do app ----------
AMOSTRA_REAL = ('{"quoteType":{"result":[{"symbol":"META","quoteType":"EQUITY","quartrId":"4109",'
                '"exchange":"NMS","shortName":"Meta Platforms, Inc.","longName":"Meta Platforms, Inc.",'
                '"messageBoardId":"finmb_713899537","exchangeTimezoneName":"America/New_York",'
                '"exchangeTimezoneShortName":"EDT","gmtOffSetMilliseconds":"-14400000","market":"us_market",'
                '"isEsgPopulated":false,"hasSelerityEarnings":true,"selerityIsGaap":true}],"error":null}}')


def autoteste_app():
    global _dormir, _requisitar
    falhas = []

    def checa(nome, cond):
        print(("OK    " if cond else "FALHA ") + nome)
        if not cond:
            falhas.append(nome)

    antes = dict(ESTILO)
    for asc in (False, True):
        ESTILO.update(cor=True, ascii=asc)
        ls = caixa("Título", ["curto", pintar("colorido", "verde"), "uma linha bem mais longa"]).split("\n")
        checa(f"caixa com mesma largura visível em todas as linhas (ascii={asc})", len({larg(l) for l in ls}) == 1)
        ls = caixa("Fixa", ["a", pintar("b", "ambar")], total=40).split("\n")
        checa(f"caixa com largura fixa de 40 (ascii={asc})", {larg(l) for l in ls} == {40})
    t = tabela(["A", "B"], [[pintar("x", "vermelho"), "yy"], ["zzz", pintar("w", "verde")]]).split("\n")
    checa("tabela alinha colunas ignorando ANSI", len({larg(l) for l in t}) == 1)
    ESTILO.update(antes)
    checa("preencher ignora códigos ANSI", larg(preencher(pintar("ab", "verde"), 6)) == 6)
    checa("fmt_num pt-BR milhares e decimais", fmt_num(1234567.891, 2) == "1.234.567,89")
    checa("fmt_valor de offset numérico", fmt_valor("gmtOffSetMilliseconds", -14400000) == "-14.400.000 ms (-4,0 h)")
    checa("fmt_valor de offset em string (resposta real)",
          fmt_valor("gmtOffSetMilliseconds", "-14400000") == "-14.400.000 ms (-4,0 h)")
    checa("fmt_valor de None é traço", fmt_valor("x", None) == "—")
    checa("to_int aceita string e rejeita lixo", to_int("-14400000") == -14400000 and to_int("x") is None)

    checa("interpretar: ticker simples", interpretar("META") == ("QT", ["META"]))
    checa("interpretar: vários tickers", interpretar("AAPL, MSFT") == ("QT", ["AAPL", "MSFT"]))
    checa("interpretar: CMP com tickers", interpretar("cmp AAPL MSFT") == ("CMP", ["AAPL", "MSFT"]))
    checa("interpretar: ticker CMP exige QT", interpretar("CMP QT") == ("QT", ["CMP"]))
    checa("interpretar: CFG, EXP e SAIR", interpretar("cfg") == ("CFG", []) and interpretar("EXP") == ("EXP", [])
          and interpretar("sair") == ("SAIR", []) and interpretar("0") == ("SAIR", []))
    checa("interpretar: linha vazia repete a consulta", interpretar("") == ("QT", []))

    # derivados do cliente
    checa("mapa de fusos tem 26 aliases", len(ALIAS_FUSO) == 26)
    checa("alias de fuso aplicado e fuso comum preservado",
          fuso_grafico("Europe/Paris") == "Europe/Amsterdam" and fuso_grafico("America/New_York") == "America/New_York")
    checa("calendário vem de market; cripto não tem",
          calendario({"market": "us_market", "quoteType": "EQUITY"}) == "us_market_6.0.55.json"
          and calendario({"market": "ccc_market", "quoteType": "CRYPTOCURRENCY"}).startswith("nenhum"))
    checa("hora_na_bolsa tem HH:MM:SS", len(hora_na_bolsa(-14400000)) == 8 and hora_na_bolsa(None) == "—")
    amostra = json.loads(AMOSTRA_REAL)["quoteType"]["result"][0]
    for asc in (False, True):
        ESTILO.update(cor=True, ascii=asc)
        linhas = cartao("META", amostra).split("\n")[1:]
        checa(f"cartão com a amostra real mantém alinhamento (ascii={asc})", len({larg(l) for l in linhas}) == 1)
    ESTILO.update(antes)

    # hosts sorteados entre os 3
    vistos = {tuple(_kw()["hosts"]) for _ in range(60)}
    checa("host inicial sorteado entre os 3 e todos como failover",
          {h[0] for h in vistos} == set(HOSTS_ALVO.values()) and all(len(h) == 3 for h in vistos))

    # transporte simulado: cache, falta e backoff
    chamadas = []
    real = _requisitar

    def falso(url, timeout):
        chamadas.append(url)
        ULTIMA.update(url=url, bytes=AMOSTRA_REAL.encode(), ms=1.0)
        return AMOSTRA_REAL

    _requisitar = falso
    cfg_cache = CFG["cache"]
    CACHE.clear()
    try:
        CFG["cache"] = True
        e1, f1, c1 = obter(["META"])
        e2, f2, c2 = obter(["META"])
        checa("cache de 60 s evita a segunda ida à rede", len(chamadas) == 1 and c2 == {"META"} and not c1)
        checa("símbolo omitido pelo servidor vira faltante", obter(["META", "ZZZZ"])[1] == ["ZZZZ"])
        CFG["cache"] = False
        n = len(chamadas)
        obter(["META"])
        checa("com cache desligado sempre consulta a rede", len(chamadas) == n + 1)
    finally:
        _requisitar = real
        CFG["cache"] = cfg_cache
        CACHE.clear()

    esperas, estado = [], {"n": 0}
    _dormir = esperas.append

    def falha_429_duas_vezes():
        estado["n"] += 1
        if estado["n"] <= 2:
            raise ErroQuoteType("todos os hosts falharam; último erro: HTTP 429 de x")
        return "ok"

    try:
        checa("backoff repete em 429 e termina com sucesso", com_backoff(falha_429_duas_vezes) == "ok")
        checa("esperas de 2^n segundos (1 depois 2)", esperas == [1, 2])
        esperas.clear()

        def sempre_503():
            raise ErroQuoteType("HTTP 503 de x")
        try:
            com_backoff(sempre_503)
            levantou = False
        except ErroQuoteType:
            levantou = True
        checa("máximo de 5 tentativas (esperas 1, 2, 4, 8)", levantou and esperas == [1, 2, 4, 8])
        esperas.clear()

        def erro_404():
            raise ErroQuoteType("HTTP 404 de x")
        try:
            com_backoff(erro_404)
        except ErroQuoteType:
            pass
        checa("404 não entra em backoff", esperas == [])
    finally:
        _dormir = time.sleep

    print()
    print(f"{len(falhas)} falha(s)" if falhas else "todos os testes do app passaram")
    return 1 if falhas else 0


def pausar_final():
    try:
        input(pintar("\nPressione ENTER para fechar… ", "cinza"))
    except (EOFError, KeyboardInterrupt):
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--ascii", action="store_true")
    pre.add_argument("--sem-cores", action="store_true")
    pre.add_argument("--no-pause", action="store_true")
    pre.add_argument("--pausa", action="store_true", help="pausa final também no modo CLI")
    pre.add_argument("--menu", action="store_true", help="abre o terminal mesmo com outros argumentos")
    pre.add_argument("--autoteste-app", action="store_true")
    flags, resto = pre.parse_known_args(argv)
    ESTILO["ascii"] = flags.ascii
    ESTILO["cor"] = not flags.sem_cores and "NO_COLOR" not in os.environ
    habilitar_terminal()
    modo_menu = (flags.menu or not resto) and not flags.autoteste_app
    codigo = 0
    try:
        if flags.autoteste_app:
            codigo = autoteste_app()
        elif modo_menu:
            terminal()
        else:
            codigo = main_cli(resto)
    except KeyboardInterrupt:
        print()
    except SystemExit as e:  # argparse (--help ou erro de uso)
        codigo = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:
        erro(f"FALHA inesperada ({type(e).__name__}): {e}")
        codigo = 1
    if (modo_menu or flags.pausa) and not flags.no_pause:
        pausar_final()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
