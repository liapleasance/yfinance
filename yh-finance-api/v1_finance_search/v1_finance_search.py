#!/usr/bin/env python3
"""
v1_finance_search.py — implementacao de referencia executavel do endpoint
GET /v1/finance/search (Yahoo Finance).

Autossuficiente: sem dependencias alem da stdlib (urllib; o endpoint nao
exige fingerprint TLS de browser — apenas User-Agent de navegador).

Uso:
    python v1_finance_search.py Apple                     # contexto all (padrao do modulo)
    python v1_finance_search.py NVDA --context quote      # caixa do dock (data-finsrch=quote)
    python v1_finance_search.py NVDA --context researchReports   # cabecalho ybar (data-finsrch)
    python v1_finance_search.py AAPL,MSFT                 # modo multiquote por virgula
    python v1_finance_search.py AAPL --include equity     # includeTypes (providerLogos)
    python v1_finance_search.py Apple --lang pt-BR --region BR
    python v1_finance_search.py Apple --json               # corpo cru
    python v1_finance_search.py Apple --save-fixture       # captura fixture do consumer oficial
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

HOSTS = [
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
PATH = "/v1/finance/search"

# Presets de contexto do FinSearchJS (B, webcore/srchjs/1.2.50/js/finSearch.modern.js):
# o cliente oficial sorteia query1/query2 por requisicao (funcao q).
CONTEXTS = {
    "all": {
        "quotesCount": 6, "newsCount": 4, "enableFuzzyQuery": False,
        "quotesQueryId": "tss_match_phrase_query",
        "multiQuoteQueryId": "multi_quote_single_token_query",
        "newsQueryId": "news_cie_vespa", "enableCb": True,
        "enableNavLinks": True, "enableEnhancedTrivialQuery": True,
        "enableCulturalAssets": True, "enableLogoUrl": True,
        "enableLists": False, "enableNcgNews": True,
    },
    "researchReports": {  # form do cabecalho (data-finsrch="researchReports")
        "quotesCount": 6, "newsCount": 3, "listsCount": 2,
        "enableFuzzyQuery": False,
        "quotesQueryId": "tss_match_phrase_query",
        "multiQuoteQueryId": "multi_quote_single_token_query",
        "newsQueryId": "news_cie_vespa", "enableCb": True,
        "enableNavLinks": True, "enableEnhancedTrivialQuery": True,
        "enableResearchReports": True, "enableCulturalAssets": True,
        "enableLogoUrl": True, "enableLists": False, "enableNcgNews": True,
    },
    "quote": {  # form do dock (data-finsrch="quote")
        "quotesCount": 8,
        "quotesQueryId": "tss_match_phrase_query",
        "multiQuoteQueryId": "multi_quote_single_token_query",
        "enableCb": False, "enableNavLinks": True,
        "enableCulturalAssets": True, "enableNews": False,
        "enableResearchReports": False, "enableLists": False,
    },
}


def search(query, lang="en-US", region="US", context="all", host_index=0,
           timeout=15, include_types=None, exclude_types=None):
    """GET /v1/finance/search — retorna o corpo cru (envelope plano).

    Serializacao fiel ao cliente oficial: apenas valores string/number/boolean
    entram na querystring (objetos sao descartados); a ordem de insercao e
    q, lang, region, depois os campos do contexto.

    Raises:
        RuntimeError: 400/405 (deterministicos) ou todos os hosts falharam
    """
    params = {"q": query, "lang": lang, "region": region}
    params.update(CONTEXTS.get(context, CONTEXTS["all"]))
    if include_types:
        params["includeTypes"] = include_types
    if exclude_types:
        params["excludeTypes"] = exclude_types
    qs = "&".join(f"{k}={v}" for k, v in params.items())  # fiel ao V() do bundle

    last_err = None
    for i in range(len(HOSTS)):
        host = HOSTS[(host_index + i) % len(HOSTS)]  # o oficial sorteia; aqui failover
        url = f"{host}{PATH}?{qs}"
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,  # unica exigencia da edge (UA browser)
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (400, 405):
                raise RuntimeError(f"HTTP {e.code}: {body[:200]}")
            last_err = f"HTTP {e.code}: {body[:120]}"
        except Exception as e:  # timeout, conexao — tenta proximo host
            last_err = str(e)
    raise RuntimeError(f"todos os hosts falharam; ultimo erro: {last_err}")


def summarize(body):
    """Resumo legivel do envelope plano: categorias e simbolos."""
    if "finance" in body:  # envelope de erro
        return body
    lines = []
    for cat in ("quotes", "news", "nav", "lists", "researchReports",
                "screenerFieldResults"):
        items = body.get(cat) or []
        if not items:
            continue
        if cat == "quotes":
            labels = [it.get("symbol") or f"[privada] {it.get('name')}"
                      for it in items]
            lines.append(f"quotes ({len(items)}): " + ", ".join(labels))
        elif cat == "news":
            lines.append(f"news ({len(items)}): "
                          + "; ".join(it.get("title", "")[:60] for it in items[:3]))
        else:
            lines.append(f"{cat} ({len(items)})")
    lines.append(f"count={body.get('count')} totalTime={body.get('totalTime')}ms")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Cliente /v1/finance/search")
    ap.add_argument("query", help="termo de busca (aspas se tiver espaco; "
                                  "virgula ativa modo multiquote exato)")
    ap.add_argument("--lang", default="en-US")
    ap.add_argument("--region", default="US")
    ap.add_argument("--context", default="all",
                    choices=sorted(CONTEXTS), help="preset do FinSearchJS")
    ap.add_argument("--include", dest="include_types", default=None,
                    help="includeTypes (ex.: equity)")
    ap.add_argument("--exclude", dest="exclude_types", default=None,
                    help="excludeTypes (ex.: equity,etf)")
    ap.add_argument("--json", action="store_true", help="corpo cru JSON")
    ap.add_argument("--save-fixture", action="store_true",
                    help="salva a resposta crua em v1_finance_search.json")
    args = ap.parse_args()

    body = search(args.query, lang=args.lang, region=args.region,
                  context=args.context, include_types=args.include_types,
                  exclude_types=args.exclude_types)
    if args.save_fixture:
        with open("v1_finance_search.json", "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=1)
        print("fixture salvo em v1_finance_search.json", file=sys.stderr)
    if args.json:
        print(json.dumps(body, ensure_ascii=False, indent=1))
    else:
        print(summarize(body))


if __name__ == "__main__":
    main()
