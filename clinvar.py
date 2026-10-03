#!/usr/bin/env python3
"""
Step 4: pathogenic / likely pathogenic variants from ClinVar for each seed gene.

Reads : data/processed/genes_resolved.json
Writes: data/processed/variants.csv
Cache : data/raw/clinvar_<SYMBOL>_esummary.json  (raw NCBI responses, for debugging)

Usage:
  python fetch_clinvar.py                    # 200 best-reviewed variants per gene
  python fetch_clinvar.py --max-per-gene 500
Optional env vars: NCBI_API_KEY (10 req/s instead of 3), NCBI_EMAIL
Deps: pip install requests pandas
Note: ClinVar records the *classification*, not loss- vs gain-of-function. Mechanism comes
from literature claims in a later step; `consequence` is stored only as context.
"""
import argparse, json, os, sys, time
from pathlib import Path
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
KEEP = {"pathogenic", "likely pathogenic", "pathogenic/likely pathogenic"}
DELAY = 0.12 if os.environ.get("NCBI_API_KEY") else 0.4


# ---- network layer (mocked in tests) ---------------------------------------
def _params(extra):
    p = {"tool": "rare-disease-atlas", "retmode": "json", **extra}
    if os.environ.get("NCBI_API_KEY"):
        p["api_key"] = os.environ["NCBI_API_KEY"]
    if os.environ.get("NCBI_EMAIL"):
        p["email"] = os.environ["NCBI_EMAIL"]
    return p


def _json(r, what):
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f"NCBI {what} returned non-JSON (HTTP {r.status_code}): {r.text[:300]!r}")


def eutils_get(endpoint, **params):
    r = requests.get(f"{EUTILS}/{endpoint}", params=_params(params), timeout=60)
    r.raise_for_status(); time.sleep(DELAY)
    return _json(r, endpoint)


def eutils_post(endpoint, **params):
    r = requests.post(f"{EUTILS}/{endpoint}", data=_params(params), timeout=120)
    r.raise_for_status(); time.sleep(DELAY)
    return _json(r, endpoint)


# ---- logic ------------------------------------------------------------------
def review_stars(status):
    s = (status or "").lower()
    if "practice guideline" in s: return 4
    if "expert panel" in s: return 3
    if "multiple submitters, no conflicts" in s: return 2
    if "single submitter" in s or "conflicting" in s: return 1
    return 0


def search_ids(symbol):
    term = (f'{symbol}[gene] AND ("clinsig pathogenic"[Properties] '
            f'OR "clinsig likely pathogenic"[Properties])')
    resp = eutils_get("esearch.fcgi", db="clinvar", term=term, retmax=10000)
    if "esearchresult" not in resp:
        raise RuntimeError(f"esearch for {symbol} has no 'esearchresult'. Response: {json.dumps(resp)[:400]}")
    res = resp["esearchresult"]
    if res.get("errorlist") or res.get("warninglist"):
        print(f"  {symbol} query notes: {res.get('errorlist')} {res.get('warninglist')}", file=sys.stderr)
    if int(res.get("count", 0)) > len(res.get("idlist", [])):
        print(f"  warning: {symbol} has {res['count']} hits, only {len(res['idlist'])} returned", file=sys.stderr)
    return res.get("idlist", [])


def summaries(ids, batch=100):
    out = {}
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        for attempt in range(4):
            resp = eutils_post("esummary.fcgi", db="clinvar", id=",".join(chunk))
            if "result" in resp:
                break
            print(f"  esummary batch {i // batch} attempt {attempt + 1} had no 'result'. "
                  f"Response: {json.dumps(resp)[:300]}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"esummary kept failing. Last response: {json.dumps(resp)[:400]}")
        for uid in resp["result"].get("uids", []):
            out[uid] = resp["result"][uid]
    return out


def parse(uid, rec):
    cls = rec.get("germline_classification") or rec.get("clinical_significance") or {}
    vs = (rec.get("variation_set") or [{}])[0]
    return {
        "variation_id": uid,
        "accession": rec.get("accession"),
        "title": rec.get("title"),
        "protein_change": rec.get("protein_change"),
        "cdna_change": vs.get("cdna_change"),
        "variant_type": rec.get("obj_type"),
        "consequence": "; ".join(rec.get("molecular_consequence_list") or []),
        "classification": cls.get("description", ""),
        "review_status": cls.get("review_status", ""),
        "review_stars": review_stars(cls.get("review_status")),
        "last_evaluated": cls.get("last_evaluated", ""),
        "traits": "; ".join(t.get("trait_name", "") for t in cls.get("trait_set", []) or []),
        "genes_on_record": ";".join(g.get("symbol", "") for g in rec.get("genes", []) or []),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-gene", type=int, default=200)
    ap.add_argument("--include-multigene", action="store_true",
                    help="keep records spanning several genes (e.g. large deletions); excluded by default")
    args = ap.parse_args()
    genes = json.load(open(PROC / "genes_resolved.json"))
    rows, report, printed_keys = [], [], []
    RAW.mkdir(parents=True, exist_ok=True)
    for g in genes:
        sym = g["symbol"]
        ids = search_ids(sym)
        recs = summaries(ids)
        json.dump(recs, open(RAW / f"clinvar_{sym}_esummary.json", "w"))
        if recs and not printed_keys:
            print("sample record keys:", sorted(next(iter(recs.values())).keys())); printed_keys.append(1)
        parsed = [parse(uid, r) for uid, r in recs.items()]
        kept = [p for p in parsed if p["classification"].lower() in KEEP
                and sym in p["genes_on_record"].split(";")
                and (args.include_multigene or p["genes_on_record"].count(";") == 0)]
        kept.sort(key=lambda p: (p["review_stars"], p["last_evaluated"]), reverse=True)  # best-reviewed, newest first
        top = kept[:args.max_per_gene]
        for p in top:
            rows.append({"symbol": sym, "hgnc_id": g["hgnc_id"], **p})
        report.append({"gene": sym, "esearch": len(ids), "pathogenic/LP": len(kept), "kept": len(top),
                       "stars>=2": sum(p["review_stars"] >= 2 for p in top),
                       "LoF-type consequence": sum(any(k in p["consequence"] for k in
                                ("nonsense", "frameshift", "splice")) for p in top)})
    PROC.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(PROC / "variants.csv", index=False)
    print(pd.DataFrame(report).to_string(index=False))
    if not rows or any(r["esearch"] == 0 for r in report):
        print("\nWARNING: a gene returned 0 hits. The ClinVar query syntax may need adjusting; "
              "paste this output and the first lines of data/raw/clinvar_*.json.")
    print(f"\nwrote {PROC/'variants.csv'}")


if __name__ == "__main__":
    main()