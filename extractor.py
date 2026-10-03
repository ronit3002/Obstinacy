#!/usr/bin/env python3
"""
Step 1: data + ID resolution.

  - downloads MONDO + HPO files (once)
  - builds an alias -> MONDO ID resolver over ALL of MONDO (not just the seeds)
  - resolves each seed: name, synonyms, OMIM/Orphanet/GARD xrefs
  - joins HPO phenotype annotations through those xrefs
  - prints a coverage report and writes processed files

Usage:
  python scripts/01_resolve_seeds.py
  python scripts/01_resolve_seeds.py --lookup "DEE27"
Deps: pip install pandas pyyaml requests
"""
import argparse, json, re, sys
from pathlib import Path
import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
URLS = {
    "mondo.json": "https://github.com/monarch-initiative/mondo/releases/latest/download/mondo.json",
    "phenotype.hpoa": "https://github.com/obophenotype/human-phenotype-ontology/releases/latest/download/phenotype.hpoa",
    "hp.json": "https://github.com/obophenotype/human-phenotype-ontology/releases/latest/download/hp.json",
}


def download_all():
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        p = RAW / name
        if p.exists() and p.stat().st_size > 0:
            continue
        print(f"downloading {name} ...", file=sys.stderr)
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(p, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)


def norm(s: str) -> str:
    """Normalise a name for alias matching."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def norm_xref(x: str) -> str:
    """Make xref prefixes consistent across sources (MONDO says Orphanet:, HPOA says ORPHA:)."""
    if x.lower().startswith("orphanet:"):
        return "ORPHA:" + x.split(":", 1)[1]
    return x


class MondoResolver:
    def __init__(self, path: Path):
        g = json.load(open(path))["graphs"][0]
        self.nodes, self.alias = {}, {}
        for n in g["nodes"]:
            if n.get("type") != "CLASS" or "/MONDO_" not in n["id"]:
                continue
            mid = n["id"].rsplit("/", 1)[-1].replace("_", ":")
            meta = n.get("meta", {})
            syns = [s["val"] for s in meta.get("synonyms", [])
                    if "DEPRECATED" not in s.get("synonymType", "")]
            xrefs = sorted({norm_xref(x["val"]) for x in meta.get("xrefs", [])})
            rec = {
                "id": mid,
                "label": n.get("lbl"),
                "synonyms": sorted(set(syns)),
                "xrefs": xrefs,
                "definition": meta.get("definition", {}).get("val"),
                "deprecated": bool(meta.get("deprecated")),
                "rare_subsets": sorted(s.rsplit("#", 1)[-1] for s in meta.get("subsets", [])
                                       if s.endswith(("_rare", "#rare"))),
            }
            self.nodes[mid] = rec
            if rec["deprecated"] or not rec["label"]:
                continue
            for name in [rec["label"], *rec["synonyms"]]:
                self.alias.setdefault(norm(name), set()).add(mid)
            for x in xrefs:  # IDs resolve too: "OMIM:616139" -> MONDO
                self.alias.setdefault(norm(x), set()).add(mid)

    def resolve(self, text: str):
        """Return list of MONDO IDs for a name/synonym/xref. >1 result = ambiguous."""
        return sorted(self.alias.get(norm(text), []))


def load_hpoa():
    df = pd.read_csv(RAW / "phenotype.hpoa", sep="\t", comment="#", dtype=str).fillna("")
    df = df[(df["aspect"] == "P") & (df["qualifier"] != "NOT")]  # phenotypic abnormalities, not negated
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default=str(ROOT / "seeds.yaml"))
    ap.add_argument("--lookup", help="resolve a single name/ID and exit")
    args = ap.parse_args()

    download_all()
    mondo = MondoResolver(RAW / "mondo.json")

    if args.lookup:
        for mid in mondo.resolve(args.lookup) or []:
            print(mid, "|", mondo.nodes[mid]["label"])
        if not mondo.resolve(args.lookup):
            print("no match")
        return

    hpoa = load_hpoa()
    seeds = yaml.safe_load(open(args.seeds))["seeds"]
    resolved, pheno_rows, report = [], [], []

    for s in seeds:
        mid = s["mondo"]
        rec = mondo.nodes.get(mid)
        if rec is None:
            report.append({"mondo": mid, "disease": "NOT FOUND IN MONDO"})
            continue
        omim = [x for x in rec["xrefs"] if x.startswith("OMIM:")]
        orpha = [x for x in rec["xrefs"] if x.startswith("ORPHA:")]
        gard = [x for x in rec["xrefs"] if x.startswith("GARD:")]
        extra = [norm_xref(x) for x in s.get("extra_xrefs", [])]  # manual overrides, tracked separately
        join_ids = omim + orpha + extra
        ph = hpoa[hpoa["database_id"].isin(join_ids)]
        # which xref actually supplied the phenotypes (so gaps are explainable)
        by_src = ph.groupby("database_id")["hpo_id"].nunique().to_dict()
        for _, r in ph.iterrows():
            pheno_rows.append({"mondo": mid, "source_id": r["database_id"], "hpo_id": r["hpo_id"],
                               "frequency": r["frequency"], "evidence": r["evidence"],
                               "reference": r["reference"]})
        # sanity check: does the declared gene appear in the MONDO text?
        text = " ".join([rec["label"] or "", rec["definition"] or "", *rec["synonyms"]])
        gene_check = {g: bool(re.search(rf"\b{re.escape(g)}\b", text)) for g in s.get("genes", [])}
        resolved.append({**rec, "genes": s.get("genes", []), "omim": omim, "orpha": orpha, "gard": gard,
                         "manual_xrefs": extra,
                         "hpo_terms_by_source": by_src, "gene_mentioned_in_mondo": gene_check})
        report.append({
            "mondo": mid, "disease": (rec["label"] or "")[:44],
            "OMIM": len(omim), "ORPHA": len(orpha), "GARD": len(gard),
            "synonyms": len(rec["synonyms"]),
            "HPO terms": ph["hpo_id"].nunique(),
            "gene": ",".join(s.get("genes", [])) + ("" if all(gene_check.values()) else " (?)"),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(resolved, open(OUT / "seeds_resolved.json", "w"), indent=1)
    pd.DataFrame(pheno_rows).to_csv(OUT / "seed_phenotypes.csv", index=False)

    print("\nCOVERAGE REPORT")
    print(pd.DataFrame(report).to_string(index=False))
    print("\nGAPS TO FOLLOW UP")
    any_gap = False
    for r in resolved:
        if not r["orpha"] and not any(x.startswith("ORPHA:") for x in r["manual_xrefs"]):
            print(f"- {r['id']}: no Orphanet xref in MONDO"); any_gap = True
        if not r["omim"] and not any(x.startswith("OMIM:") for x in r["manual_xrefs"]):
            print(f"- {r['id']}: no OMIM xref in MONDO"); any_gap = True
        if not r["hpo_terms_by_source"]:
            print(f"- {r['id']}: no HPO annotations via its OMIM/ORPHA xrefs"); any_gap = True
        if not all(r["gene_mentioned_in_mondo"].values()):
            print(f"- {r['id']}: gene {r['genes']} not mentioned in MONDO text; verify manually"); any_gap = True
        if r["manual_xrefs"]:
            print(f"- {r['id']}: used MANUAL xrefs {r['manual_xrefs']} (not in MONDO); document in README"); any_gap = True
        if len(r["omim"]) + len(r["orpha"]) > 1:
            print(f"- {r['id']}: multiple source IDs {r['omim'] + r['orpha']}; phenotypes merged from "
                  f"{list(r['hpo_terms_by_source'])}"); any_gap = True
    if not any_gap:
        print("- none")
    print(f"\nwrote {OUT/'seeds_resolved.json'} and {OUT/'seed_phenotypes.csv'}")


if __name__ == "__main__":
    main()