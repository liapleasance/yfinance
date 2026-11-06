#!/usr/bin/env python3
"""
v1_finance_lookup.py — implementacao de referencia executavel do endpoint
GET /v1/finance/lookup (Yahoo Finance).

Autossuficiente: sem dependencias alem da stdlib (urllib; o endpoint nao
exige cookie, crumb nem fingerprint TLS de browser — apenas User-Agent de
navegador).

Defaults fiéis ao cliente oficial (funcao It, chunks/loadLookup.[hash].js):
    type=all  start=0  count=20  formatted=true  fetchPricingData=true
A pagina /lookup (nodes/143) usa count=25 via param de URL c=25.

Uso:
    python v1_finance_lookup.py Apple                     # canonico do cliente
    python v1_finance_lookup.py Apple --count 25           # default da pagina /lookup
    python v1_finance_lookup.py Apple --type equity        # filtro por tipo
    python v1_finance_lookup.py Apple --type equity,etf    # uniao por virgula
    python v1_finance_lookup.py Apple --start 20           # paginacao
    python v1_finance_lookup.py Apple --no-pricing        # fetchPricingData=false
    python v1_finance_lookup.py Apple --no-format         # formatted=false (primitivos)
    python v1_finance_lookup.py Apple --lang ja-JP --region JP   # corpus regional
    python v1_finance_lookup.py Apple --host iquery       # query1/query2/iquery
    python v1_finance_lookup.py Apple --totals            # so lookupTotals
    python v1_finance_lookup.py Apple --json              # corpo cru
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

HOSTS = {
    "query1": "https://query1.finance.yahoo.com",
    "query2": "https://query2.finance.yahoo.com",
    "iquery": "https://iquery.finance.yahoo.com",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
PATH = "/v1/finance/lookup"

# Lista canonica do servidor (mensagem do 400) + o seletor agregador.
# "all" e aceito mas nao aparece na mensagem de erro do servidor.
# "private_company" (enviado pelo bundle, nodes/135) e REJEITADO: 400.
VALID_TYPES = ["equity", "mutualfund", "etf", "index", "currency",
               "future", "cryptocurrency"]


def lookup(query: str, type_: str = "all", start: int = 0, count: int = 20,
           formatted: bool = True, fetch_pricing_data: bool = True,
           lang: str = "en-US", region: str = "US",
           host: str = "query1", timeout: int = 15) -> dict:
    """Executa GET /v1/finance/lookup e devolve o corpo JSON parseado.

    Nao exige cookie nem crumb (endpoint anonimo); o crumb enviado pelo
    cliente oficial e um no-op verificado no servidor.
    """
    if not query:
        # espelha a guarda client-side da funcao It do bundle
        raise ValueError("query obrigatoria (servidor: "
                         "'Missing required query parameter=query')")
    params = {
        "query": query,
        "type": type_,
        "start": str(start),
        "count": str(count),
        "formatted": "true" if formatted else "false",
        "fetchPricingData": "true" if fetch_pricing_data else "false",
        "lang": lang,
        "region": region,
    }
    url = HOSTS[host] + PATH + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def unwrap(field):
    """Extrai o valor cru de envelope {raw, fmt} (formatted=true)."""
    if isinstance(field, dict) and "raw" in field:
        return field["raw"]
    return field


def print_docs(body: dict) -> None:
    """Impressao tabular fiel as colunas da pagina /lookup."""
    result = (body.get("finance", {}).get("result") or [{}])[0]
    docs = result.get("documents", [])
    totals = result.get("lookupTotals", {})
    print(f"start={result.get('start')} count={result.get('count')} "
          f"total={result.get('total')} ndocs={len(docs)}")
    print("lookupTotals:", json.dumps(totals))
    if not docs:
        print("(sem documentos)")
        return
    header = f"{'symbol':<14}{'type':<15}{'rank':>8}{'price':>10}  shortName"
    print(header)
    print("-" * len(header))
    for d in docs:
        price = unwrap(d.get("regularMarketPrice"))
        price_s = f"{price:.2f}" if isinstance(price, (int, float)) else "-"
        print(f"{d.get('symbol', ''):<14}{d.get('quoteType', ''):<15}"
              f"{d.get('rank', 0):>8}{price_s:>10}  {d.get('shortName', '')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="GET /v1/finance/lookup")
    ap.add_argument("query", help="texto de busca (obrigatorio)")
    ap.add_argument("--type", default="all",
                    help="all (default) | " + "|".join(VALID_TYPES)
                         + " | uniao por virgula (ex: equity,etf)")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=20,
                    help="20 = default do servidor/funcao It; 25 = pagina /lookup")
    ap.add_argument("--no-format", action="store_true",
                    help="formatted=false (primitivos)")
    ap.add_argument("--no-pricing", action="store_true",
                    help="fetchPricingData=false (sem campos de preco)")
    ap.add_argument("--lang", default="en-US")
    ap.add_argument("--region", default="US")
    ap.add_argument("--host", choices=sorted(HOSTS), default="query1")
    ap.add_argument("--totals", action="store_true",
                    help="imprime apenas lookupTotals")
    ap.add_argument("--json", action="store_true", help="corpo cru")
    args = ap.parse_args()

    body = lookup(args.query, type_=args.type, start=args.start,
                  count=args.count, formatted=not args.no_format,
                  fetch_pricing_data=not args.no_pricing,
                  lang=args.lang, region=args.region, host=args.host)

    if args.json:
        print(json.dumps(body, indent=1, ensure_ascii=False))
    elif args.totals:
        result = (body.get("finance", {}).get("result") or [{}])[0]
        print(json.dumps(result.get("lookupTotals", {}), indent=1))
    else:
        print_docs(body)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        # Erros 4xx/5xx vem com envelope JSON {"finance": {"result": null,
        # "error": {code, description}}} — exceto 429 da edge (texto puro).
        try:
            print(json.dumps(json.loads(e.read()), indent=1), file=sys.stderr)
        except Exception:
            print(f"HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
