#!/usr/bin/env python3
"""
Step 3: gene identity (HGNC).

Maps every gene named in seeds_resolved.json to ONE stable HGNC ID, and collects its
aliases (GluN2B, NR2B, ...) so papers that use alias names can be attached later.

Reads : data/processed/seeds_resolved.json
Writes: data/processed/genes_resolved.json, data/processed/gene_aliases.json
Cache : data/raw/hgnc_cache.json   (delete to refetch)

Usage:
  python resolve_genes.py
  python resolve_genes.py --lookup GluN2B        # any gene name/alias, not just the seeds
Deps: pip install requests
Source: HGNC REST API https://rest.genenames.org (max 10 requests/second)
"""
import argparse, json, re, sys, time
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parent
RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"
BASE = "https://rest.genenames.org"
CACHE_FILE = RAW / "hgnc_cache.json"
_cache = None


# ---- the only function that touches the network (mocked in tests) ----------
def http_get_json(path):
    r = requests.get(BASE + path, headers={"Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    time.sleep(0.15)
    return r.json()


def hgnc(path):
    """Return the list of docs for an API path, cached on disk."""
    global _cache
    if _cache is None:
        _cache = json.load(open(CACHE_FILE)) if CACHE_FILE.exists() else {}
    if path not in _cache:
        _cache[path] = http_get_json(path).get("response", {}).get("docs", [])
        RAW.mkdir(parents=True, exist_ok=True)
        json.dump(_cache, open(CACHE_FILE, "w"))
    return _cache[path]


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def to_record(doc, text, how, ambiguous=False):
    aliases = set()
    for k in ("alias_symbol", "prev_symbol", "alias_name", "prev_name"):
        aliases |= set(doc.get(k, []))
    return {
        "input": text, "match": how, "ambiguous": ambiguous,
        "hgnc_id": doc.get("hgnc_id"), "symbol": doc.get("symbol"), "name": doc.get("name"),
        "aliases": sorted(aliases), "entrez_id": doc.get("entrez_id"),
        "ensembl_id": doc.get("ensembl_gene_id"), "location": doc.get("location"),
        "locus_type": doc.get("locus_type"), "status": doc.get("status"),
    }


def fetch_full(symbol):
    docs = hgnc(f"/fetch/symbol/{quote(symbol, safe='')}")
    return docs[0] if docs else None


def resolve(text):
    """-> list of records. 1 record = resolved; >1 = ambiguous; [] = not found."""
    text = text.strip()
    for variant in dict.fromkeys([text, text.upper()]):
        doc = fetch_full(variant)
        if doc:
            return [to_record(doc, text, "symbol")]
    for how, ep in (("alias", "search/alias_symbol"), ("previous", "search/prev_symbol")):
        for variant in dict.fromkeys([text, text.upper()]):
            hits = hgnc(f"/{ep}/{quote(variant, safe='')}")
            symbols = sorted({h["symbol"] for h in hits if h.get("symbol")})
            if symbols:
                docs = [d for d in (fetch_full(s) for s in symbols) if d]
                return [to_record(d, text, how, ambiguous=len(docs) > 1) for d in docs]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookup")
    args = ap.parse_args()

    if args.lookup:
        recs = resolve(args.lookup)
        for r in recs:
            print(f"{r['hgnc_id']}  {r['symbol']}  ({r['match']}{', AMBIGUOUS' if r['ambiguous'] else ''})  {r['name']}")
            print("   aliases:", ", ".join(r["aliases"]) or "-")
        if not recs:
            print("no match")
        return

    seeds = json.load(open(PROC / "seeds_resolved.json"))
    symbols = sorted({g for d in seeds for g in d["genes"]})
    out, problems = [], []
    for s in symbols:
        recs = resolve(s)
        if len(recs) != 1:
            problems.append(f"{s}: {'not found' if not recs else 'ambiguous -> ' + str([r['symbol'] for r in recs])}")
            continue
        r = recs[0]
        if r["symbol"] != s:
            problems.append(f"{s}: resolved via {r['match']} to current symbol {r['symbol']}; update seeds.yaml")
        if r["status"] and r["status"] != "Approved":
            problems.append(f"{s}: HGNC status is {r['status']}")
        out.append(r)

    PROC.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(PROC / "genes_resolved.json", "w"), indent=1)
    aliases = {}
    for r in out:
        for a in [r["symbol"], r["name"], *r["aliases"]]:
            if a:
                aliases.setdefault(norm(a), set()).add(r["hgnc_id"])
    json.dump({k: sorted(v) for k, v in aliases.items()}, open(PROC / "gene_aliases.json", "w"), indent=1)

    print("GENES")
    for r in out:
        print(f" {r['symbol']:<8} {r['hgnc_id']:<11} {r['location'] or '':<10} {len(r['aliases']):>2} aliases  {r['name']}")
    print("\nPROBLEMS:" if problems else "\nno problems")
    for p in problems:
        print(" -", p)
    print(f"\nwrote genes_resolved.json and gene_aliases.json in {PROC}")


if __name__ == "__main__":
    main()