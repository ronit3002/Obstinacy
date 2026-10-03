#!/usr/bin/env python3
"""
Step 2: load step-1 outputs into the atlas_schema graph, validate, and run a first
phenotype comparison.

Reads : data/processed/seeds_resolved.json, data/processed/seed_phenotypes.csv,
        data/raw/hp.json, data/raw/phenotype.hpoa
Writes: data/processed/graph.json, data/processed/phenotype_similarity.csv
Run   : python build_graph.py        (place next to atlas_schema.py)
"""
import json, math
from collections import defaultdict
from datetime import date
from pathlib import Path

import networkx as nx
import pandas as pd

import test as S

ROOT = Path(__file__).resolve().parent
RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"
TODAY = date.today().isoformat()


# ------------------------------------------------------------------ HPO ------
def hp_id(uri):
    return uri.rsplit("/", 1)[-1].replace("_", ":") if "/HP_" in uri else None


def load_hpo():
    """names {HP:id: label}, parents {HP:id: {HP:id}}, alt {old HP:id: current HP:id}."""
    g = json.load(open(RAW / "hp.json"))["graphs"][0]
    names, alt = {}, {}
    for n in g["nodes"]:
        i = hp_id(n["id"])
        if not i:
            continue
        names[i] = n.get("lbl", i)
        for b in n.get("meta", {}).get("basicPropertyValues", []):
            if "hasAlternativeId" in b.get("pred", ""):
                alt[b["val"]] = i
    parents = defaultdict(set)
    for e in g["edges"]:
        if e.get("pred") == "is_a" and hp_id(e["sub"]) and hp_id(e["obj"]):
            parents[hp_id(e["sub"])].add(hp_id(e["obj"]))
    return names, parents, alt


def make_closure(parents):
    cache = {}
    def anc(t):  # term + all ancestors
        if t not in cache:
            s = {t}
            for p in parents.get(t, ()):
                s |= anc(p)
            cache[t] = frozenset(s)
        return cache[t]
    return anc


# ------------------------------------------------------------ build graph ----
def build_graph(names, alt):
    seeds = json.load(open(PROC / "seeds_resolved.json"))
    pheno = pd.read_csv(PROC / "seed_phenotypes.csv", dtype=str).fillna("")
    pheno["hpo_id"] = pheno["hpo_id"].map(lambda x: alt.get(x, x))  # retired IDs -> current
    genes = {r["input"]: r for r in json.load(open(PROC / "genes_resolved.json"))} \
        if (PROC / "genes_resolved.json").exists() else {}
    gene_node = {}                                   # seed symbol -> node id

    G = nx.MultiDiGraph()
    for m_id, m_name in S.MECHANISMS.items():       # vocabulary only; no edges without evidence
        S.add_node(G, m_id, "Mechanism", name=m_name)

    for d in seeds:
        S.add_node(G, d["id"], "Disease", name=d["label"], synonyms=d["synonyms"],
                   xrefs=d["xrefs"] + d.get("manual_xrefs", []), definition=d["definition"],
                   short=",".join(d["genes"]))
        for gene in d["genes"]:
            rec = genes.get(gene)
            gid = gene_node.setdefault(gene, rec["hgnc_id"] if rec and rec.get("hgnc_id") else f"GENE:{gene}")
            if gid not in G:
                S.add_node(G, gid, "Gene", name=rec["symbol"] if rec else gene,
                           hgnc_id=rec["hgnc_id"] if rec else None,
                           full_name=rec["name"] if rec else None,
                           aliases=rec["aliases"] if rec else [],
                           entrez_id=rec["entrez_id"] if rec else None)
            confirmed = d["gene_mentioned_in_mondo"].get(gene, False)
            S.add_edge(G, d["id"], gid, "ASSOCIATED_WITH",
                       source="MONDO definition" if confirmed else "team seed list (unverified)",
                       source_tier=1 if confirmed else 3, retrieved=TODAY,
                       status="observation" if confirmed else "hypothesis",
                       method="curated_import")

    for (mid, hid), grp in pheno.groupby(["mondo", "hpo_id"]):   # one edge per disease-phenotype
        if hid not in G:
            S.add_node(G, hid, "Phenotype", name=names.get(hid, hid))
        S.add_edge(G, mid, hid, "HAS_PHENOTYPE", source="HPO", source_tier=1, retrieved=TODAY,
                   status="observation", method="curated_import",
                   evidence=[{"via": r.source_id, "reference": r.reference,
                              "code": r.evidence, "frequency": r.frequency}
                             for r in grp.itertuples()])

    vpath = PROC / "variants.csv"                    # optional: written by fetch_clinvar.py
    if vpath.exists():
        for r in pd.read_csv(vpath, dtype=str).fillna("").itertuples():
            gid = gene_node.get(r.symbol)
            if gid is None:
                continue
            vid = f"CLINVAR:{r.accession or r.variation_id}"
            if vid not in G:
                S.add_node(G, vid, "Variant", name=r.title, protein_change=r.protein_change,
                           cdna_change=r.cdna_change, variant_type=r.variant_type,
                           consequence=r.consequence, classification=r.classification,
                           traits=r.traits)
            S.add_edge(G, vid, gid, "IN_GENE", source="ClinVar", source_tier=1, retrieved=TODAY,
                       status="observation", method="curated_import",
                       classification=r.classification, review_status=r.review_status,
                       review_stars=int(r.review_stars or 0), last_evaluated=r.last_evaluated)
    return G


