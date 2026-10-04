#!/usr/bin/env python3
"""
Step 2: load step-1 outputs into the atlas_schema graph, validate, and run a first
phenotype comparison.

Reads : data/processed/seeds_resolved.json, data/processed/seed_phenotypes.csv,
        data/raw/hp.json, data/raw/phenotype.hpoa
Writes: data/processed/graph.json, data/processed/phenotype_similarity.csv
Run   : python build_graph.py        (place next to atlas_schema.py)
"""
import argparse
import json, math
from collections import defaultdict
from datetime import date
from pathlib import Path

import networkx as nx
import pandas as pd

try:
    import schema as S
except ImportError:
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


def phenotype_scores_by_id(G, anc, alt):
    """
    Same IC-weighted HPO similarity as phenotype_similarity(),
    but keyed by stable disease node IDs.
    """
    df = pd.read_csv(
        RAW / "phenotype.hpoa",
        sep="\t",
        comment="#",
        dtype=str,
    ).fillna("")

    df = df[
        (df["aspect"] == "P") &
        (df["qualifier"] != "NOT")
    ]

    per_disease = (
        df.groupby("database_id")["hpo_id"]
        .apply(lambda s: {alt.get(x, x) for x in s})
    )

    N = len(per_disease)
    count = defaultdict(int)

    for terms in per_disease:
        closed = set().union(*(anc(t) for t in terms))
        for term in closed:
            count[term] += 1

    def ic(term):
        return -math.log2(
            count.get(term, 1) / max(N, 1)
        )

    diseases = [
        n for n, d in G.nodes(data=True)
        if d["type"] == "Disease"
    ]

    closed = {
        disease: set().union(*(
            anc(v)
            for _, v, e in G.out_edges(disease, data=True)
            if e["rel"] == "HAS_PHENOTYPE"
        ))
        for disease in diseases
    }

    scores = {}
    top_terms = {}

    for i, a in enumerate(diseases):
        for b in diseases[i + 1:]:
            inter = closed[a] & closed[b]
            union = closed[a] | closed[b]

            denominator = sum(ic(x) for x in union)

            scores[(a, b)] = (
                sum(ic(x) for x in inter) / denominator
                if denominator else 0.0
            )

            top_terms[(a, b)] = sorted(
                inter,
                key=ic,
                reverse=True,
            )[:3]

    return scores, top_terms
