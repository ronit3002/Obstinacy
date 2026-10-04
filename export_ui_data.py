#!/usr/bin/env python3
"""
Export the atlas graph for the web UI.

Reads : data/processed/graph.json                 (scientific graph, from graph.py)
        data/processed/disease_connections.json   (disease matches, from graph.py / schema.all_connections)
        data/processed/improved-review-candidates/candidates-*.json   (paper bundles, optional)
Writes: ui/public/graph.json   ({"nodes": [...], "edges": [...], "meta": {...}})

Run   : python export_ui_data.py                  # reviewed papers only (none yet)
        python export_ui_data.py --include-pending # also show papers still awaiting signed human review

Paper bundles come from paper_pipeline.py. Their claims stay `pending` until a reviewer signs
them (paper_review.py). By default nothing pending is exported; with --include-pending the
papers are exported but every paper/claim carries review_status="pending" and the UI labels
them as unreviewed AI extractions.
"""
import argparse
import glob
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import networkx as nx
from networkx.algorithms.community import louvain_communities

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "data" / "processed"
OUT = ROOT / "ui" / "public" / "graph.json"
PAPER_GLOB = str(PROC / "improved-review-candidates" / "candidates-*.json")

CONNECTION_LABEL = {
    "mechanistic_and_phenotypic": "Shared mechanism and symptoms",
    "mechanistic": "Shared mechanism",
    "genetic_overlap": "Shared gene",
    "phenotypic_neighbor": "Similar symptoms",
    "same_gene_different_mechanism": "Same gene, different mechanism",
    "no_supported_route": "No supported route",
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def base_graph():
    g = load(PROC / "graph.json")
    nodes = g["nodes"]
    edges = [{**e, "id": e.pop("key")} for e in g["edges"]]
    # networkx node_link_data writes the edge's source *node id* into "source", overwriting the
    # provenance name graph.py stored there. Recover the name from the rules in graph.py.
    for e in edges:
        if e["rel"] == "HAS_PHENOTYPE":
            e["source_name"] = "HPO"
        elif e["rel"] == "IN_GENE":
            e["source_name"] = "ClinVar"
        elif e["rel"] == "ASSOCIATED_WITH":
            e["source_name"] = "MONDO definition" if e["source_tier"] == 1 else "team seed list (unverified)"
    return nodes, edges


def add_disease_matches(nodes, edges, today):
    """One DISEASE_MATCH edge per pair from schema.all_connections (score 0-100, min 20)."""
    by_id = {n["id"]: n for n in nodes}
    matches = load(PROC / "disease_connections.json")
    for m in matches:
        a, b = m["disease_a"], m["disease_b"]
        edges.append({
            "id": f"DISEASE_MATCH:{a}:{b}", "rel": "DISEASE_MATCH", "source": a, "target": b,
            "score": m["score"],
            "connection_type": m["connection_type"],
            "connection_label": CONNECTION_LABEL.get(m["connection_type"], m["connection_type"]),
            "components": m.get("components", {}),
            "shared_phenotypes": [{"id": p, "name": by_id.get(p, {}).get("name", p)} for p in m.get("shared_phenotypes", [])],
            "informative_phenotypes": m.get("informative_shared_phenotype_labels", []),
            "shared_genes": m.get("shared_genes", []),
            "shared_mechanisms": m.get("shared_mechanisms", []),
            "why_connected": m.get("why_connected", []),
            "meaningful_phenotype_link": m.get("meaningful_phenotype_link"),
            "same_gene_different_mechanism": m.get("same_gene_different_mechanism"),
            "evidence_quality": m.get("evidence_quality"),
            "confidence": m.get("confidence"),
            "source_name": "Atlas disease matching (schema.all_connections)",
            "source_tier": 1, "retrieved": today, "status": "inference", "method": "computed",
        })
    return len(matches)


def add_papers(nodes, edges, include_pending):
    """Paper, Claim, Researcher and Intervention nodes from paper_pipeline.py bundles."""
    by_id = {n["id"]: n for n in nodes}
    diseases = [n for n in nodes if n["type"] == "Disease" and not n.get("paper_scoped")]
    gene_to_diseases = defaultdict(set)
    for e in edges:
        if e["rel"] == "ASSOCIATED_WITH":
            gene_to_diseases[e["target"]].add(e["source"])

    def add_node(n):
        if n["id"] not in by_id:
            nodes.append(n)
            by_id[n["id"]] = n

    def add_edge(src, dst, rel, **props):
        edges.append({"id": f"{rel}:{src}->{dst}", "rel": rel, "source": src, "target": dst, **props})

    # graph.py may already have imported these papers (Paper nodes carry their PMID in source_id)
    already = {n.get("source_id") for n in nodes if n["type"] == "Paper"}

    count = 0
    for path in sorted(glob.glob(PAPER_GLOB)):
        bundle = load(path)
        for paper in bundle["papers"]:
            src = paper["source"]
            quality = paper.get("quality", {})
            pid = src["source_id"]
            if pid in already:
                continue
            approved = quality.get("publication_status") == "approved"
            if not approved and not include_pending:
                continue
            # papers that passed the pipeline's automatic checks but no human review
            review = "approved" if approved else "auto_verified"
            claims = paper["claims"]
            authors = [c for c in claims if c.get("category") == "authorship"]
            science = [c for c in claims if c.get("category") != "authorship"]
            add_node({
                "id": pid, "type": "Paper", "name": src.get("title") or pid, "url": src.get("url"),
                "source_kind": src.get("source_kind"), "source_tier": src.get("source_tier"),
                "summary_sentences": [s["text"] for s in paper.get("summary", [])],
                "summary_audit": paper.get("summary_audit", {}),
                "authors": [next(iter(c["entities"].values()))["mention"] for c in authors if c.get("entities")],
                "claim_count": len(science),
                "review_status": review, "model": bundle.get("model"), "verifier_model": bundle.get("verifier_model"),
                "prompt_version": bundle.get("prompt_version"), "bundle_sha256": bundle.get("bundle_sha256"),
                "scope_note": quality.get("scope_note"),
            })
            prov = dict(source_name=pid, source_tier=src.get("source_tier", 3), retrieved=bundle.get("created_at", "")[:10],
                        method="llm_extracted", review_status=review)

            linked_diseases = {}  # disease id -> how we know
            for i, c in enumerate(authors):
                ent = next(iter(c["entities"].values()), None)
                if not ent:
                    continue
                rid = f"RES:{pid}:{i}"  # source-local: names alone never merge people across papers
                add_node({"id": rid, "type": "Researcher", "name": ent["mention"], "source_local": True})
                add_edge(rid, pid, "AUTHORED", status="observation", **prov)

            for c in science:
                cid = c["id"]
                ents = c.get("entities", {})
                add_node({
                    "id": cid, "type": "Claim", "name": c["statement"], "statement": c["statement"],
                    "quote": c.get("evidence", {}).get("quote") or c.get("quote"),
                    "category": c.get("category"), "polarity": c.get("polarity"), "relation": c.get("relation"),
                    "study_context": c.get("study_context"), "pmid": pid,
                    "verification": c.get("verification", {}).get("reason"),
                    "review_status": review,
                    "mentions": [{"kind": e["kind"], "mention": e["mention"],
                                  "canonical_id": (e.get("resolution") or {}).get("canonical_id")} for e in ents.values()],
                })
                add_edge(pid, cid, "CONTAINS", status="observation", **prov)
                for e in ents.values():
                    kind, cano = e["kind"], (e.get("resolution") or {}).get("canonical_id")
                    target = None
                    if cano and kind in ("Gene", "Phenotype", "Disease"):
                        if cano not in by_id and kind == "Phenotype":
                            add_node({"id": cano, "type": "Phenotype", "name": e["mention"].capitalize(), "name_source": "paper mention"})
                        target = cano if cano in by_id else None
                        if kind == "Gene":
                            for d in gene_to_diseases.get(cano, ()):
                                linked_diseases.setdefault(d, f"paper discusses {by_id[cano]['name']}, the gene of this disease")
                    elif kind == "Intervention":
                        target = "INT:" + e["mention"].lower()
                        add_node({"id": target, "type": "Intervention", "name": e["mention"], "source_local": True})
                    if target:
                        add_edge(cid, target, "ABOUT", status="observation" if c.get("polarity") == "affirmed" else "hypothesis",
                                 polarity=c.get("polarity"), **prov)

            # Disease named exactly (label or synonym) in the title, e.g. "Dravet Syndrome"
            title = (src.get("title") or "").lower()
            for d in diseases:
                names = [d["name"]] + list(d.get("synonyms", []))
                hit = next((s for s in names if len(s) > 4 and s.lower() in title), None)
                if hit:
                    linked_diseases.setdefault(d["id"], f"title names “{hit}”")
            for d, why in linked_diseases.items():
                add_edge(pid, d, "DISCUSSES", status="inference", method="computed", source_name="Atlas paper linking",
                         source_tier=src.get("source_tier", 3), retrieved=prov["retrieved"], link_reason=why,
                         review_status=review)
            count += 1
    return count


def drop_partial_base_papers(nodes, edges):
    """graph.json may hold a paper with only the few claims someone approved by hand. When the full
    bundle has more claims, drop that partial copy (and anything only it touched) so the bundle replaces it.
    A complete import by graph.py (the normal case now) is kept as is."""
    full = {p["source"]["source_id"]: sum(c.get("category") != "authorship" for c in p["claims"])
            for path in glob.glob(PAPER_GLOB) for p in load(path)["papers"]}
    by_id = {n["id"]: n for n in nodes}
    have = defaultdict(int)  # scientific claims graph.json already holds per paper
    for e in edges:
        if e["rel"] == "CONTAINS" and e["target"] in by_id and by_id[e["target"]].get("category") not in ("authorship", "mechanism"):
            have[e["source"]] += 1
    papers = {n["id"] for n in nodes if n["type"] == "Paper" and n.get("source_id") in full
              and have[n["id"]] < full[n["source_id"]]}
    if not papers:
        return
    claims = {e["target"] for e in edges if e["rel"] == "CONTAINS" and e["source"] in papers}
    drop = papers | claims
    edges[:] = [e for e in edges if e["source"] not in drop and e["target"] not in drop]
    linked = {x for e in edges for x in (e["source"], e["target"])}
    # paper-only entities (researchers, outcomes, unresolved mentions) that no longer connect to anything
    for n in nodes:
        if n["id"] not in linked and (n.get("paper_scoped") or n["type"] in ("Researcher", "Outcome", "Study", "Intervention")):
            drop.add(n["id"])
    nodes[:] = [n for n in nodes if n["id"] not in drop]
    print(f"  replaced {len(papers)} partially imported papers with their full bundles")


def normalize_papers(nodes, edges):
    """Papers imported by graph.py (PAPER:... nodes) get the same shape as bundle-imported ones:
    authors list, summary sentences from the bundle, a disease link, and no authorship Claim clutter."""
    by_id = {n["id"]: n for n in nodes}
    summaries = {}
    for path in sorted(glob.glob(PAPER_GLOB)):
        for paper in load(path)["papers"]:
            summaries[paper["source"]["source_id"]] = paper

    # authorship claims are metadata, not findings: drop them (AUTHORED edges already carry them)
    drop = {n["id"] for n in nodes if n["type"] == "Claim" and n.get("category") == "authorship"}
    nodes[:] = [n for n in nodes if n["id"] not in drop]
    edges[:] = [e for e in edges if e["source"] not in drop and e["target"] not in drop]

    gene_to_diseases = defaultdict(set)
    for e in edges:
        if e["rel"] == "ASSOCIATED_WITH":
            gene_to_diseases[e["target"]].add(e["source"])
    diseases = [n for n in nodes if n["type"] == "Disease" and not n.get("paper_scoped")]
    have_link = {(e["source"], e["target"]) for e in edges if e["rel"] == "DISCUSSES"}

    for p in [n for n in nodes if n["type"] == "Paper" and "authors" not in n]:
        pid = p["id"]
        claims = [by_id[e["target"]] for e in edges if e["rel"] == "CONTAINS" and e["source"] == pid and e["target"] in by_id]
        p["authors"] = [by_id[e["source"]]["name"] for e in edges
                        if e["rel"] == "AUTHORED" and e["target"] == pid and e["source"] in by_id]
        p["claim_count"] = len(claims)
        statuses = {c.get("review_status") for c in claims}
        p["review_status"] = "approved" if statuses <= {"approved", "curated"} and statuses else "auto_verified"
        if claims:
            p["model"] = claims[0].get("model")
            p["prompt_version"] = claims[0].get("prompt_version")
        src = summaries.get(p.get("source_id"))
        if src:
            p["summary_sentences"] = [x["text"] for x in src.get("summary", [])]
            p["summary_audit"] = src.get("summary_audit", {})
            p["verifier_model"] = None
            p["scope_note"] = src.get("quality", {}).get("scope_note")
        # which diseases does this paper discuss?
        reasons = {}
        for c in claims:
            for e in edges:
                if e["rel"] != "ABOUT" or e["source"] != c["id"]:
                    continue
                tgt = by_id.get(e["target"], {})
                if tgt.get("type") == "Gene":
                    for d in gene_to_diseases.get(e["target"], ()):
                        reasons.setdefault(d, f"paper discusses {tgt['name']}, the gene of this disease")
                elif tgt.get("type") == "Disease" and not tgt.get("paper_scoped"):
                    reasons.setdefault(tgt["id"], "paper claims name this disease")
        title = (p["name"] or "").lower()
        for d in diseases:
            hit = next((x for x in [d["name"], *d.get("synonyms", [])] if len(x) > 4 and x.lower() in title), None)
            if hit:
                reasons.setdefault(d["id"], f"title names “{hit}”")
        for d, why in reasons.items():
            if (pid, d) not in have_link:
                edges.append({"id": f"DISCUSSES:{pid}->{d}", "rel": "DISCUSSES", "source": pid, "target": d,
                              "status": "inference", "method": "computed", "source_name": "Atlas paper linking",
                              "source_tier": p.get("source_tier", 2), "retrieved": date.today().isoformat(),
                              "link_reason": why, "review_status": p["review_status"]})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--include-pending", action="store_true",
                    help="export paper extractions that are still awaiting signed human review")
    args = ap.parse_args()

    today = date.today().isoformat()
    nodes, edges = base_graph()
    by_id = {n["id"]: n for n in nodes}
    diseases = [n for n in nodes if n["type"] == "Disease" and not n.get("paper_scoped")]

    n_match = add_disease_matches(nodes, edges, today)
    if args.include_pending:
        drop_partial_base_papers(nodes, edges)
    n_papers = add_papers(nodes, edges, args.include_pending)
    normalize_papers(nodes, edges)
    n_papers += sum(1 for n in nodes if n["type"] == "Paper" and n.get("source_id"))

    # Disease clusters: Louvain over match scores (fixed seed = reproducible demo)
    P = nx.Graph()
    P.add_nodes_from(d["id"] for d in diseases)
    P.add_weighted_edges_from((e["source"], e["target"], e["score"]) for e in edges if e["rel"] == "DISEASE_MATCH")
    for i, comm in enumerate(sorted(louvain_communities(P, weight="weight", seed=42), key=len, reverse=True)):
        for nid in comm:
            by_id[nid]["cluster"] = i

    # Variants per gene, precomputed so the UI can collapse them without scanning edges
    per_gene = defaultdict(lambda: defaultdict(int))
    var_cls = {n["id"]: n.get("classification") or "Unknown" for n in nodes if n["type"] == "Variant"}
    for e in edges:
        if e["rel"] == "IN_GENE":
            per_gene[e["target"]][var_cls[e["source"]]] += 1
    for gid, counts in per_gene.items():
        by_id[gid]["variant_counts"] = dict(counts)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": edges,
                   "meta": {"generated": today, "nodes": len(nodes), "edges": len(edges),
                            "includes_pending_papers": args.include_pending}},
                  f, separators=(",", ":"), ensure_ascii=False)
    print(f"wrote {OUT}: {len(nodes)} nodes, {len(edges)} edges "
          f"({n_match} disease matches, {n_papers} papers{' incl. pending review' if args.include_pending else ''})")


if __name__ == "__main__":
    main()