# ------------------------------------------------- IC-weighted similarity ----
def phenotype_similarity(G, anc, alt):
    """IC-weighted Jaccard over ancestor-closed phenotype sets.
    IC comes from ALL diseases in phenotype.hpoa, so 'Seizure' (common) scores near 0
    and a specific term scores high."""
    df = pd.read_csv(RAW / "phenotype.hpoa", sep="\t", comment="#", dtype=str).fillna("")
    df = df[(df["aspect"] == "P") & (df["qualifier"] != "NOT")]
    per_disease = df.groupby("database_id")["hpo_id"].apply(lambda s: {alt.get(x, x) for x in s})
    N, count = len(per_disease), defaultdict(int)
    for terms in per_disease:
        closed = set().union(*(anc(t) for t in terms))
        for t in closed:
            count[t] += 1
    ic = lambda t: -math.log2(count.get(t, 1) / N)

    diseases = [n for n, d in G.nodes(data=True) if d["type"] == "Disease"]
    closed = {x: set().union(*(anc(v) for _, v, e in G.out_edges(x, data=True)
                               if e["rel"] == "HAS_PHENOTYPE")) for x in diseases}
    label = {x: G.nodes[x]["short"] for x in diseases}
    M = pd.DataFrame(index=[label[x] for x in diseases], columns=[label[x] for x in diseases], dtype=float)
    top = {}
    for a in diseases:
        for b in diseases:
            inter, union = closed[a] & closed[b], closed[a] | closed[b]
            M.loc[label[a], label[b]] = sum(map(ic, inter)) / sum(map(ic, union))
            if a < b:
                top[(label[a], label[b])] = sorted(inter, key=ic, reverse=True)[:3]
    return M, top, ic


# ------------------------------------------------------------------ main -----
def main():
    names, parents, alt = load_hpo()
    anc = make_closure(parents)
    G = build_graph(names, alt)

    print("== Graph ==")
    kinds = defaultdict(int)
    for _, d in G.nodes(data=True):
        kinds[d["type"]] += 1
    rels = defaultdict(int)
    for *_, d in G.edges(keys=True, data=True):
        rels[d["rel"]] += 1
    print(" nodes:", dict(kinds)); print(" edges:", dict(rels))
    unk = [n for n, d in G.nodes(data=True) if d["type"] == "Phenotype" and d["name"] == n]
    print(f" phenotype IDs without a name in hp.json: {len(unk)}")
    noid = [d["name"] for _, d in G.nodes(data=True) if d["type"] == "Gene" and not d.get("hgnc_id")]
    print(f" genes without HGNC ID: {noid or 'none'}")

    print("== Validation (atlas_schema) ==")
    print(" schema violations:", S.schema_violations(G) or "none")
    print(" unsupported inferences:", S.unsupported_inferences(G) or "none")

    print("\n== Your projection (exact-match phenotypes, 1/freq weights) ==")
    P, comms = S.cluster(G)
    for i, c in enumerate(comms):
        print(f" cluster {i}:", sorted(G.nodes[n]["short"] for n in c))
    print(f" links kept at MIN_LINK_WEIGHT={S.MIN_LINK_WEIGHT}: {P.number_of_edges()} of 21 possible pairs")

    print("\n== IC-weighted phenotype similarity (ancestor-aware, background = all HPO diseases) ==")
    M, top, ic = phenotype_similarity(G, anc, alt)
    print(M.round(2).to_string())
    M.to_csv(PROC / "phenotype_similarity.csv")
    print("\n most informative shared terms per pair (top 3):")
    for (a, b), terms in sorted(top.items()):
        print(f"  {a:>6} ~ {b:<6} {M.loc[a, b]:.2f}  " + "; ".join(f"{names.get(t, t)} ({ic(t):.1f})" for t in terms))

    try:
        data = nx.node_link_data(G, edges="edges")
    except TypeError:
        data = nx.node_link_data(G)
    json.dump(data, open(PROC / "graph.json", "w"), indent=1)
    print(f"\nwrote {PROC/'graph.json'} and {PROC/'phenotype_similarity.csv'}")


if __name__ == "__main__":
    main()