# ------------------------------------------------------------------ main -----
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-bundle", type=Path)
    parser.add_argument("--paper-review", type=Path)
    args = parser.parse_args()
    if bool(args.paper_bundle) != bool(args.paper_review):
        parser.error("--paper-bundle and --paper-review must be supplied together")
    # ---------------------------------------------------------
    # 1. Load HPO and build the graph
    # ---------------------------------------------------------
    names, parents, alt = load_hpo()
    anc = make_closure(parents)

    G = build_graph(names, alt)

    # ---------------------------------------------------------
    # 2. Basic graph summary
    # ---------------------------------------------------------
    print("== Graph ==")

    kinds = defaultdict(int)
    for _, d in G.nodes(data=True):
        kinds[d["type"]] += 1

    rels = defaultdict(int)
    for *_, d in G.edges(keys=True, data=True):
        rels[d["rel"]] += 1

    print(" nodes:", dict(kinds))
    print(" edges:", dict(rels))

    unk = [
        n
        for n, d in G.nodes(data=True)
        if d["type"] == "Phenotype" and d["name"] == n
    ]
    print(
        f" phenotype IDs without a name in hp.json: {len(unk)}"
    )

    noid = [
        d["name"]
        for _, d in G.nodes(data=True)
        if d["type"] == "Gene" and not d.get("hgnc_id")
    ]
    print(
        f" genes without HGNC ID: {noid or 'none'}"
    )

    # ---------------------------------------------------------
    # 3. Validation
    # ---------------------------------------------------------
    print("\n== Graph validation ==")

    violations = S.schema_violations(G)
    unsupported = S.unsupported_inferences(G)
    weak = S.single_weak_source(G)

    print(f"Schema violations: {len(violations)}")
    print(f"Unsupported inferences: {len(unsupported)}")
    print(f"Weak-source edges: {len(weak)}")

    if violations:
        for item in violations:
            print(" ", item)

    if unsupported:
        for item in unsupported:
            print(" ", item)

    if weak:
        for item in weak:
            print(" ", item)

    # ---------------------------------------------------------
    # 4. Existing disease clustering
    # ---------------------------------------------------------
    print("\n== Disease clusters ==")

    P, comms = S.cluster(G)

    for i, community in enumerate(comms):
        print(
            f"cluster {i}:",
            sorted(
                G.nodes[n].get("name", n)
                for n in community
            ),
        )

    print(
        f"links kept at MIN_LINK_WEIGHT={S.MIN_LINK_WEIGHT}: "
        f"{P.number_of_edges()} of "
        f"{len([n for n, d in G.nodes(data=True) if d['type'] == 'Disease'])}"
        f"{(len([n for n, d in G.nodes(data=True) if d['type'] == 'Disease']) - 1) // 2} "
        f"possible pairs"
    )

    # ---------------------------------------------------------
    # 5. IC-weighted phenotype similarity
    # ---------------------------------------------------------
    print("\n== Phenotype similarity ==")

    M, top, ic = phenotype_similarity(
        G,
        anc,
        alt,
    )

    print(M.round(2).to_string())

    M.to_csv(
        PROC / "phenotype_similarity.csv"
    )

    print("\nMost informative shared terms per pair:")

    for (label_a, label_b), terms in sorted(top.items()):
        print(
            f"  {label_a} ~ {label_b} "
            f"{M.loc[label_a, label_b]:.2f}  "
            + "; ".join(
                f"{names.get(t, t)} ({ic(t):.1f})"
                for t in terms
            )
        )

    # ---------------------------------------------------------
    # 6. Convert phenotype scores to stable disease IDs
    # ---------------------------------------------------------
    disease_labels = {
        n: G.nodes[n].get("short", n)
        for n, d in G.nodes(data=True)
        if d.get("type") == "Disease"
    }

    label_to_id = {
        label: disease_id
        for disease_id, label in disease_labels.items()
    }

    phenotype_scores = {}
    informative_terms = {}

    for (label_a, label_b), terms in top.items():
        disease_a = label_to_id.get(label_a)
        disease_b = label_to_id.get(label_b)

        if disease_a is None or disease_b is None:
            continue

        key = tuple(sorted((disease_a, disease_b)))

        phenotype_scores[key] = float(
            M.loc[label_a, label_b]
        )

        informative_terms[key] = terms

    # ---------------------------------------------------------
    # 7. Evidence-aware disease matching
    # ---------------------------------------------------------
    print("\n== Evidence-aware disease connections ==")

    matches = S.all_connections(
        G,
        phenotype_scores=phenotype_scores,
        informative_terms=informative_terms,
        min_score=20.0,
    )

    if not matches:
        print("No disease connections passed the score threshold.")

    for match in matches:
        disease_a = match["disease_a"]
        disease_b = match["disease_b"]

        name_a = G.nodes[disease_a].get(
            "name",
            disease_a,
        )

        name_b = G.nodes[disease_b].get(
            "name",
            disease_b,
        )

        # Add human-readable phenotype names
        match["shared_phenotype_labels"] = [
            names.get(hp, hp)
            for hp in match.get(
                "shared_phenotypes",
                [],
            )
        ]

        match["informative_shared_phenotype_labels"] = [
            names.get(hp, hp)
            for hp in informative_terms.get(
                tuple(sorted((disease_a, disease_b))),
                [],
            )
        ]

        # Rename confidence concept:
        # evidence quality != biological certainty
        evidence_quality = match.pop(
            "confidence",
            0.0,
        )

        match["evidence_quality"] = evidence_quality

        if evidence_quality >= 0.85:
            match["confidence"] = "high"
        elif evidence_quality >= 0.60:
            match["confidence"] = "moderate"
        else:
            match["confidence"] = "low"

        # Make explanation human-readable
        informative_labels = (
            match["informative_shared_phenotype_labels"]
        )

        why_connected = []

        if match.get("shared_mechanisms"):
            why_connected.append(
                "Both diseases involve: "
                + ", ".join(
                    match["shared_mechanisms"]
                )
                + "."
            )

        if match.get("shared_genes"):
            why_connected.append(
                "Shared gene(s): "
                + ", ".join(
                    match["shared_genes"]
                )
                + "."
            )

        if informative_labels:
            why_connected.append(
                "Meaningful phenotype overlap: "
                + ", ".join(
                    informative_labels[:3]
                )
                + "."
            )

        if match.get("same_gene_different_mechanism"):
            why_connected.append(
                "The diseases share a gene but have "
                "different supported mechanisms, so this "
                "is not treated as a direct mechanistic match."
            )

        if not why_connected:
            why_connected.append(
                "No supported route was found in the "
                "current graph coverage."
            )

        match["why_connected"] = why_connected

        print(
            f"\n{name_a} <-> {name_b}"
        )
        print(
            f"  score: {match['score']}"
        )
        print(
            f"  type: {match['connection_type']}"
        )
        print(
            f"  confidence: {match['confidence']}"
        )
        print(
            f"  evidence quality: "
            f"{match['evidence_quality']}"
        )
        print(
            f"  mechanisms: "
            f"{match['shared_mechanisms']}"
        )
        print(
            f"  genes: "
            f"{match['shared_genes']}"
        )
        print(
            f"  phenotypes: "
            f"{match['shared_phenotype_labels']}"
        )

        for reason in match["why_connected"]:
            print(
                f"  why: {reason}"
            )

    # ---------------------------------------------------------
    # 8. Save disease connections for frontend
    # ---------------------------------------------------------
    connections_path = (
        PROC / "disease_connections.json"
    )

    with open(
        connections_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            matches,
            f,
            indent=2,
            ensure_ascii=False,
        )

    # ---------------------------------------------------------
    # 9. Save rich graph JSON
    # ---------------------------------------------------------
    graph_path = PROC / "graph.json"

    if args.paper_bundle:
        from paper_graph import add_reviewed_papers
        from paper_security import load_json, MAX_BUNDLE_BYTES
        G = add_reviewed_papers(G, load_json(args.paper_bundle, MAX_BUNDLE_BYTES),
                               load_json(args.paper_review))

    try:
        data = nx.node_link_data(
            G,
            edges="edges",
        )
    except TypeError:
        data = nx.node_link_data(G)

    with open(
        graph_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            indent=1,
        )

    # ---------------------------------------------------------
    # 10. Save GEXF for Gephi
    # ---------------------------------------------------------
    G_gephi = G.copy()

    for node, data in G_gephi.nodes(data=True):
        for key, value in data.items():
            if isinstance(
                value,
                (list, dict, tuple, set),
            ):
                data[key] = str(value)

    for u, v, key, data in G_gephi.edges(
        keys=True,
        data=True,
    ):
        for attr, value in data.items():
            if isinstance(
                value,
                (list, dict, tuple, set),
            ):
                data[attr] = str(value)

    nx.write_gexf(
        G_gephi,
        PROC / "graph.gexf",
    )


    # ---------------------------------------------------------
    # Gephi test: exactly 2 diseases
    # ---------------------------------------------------------

    disease_a = "MONDO:0014505"
    disease_b = "MONDO:0014947"

    if disease_a in G and disease_b in G:

        print("\n== Gephi two-disease test ==")

        # -----------------------------------------------------
        # 1. Collect the one-hop neighborhoods of both diseases
        # -----------------------------------------------------
        keep_nodes = {
            disease_a,
            disease_b,
        }

        for disease in (disease_a, disease_b):

            # Incoming neighbors
            for source, target in G.in_edges(disease):
                keep_nodes.add(source)
                keep_nodes.add(target)

            # Outgoing neighbors
            for source, target in G.out_edges(disease):
                keep_nodes.add(source)
                keep_nodes.add(target)

        # -----------------------------------------------------
        # 2. Create an UNDIRECTED graph for Gephi
        #
        # Important:
        # Keep the real G as a MultiDiGraph.
        # This graph is only for visualization.
        # -----------------------------------------------------
        G_viz = nx.MultiGraph()

        # Add nodes
        for node in keep_nodes:
            G_viz.add_node(
                node,
                **G.nodes[node],
            )

        # Add biological relationships as undirected edges
        for source, target, key, data in G.edges(
            keys=True,
            data=True,
        ):
            if source in keep_nodes and target in keep_nodes:

                edge_data = dict(data)

                # GEXF-safe edge attributes
                for attr, value in list(edge_data.items()):
                    if isinstance(
                        value,
                        (list, dict, tuple, set),
                    ):
                        edge_data[attr] = str(value)

                G_viz.add_edge(
                    source,
                    target,
                    key=key,
                    **edge_data,
                )

        # -----------------------------------------------------
        # 3. Find the disease-pair match
        # -----------------------------------------------------
        selected_match = None

        for match in matches:

            pair = {
                match["disease_a"],
                match["disease_b"],
            }

            if pair == {
                disease_a,
                disease_b,
            }:
                selected_match = match
                break

        # -----------------------------------------------------
        # 4. Add explicit symmetric disease connection
        # -----------------------------------------------------
        if selected_match:

            G_viz.add_edge(
                disease_a,
                disease_b,
                key="DISEASE_MATCH",
                rel="DISEASE_MATCH",
                weight=float(
                    selected_match["score"]
                ),
                score=float(
                    selected_match["score"]
                ),
                connection_type=selected_match[
                    "connection_type"
                ],
                evidence_quality=float(
                    selected_match[
                        "evidence_quality"
                    ]
                ),
                status="computed",
                source="Atlas disease matching",
                source_tier=1,
                retrieved=TODAY,
                method="computed",
                why_connected=" | ".join(
                    selected_match[
                        "why_connected"
                    ]
                ),
            )

            print(
                f"  disease connection: "
                f"{selected_match['score']}"
            )

            print(
                f"  type: "
                f"{selected_match['connection_type']}"
            )

        else:
            print(
                "  WARNING: no disease-pair match found"
            )

        # -----------------------------------------------------
        # 5. Human-readable node labels
        # -----------------------------------------------------
        for node, data in G_viz.nodes(data=True):

            node_type = data.get("type")

            data["label"] = (
                data.get("name")
                or data.get("label")
                or node
            )

            data["node_type"] = (
                node_type
                or "Unknown"
            )

            # Mark the two focal diseases
            data["selected"] = (
                node in {
                    disease_a,
                    disease_b,
                }
            )

        # -----------------------------------------------------
        # 6. Convert complex attributes for GEXF
        # -----------------------------------------------------
        for node, data in G_viz.nodes(data=True):

            for key, value in list(data.items()):

                if isinstance(
                    value,
                    (list, dict, tuple, set),
                ):
                    data[key] = str(value)

        for source, target, key, data in G_viz.edges(
            keys=True,
            data=True,
        ):

            for attr, value in list(data.items()):

                if isinstance(
                    value,
                    (list, dict, tuple, set),
                ):
                    data[attr] = str(value)

        # -----------------------------------------------------
        # 7. Write dedicated Gephi file
        # -----------------------------------------------------
        gephi_test_path = (
            PROC / "graph_two_diseases.gexf"
        )

        nx.write_gexf(
            G_viz,
            gephi_test_path,
        )

        print(
            f"  nodes: "
            f"{G_viz.number_of_nodes()}"
        )

        print(
            f"  edges: "
            f"{G_viz.number_of_edges()}"
        )

        print(
            f"  wrote: "
            f"{gephi_test_path}"
        )

    else:

        print(
            "\nCould not create two-disease "
            "Gephi test:"
            f" {disease_a} or "
            f"{disease_b} not found."
        )

    # ---------------------------------------------------------
    # 12. Final output summary
    # ---------------------------------------------------------
    print("\nWrote:")
    print(
        f"  {PROC / 'phenotype_similarity.csv'}"
    )
    print(
        f"  {PROC / 'disease_connections.json'}"
    )
    print(
        f"  {PROC / 'graph.json'}"
    )
    print(
        f"  {PROC / 'graph.gexf'}"
    )

if __name__ == "__main__":
    main()