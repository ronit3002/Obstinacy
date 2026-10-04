#!/usr/bin/env python3

"""
Build the AI Atlas graph.

Reads:
    data/processed/seeds_resolved.json
    data/processed/seed_phenotypes.csv
    data/raw/hp.json
    data/raw/phenotype.hpoa
    data/processed/genes_resolved.json       (optional)
    data/processed/variants.csv              (optional)

Optional paper integration:
    --paper-bundle <paper_candidates.json>
    --paper-review <review.json>

Writes:
    data/processed/graph.json
    data/processed/ui_graph.json
    data/processed/phenotype_similarity.csv
    data/processed/disease_connections.json
    data/processed/graph.gexf
    data/processed/graph_two_diseases.gexf
"""

import argparse
import json
import math
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
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

TODAY = date.today().isoformat()


# ------------------------------------------------------------------ HPO -----


def hp_id(uri):
    return (
        uri.rsplit("/", 1)[-1].replace("_", ":")
        if "/HP_" in uri
        else None
    )


def load_hpo():
    """
    Returns:
        names: {HP:id: label}
        parents: {HP:id: {parent HP:id, ...}}
        alt: {old HP:id: current HP:id}
    """

    with open(RAW / "hp.json", encoding="utf-8") as f:
        graph = json.load(f)["graphs"][0]

    names = {}
    alt = {}

    for node in graph["nodes"]:
        identifier = hp_id(node["id"])

        if not identifier:
            continue

        names[identifier] = node.get(
            "lbl",
            identifier,
        )

        for item in node.get(
            "meta",
            {},
        ).get(
            "basicPropertyValues",
            [],
        ):
            if "hasAlternativeId" in item.get(
                "pred",
                "",
            ):
                alt[item["val"]] = identifier

    parents = defaultdict(set)

    for edge in graph["edges"]:
        if (
            edge.get("pred") == "is_a"
            and hp_id(edge["sub"])
            and hp_id(edge["obj"])
        ):
            parents[
                hp_id(edge["sub"])
            ].add(
                hp_id(edge["obj"])
            )

    return names, parents, alt


def make_closure(parents):
    """
    Return a callable that gives a phenotype term
    plus all of its ancestors.
    """

    cache = {}

    def anc(term):
        if term not in cache:
            terms = {term}

            for parent in parents.get(
                term,
                (),
            ):
                terms |= anc(parent)

            cache[term] = frozenset(terms)

        return cache[term]

    return anc


# ------------------------------------------------------------ build graph -----


def build_graph(names, alt):
    seeds_path = PROC / "seeds_resolved.json"
    phenotype_path = PROC / "seed_phenotypes.csv"
    genes_path = PROC / "genes_resolved.json"
    variants_path = PROC / "variants.csv"

    with open(
        seeds_path,
        encoding="utf-8",
    ) as f:
        seeds = json.load(f)

    phenotypes = pd.read_csv(
        phenotype_path,
        dtype=str,
    ).fillna("")

    phenotypes["hpo_id"] = phenotypes[
        "hpo_id"
    ].map(
        lambda x: alt.get(x, x)
    )

    if genes_path.exists():
        with open(
            genes_path,
            encoding="utf-8",
        ) as f:
            gene_records = {
                row["input"]: row
                for row in json.load(f)
            }
    else:
        gene_records = {}

    gene_node = {}

    G = nx.MultiDiGraph()

    # Mechanisms are vocabulary only.
    # No disease/mechanism relationship is created here without evidence.
    for mechanism_id, mechanism_name in S.MECHANISMS.items():
        S.add_node(
            G,
            mechanism_id,
            "Mechanism",
            name=mechanism_name,
        )

    # ---------------------------------------------------------
    # Diseases + genes
    # ---------------------------------------------------------

    for disease in seeds:
        S.add_node(
            G,
            disease["id"],
            "Disease",
            name=disease["label"],
            synonyms=disease["synonyms"],
            xrefs=(
                disease["xrefs"]
                + disease.get(
                    "manual_xrefs",
                    [],
                )
            ),
            definition=disease["definition"],
            short=",".join(
                disease["genes"]
            ),
        )

        for gene in disease["genes"]:
            record = gene_records.get(gene)

            gene_id = gene_node.setdefault(
                gene,
                (
                    record["hgnc_id"]
                    if record
                    and record.get("hgnc_id")
                    else f"GENE:{gene}"
                ),
            )

            if gene_id not in G:
                S.add_node(
                    G,
                    gene_id,
                    "Gene",
                    name=(
                        record["symbol"]
                        if record
                        else gene
                    ),
                    hgnc_id=(
                        record["hgnc_id"]
                        if record
                        else None
                    ),
                    full_name=(
                        record["name"]
                        if record
                        else None
                    ),
                    aliases=(
                        record["aliases"]
                        if record
                        else []
                    ),
                    entrez_id=(
                        record["entrez_id"]
                        if record
                        else None
                    ),
                )

            confirmed = disease[
                "gene_mentioned_in_mondo"
            ].get(
                gene,
                False,
            )

            S.add_edge(
                G,
                disease["id"],
                gene_id,
                "ASSOCIATED_WITH",
                source=(
                    "MONDO definition"
                    if confirmed
                    else "team seed list (unverified)"
                ),
                source_tier=(
                    1
                    if confirmed
                    else 3
                ),
                retrieved=TODAY,
                status=(
                    "observation"
                    if confirmed
                    else "hypothesis"
                ),
                method="curated_import",
            )

    # ---------------------------------------------------------
    # Disease → phenotype
    # ---------------------------------------------------------

    for (
        mondo_id,
        hpo_id_value,
    ), group in phenotypes.groupby(
        [
            "mondo",
            "hpo_id",
        ]
    ):
        if hpo_id_value not in G:
            S.add_node(
                G,
                hpo_id_value,
                "Phenotype",
                name=names.get(
                    hpo_id_value,
                    hpo_id_value,
                ),
            )

        S.add_edge(
            G,
            mondo_id,
            hpo_id_value,
            "HAS_PHENOTYPE",
            source="HPO",
            source_tier=1,
            retrieved=TODAY,
            status="observation",
            method="curated_import",
            evidence=[
                {
                    "via": row.source_id,
                    "reference": row.reference,
                    "code": row.evidence,
                    "frequency": row.frequency,
                }
                for row in group.itertuples()
            ],
        )

    # ---------------------------------------------------------
    # Variant → gene
    # ---------------------------------------------------------

    if variants_path.exists():
        variants = pd.read_csv(
            variants_path,
            dtype=str,
        ).fillna("")

        for row in variants.itertuples():
            gene_id = gene_node.get(
                row.symbol
            )

            if gene_id is None:
                continue

            variant_id = (
                f"CLINVAR:"
                f"{row.accession or row.variation_id}"
            )

            if variant_id not in G:
                S.add_node(
                    G,
                    variant_id,
                    "Variant",
                    name=row.title,
                    protein_change=row.protein_change,
                    cdna_change=row.cdna_change,
                    variant_type=row.variant_type,
                    consequence=row.consequence,
                    classification=row.classification,
                    traits=row.traits,
                )

            try:
                review_stars = int(
                    row.review_stars or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                review_stars = 0

            S.add_edge(
                G,
                variant_id,
                gene_id,
                "IN_GENE",
                source="ClinVar",
                source_tier=1,
                retrieved=TODAY,
                status="observation",
                method="curated_import",
                classification=row.classification,
                review_status=row.review_status,
                review_stars=review_stars,
                last_evaluated=row.last_evaluated,
            )
    return G


# ------------------------------------------------- IC-weighted similarity -----


def phenotype_similarity(G, anc, alt):
    """
    IC-weighted Jaccard over ancestor-closed phenotype sets.

    IC is calculated against all diseases in phenotype.hpoa,
    so broad terms such as Seizure contribute less than
    informative specific terms.
    """

    df = pd.read_csv(
        RAW / "phenotype.hpoa",
        sep="\t",
        comment="#",
        dtype=str,
    ).fillna("")

    df = df[
        (df["aspect"] == "P")
        & (df["qualifier"] != "NOT")
    ]

    per_disease = (
        df.groupby(
            "database_id"
        )["hpo_id"]
        .apply(
            lambda values: {
                alt.get(value, value)
                for value in values
            }
        )
    )

    number_of_diseases = len(
        per_disease
    )

    count = defaultdict(int)

    for terms in per_disease:
        closed_terms = set().union(
            *(
                anc(term)
                for term in terms
            )
        )

        for term in closed_terms:
            count[term] += 1

    def information_content(term):
        return -math.log2(
            count.get(
                term,
                1,
            )
            / max(number_of_diseases, 1)
        )

    diseases = [
        node
        for node, data in G.nodes(
            data=True
        )
        if data["type"] == "Disease"
    ]

    closed = {
        disease: set().union(
            *(
                anc(phenotype)
                for _, phenotype, edge in G.out_edges(
                    disease,
                    data=True,
                )
                if edge["rel"]
                == "HAS_PHENOTYPE"
            )
        )
        for disease in diseases
    }

    labels = {
        disease: G.nodes[disease].get(
            "short",
            disease,
        )
        for disease in diseases
    }

    M = pd.DataFrame(
        index=[
            labels[d]
            for d in diseases
        ],
        columns=[
            labels[d]
            for d in diseases
        ],
        dtype=float,
    )

    top = {}

    for a in diseases:
        for b in diseases:
            intersection = (
                closed[a] & closed[b]
            )
            union = (
                closed[a] | closed[b]
            )

            denominator = sum(
                information_content(term)
                for term in union
            )

            M.loc[
                labels[a],
                labels[b],
            ] = (
                sum(
                    information_content(term)
                    for term in intersection
                )
                / denominator
                if denominator
                else 0.0
            )

            if a < b:
                top[
                    (
                        labels[a],
                        labels[b],
                    )
                ] = sorted(
                    intersection,
                    key=information_content,
                    reverse=True,
                )[:3]

    return (
        M,
        top,
        information_content,
    )


# ------------------------------------------------------------ serialization ---


def save_json(path, data):
    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


def node_link_data(G):
    try:
        return nx.node_link_data(
            G,
            edges="edges",
        )
    except TypeError:
        return nx.node_link_data(G)


# ---------------------------------------------------------- UI graph ----------


def add_ui_match_edges(G, matches):
    """
    Copy the scientific graph and add computed disease-match edges.

    These DISEASE_MATCH edges are for the application UI.
    They are NOT added to the scientific graph used for
    validation or biological clustering.
    """

    ui_graph = G.copy()

    for match in matches:
        disease_a = match[
            "disease_a"
        ]
        disease_b = match[
            "disease_b"
        ]

        why_connected = " | ".join(
            match.get(
                "why_connected",
                [],
            )
        )

        informative_phenotypes = "; ".join(
            match.get(
                "informative_shared_phenotype_labels",
                [],
            )
        )

        shared_phenotypes = "; ".join(
            match.get(
                "shared_phenotype_labels",
                [],
            )
        )

        shared_genes = "; ".join(
            match.get(
                "shared_genes",
                [],
            )
        )

        shared_mechanisms = "; ".join(
            match.get(
                "shared_mechanisms",
                [],
            )
        )

        ui_graph.add_edge(
            disease_a,
            disease_b,
            key=(
                "DISEASE_MATCH:"
                f"{disease_a}:"
                f"{disease_b}"
            ),
            rel="DISEASE_MATCH",
            label=(
                f"{match['connection_type']} "
                f"({match['score']:.1f})"
            ),
            weight=float(
                match["score"]
            ),
            score=float(
                match["score"]
            ),
            connection_type=match[
                "connection_type"
            ],
            evidence_quality=float(
                match.get(
                    "evidence_quality",
                    0.0,
                )
            ),
            confidence=match.get(
                "confidence",
                "",
            ),
            status="computed",
            source="Atlas disease matching",
            source_tier=1,
            retrieved=TODAY,
            method="computed",
            why_connected=why_connected,
            informative_shared_phenotypes=(
                informative_phenotypes
            ),
            shared_phenotypes=(
                shared_phenotypes
            ),
            shared_genes=shared_genes,
            shared_mechanisms=(
                shared_mechanisms
            ),
        )

    return ui_graph

def add_ui_variant_edges(ui_graph):
    """Disease -> Variant shortcut edges for the frontend only (derived through the disease's genes)."""
    for disease_id, data in list(ui_graph.nodes(data=True)):
        if data.get("type") != "Disease":
            continue
        genes = {v for _, v, e in ui_graph.out_edges(disease_id, data=True)
                 if e.get("rel") == "ASSOCIATED_WITH" and ui_graph.nodes[v].get("type") == "Gene"}
        for gene_id in genes:
            for variant_id, _, e in list(ui_graph.in_edges(gene_id, data=True)):
                if e.get("rel") == "IN_GENE" and ui_graph.nodes[variant_id].get("type") == "Variant":
                    ui_graph.add_edge(disease_id, variant_id, key=f"HAS_VARIANT:{disease_id}:{variant_id}",
                                      rel="HAS_VARIANT", source="derived: disease-gene and variant-gene links",
                                      source_tier=1, retrieved=TODAY, status="computed", method="computed")

# ---------------------------------------------------------- Gephi export ------


def sanitize_for_gexf(G):
    gephi = G.copy()

    for _, data in gephi.nodes(
        data=True
    ):
        for key, value in list(
            data.items()
        ):
            if isinstance(
                value,
                (
                    list,
                    dict,
                    tuple,
                    set,
                ),
            ):
                data[key] = str(value)

    for (
        _,
        _,
        _,
        data,
    ) in gephi.edges(
        keys=True,
        data=True,
    ):
        for key, value in list(
            data.items()
        ):
            if isinstance(
                value,
                (
                    list,
                    dict,
                    tuple,
                    set,
                ),
            ):
                data[key] = str(value)

    return gephi


# ---------------------------------------------------- two-disease Gephi test ---


def write_two_disease_gephi(
    G,
    matches,
    disease_a,
    disease_b,
):
    if (
        disease_a not in G
        or disease_b not in G
    ):
        print(
            "\nCould not create two-disease "
            "Gephi test:"
            f" {disease_a} or "
            f"{disease_b} not found."
        )
        return

    print(
        "\n== Gephi two-disease test =="
    )

    keep_nodes = {
        disease_a,
        disease_b,
    }

    for disease in (
        disease_a,
        disease_b,
    ):
        for source, target in G.in_edges(
            disease
        ):
            keep_nodes.add(source)
            keep_nodes.add(target)

        for source, target in G.out_edges(
            disease
        ):
            keep_nodes.add(source)
            keep_nodes.add(target)

    # Visualization graph is deliberately undirected.
    G_viz = nx.MultiGraph()

    for node in keep_nodes:
        G_viz.add_node(
            node,
            **G.nodes[node],
        )

    for (
        source,
        target,
        key,
        data,
    ) in G.edges(
        keys=True,
        data=True,
    ):
        if (
            source in keep_nodes
            and target in keep_nodes
        ):
            edge_data = dict(data)

            G_viz.add_edge(
                source,
                target,
                key=key,
                **edge_data,
            )

    selected_match = None

    for match in matches:
        if {
            match["disease_a"],
            match["disease_b"],
        } == {
            disease_a,
            disease_b,
        }:
            selected_match = match
            break

    if selected_match:
        why_text = " | ".join(
            selected_match.get(
                "why_connected",
                [],
            )
        )

        G_viz.add_edge(
            disease_a,
            disease_b,
            key="DISEASE_MATCH",
            rel="DISEASE_MATCH",
            label=(
                f"{selected_match['connection_type']} "
                f"({selected_match['score']:.1f})"
            ),
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
                selected_match.get(
                    "evidence_quality",
                    0.0,
                )
            ),
            confidence=selected_match.get(
                "confidence",
                "",
            ),
            status="computed",
            source="Atlas disease matching",
            source_tier=1,
            retrieved=TODAY,
            method="computed",
            why_connected=why_text,
            shared_phenotypes="; ".join(
                selected_match.get(
                    "shared_phenotype_labels",
                    [],
                )
            ),
            informative_shared_phenotypes=(
                "; ".join(
                    selected_match.get(
                        "informative_shared_phenotype_labels",
                        [],
                    )
                )
            ),
            shared_genes="; ".join(
                selected_match.get(
                    "shared_genes",
                    [],
                )
            ),
            shared_mechanisms="; ".join(
                selected_match.get(
                    "shared_mechanisms",
                    [],
                )
            ),
        )

        print(
            "  disease connection:",
            selected_match["score"],
        )

        print(
            "  type:",
            selected_match[
                "connection_type"
            ],
        )

        print(
            "  why:",
            why_text,
        )

    else:
        print(
            "  WARNING: no disease-pair "
            "match found"
        )

    for node, data in G_viz.nodes(
        data=True
    ):
        data["label"] = (
            data.get("name")
            or data.get("label")
            or node
        )

        data["node_type"] = (
            data.get("type")
            or "Unknown"
        )

        data["selected"] = (
            node
            in {
                disease_a,
                disease_b,
            }
        )

    G_viz = sanitize_for_gexf(
        G_viz
    )

    output_path = (
        PROC / "graph_two_diseases.gexf"
    )

    nx.write_gexf(
        G_viz,
        output_path,
    )

    print(
        "  nodes:",
        G_viz.number_of_nodes(),
    )

    print(
        "  edges:",
        G_viz.number_of_edges(),
    )

    print(
        "  wrote:",
        output_path,
    )

def rank_variants_for_disease(G, disease_id, top_k=5):
    """
    Rank variants for display for a selected disease.

    This is a display-priority score, NOT a clinical pathogenicity score.

    Maximum score = 100:
      - ClinVar classification: 30
      - ClinVar review strength: 15
      - Disease / trait match: 20
      - Molecular consequence: 20
      - Literature support: 10
      - Mechanism evidence: 5
    """

    disease_data = G.nodes[disease_id]

    disease_name = (
        disease_data.get("name")
        or disease_data.get("label")
        or ""
    ).lower()

    # -------------------------------------------------
    # Find genes associated with this disease
    # -------------------------------------------------
    genes = {
        v
        for _, v, d in G.out_edges(disease_id, data=True)
        if d.get("rel") == "ASSOCIATED_WITH"
        and G.nodes[v].get("type") == "Gene"
    }

    candidates = []

    for gene_id in genes:

        # -------------------------------------------------
        # Find variants in this gene
        # -------------------------------------------------
        for variant_id, _, edge_data in G.in_edges(
            gene_id, data=True
        ):
            if edge_data.get("rel") != "IN_GENE":
                continue

            variant = G.nodes[variant_id]

            if variant.get("type") != "Variant":
                continue

            score = 0
            reasons = []

            # -------------------------------------------------
            # 1. ClinVar classification: up to 30 points
            # -------------------------------------------------
            classification = (
                variant.get("classification") or ""
            ).lower().strip()

            classification_scores = {
                "pathogenic": 30,
                "likely pathogenic": 24,
                "uncertain significance": 9,
                "vus": 9,
                "likely benign": 3,
                "benign": 0,
            }

            class_score = classification_scores.get(
                classification,
                6
            )

            score += class_score

            if class_score >= 24:
                reasons.append(
                    "pathogenic ClinVar classification"
                )

            # -------------------------------------------------
            # 2. ClinVar review strength: up to 15 points
            # -------------------------------------------------

            review = (
                edge_data.get("review_status")
                or edge_data.get("reviewStatus")
                or ""
            ).lower().strip()

            review_scores = {
                "practice guideline": 15,
                "reviewed by expert panel": 14,
                "criteria provided, multiple submitters, no conflicts": 11,
                "criteria provided, single submitter": 6,
                "no assertion criteria provided": 1,
            }

            review_score = 0

            for label, points in review_scores.items():
                if label in review:
                    review_score = points
                    break
                
            score += review_score

            if review_score >= 11:
                reasons.append("strong ClinVar review")
            elif review_score >= 6:
                reasons.append("ClinVar review evidence")
            # -------------------------------------------------
            # 3. Disease / trait match: up to 20 points
            # -------------------------------------------------
            traits = str(
                variant.get("traits") or ""
            ).lower()

            disease_match = False

            disease_words = {
                word
                for word in disease_name.split()
                if len(word) >= 4
            }

            trait_words = {
                word
                for word in traits.split()
                if len(word) >= 4
            }

            if disease_name and disease_name in traits:
                disease_match = True

            elif disease_words & trait_words:
                disease_match = True

            trait_score = 20 if disease_match else 0

            score += trait_score

            if disease_match:
                reasons.append(
                    "ClinVar trait matches selected disease"
                )

            # -------------------------------------------------
            # 4. Molecular consequence: up to 20 points
            # -------------------------------------------------
            consequence = (
                variant.get("consequence") or ""
            ).lower().strip()

            consequence_scores = {
                "frameshift": 20,
                "nonsense": 20,
                "stop gained": 20,
                "splice acceptor": 18,
                "splice donor": 18,
                "start lost": 16,
                "missense": 10,
                "in-frame deletion": 8,
                "in-frame insertion": 8,
                "synonymous": 2,
            }

            consequence_score = 0

            for label, points in consequence_scores.items():
                if label in consequence:
                    consequence_score = points
                    break

            score += consequence_score

            if consequence_score:
                reasons.append(
                    f"{variant.get('consequence')} consequence"
                )

            # -------------------------------------------------
            # 5. Literature support: up to 10 points
            # -------------------------------------------------
            literature_support = 0

            for _, claim_id, edge_data in G.in_edges(
                variant_id, data=True
            ):
                if edge_data.get("rel") == "ABOUT":

                    # Each claim provides 5 points,
                    # capped at 10.
                    literature_support += 5

            literature_support = min(
                literature_support,
                10
            )

            score += literature_support

            if literature_support:
                reasons.append(
                    f"{literature_support} points literature support"
                )

            # -------------------------------------------------
            # 6. Mechanism evidence: up to 5 points
            # -------------------------------------------------
            mechanism_support = 0

            for _, mechanism_id, edge_data in G.out_edges(
                variant_id, data=True
            ):
                if edge_data.get("rel") == "DISRUPTS":
                    mechanism_support += 5

            mechanism_support = min(
                mechanism_support,
                5
            )

            score += mechanism_support

            if mechanism_support:
                reasons.append(
                    "mechanism evidence"
                )

            # -------------------------------------------------
            # Store candidate
            # -------------------------------------------------
            candidates.append({
                "variant_id": variant_id,
                "name": variant.get(
                    "name",
                    variant_id
                ),
                "classification": variant.get(
                    "classification"
                ),
                "review_status": variant.get(
                    "review_status"
                    or "reviewStatus"
                ),
                "consequence": variant.get(
                    "consequence"
                ),
                "traits": variant.get(
                    "traits"
                ),
                "score": min(score, 100),
                "reasons": reasons,
            })

    # -------------------------------------------------
    # Rank
    # -------------------------------------------------
    candidates.sort(
        key=lambda x: (
            -x["score"],
            x["name"] or ""
        )
    )

    return candidates[:top_k]

# ------------------------------------------------------------------ main -----


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--paper-bundle",
        type=Path,
        help="Reviewed paper candidate bundle",
    )

    parser.add_argument(
        "--paper-review",
        type=Path,
        help="Manual review decisions for paper claims",
    )

    parser.add_argument("--aliases", type=Path)
    parser.add_argument("--mechanisms", type=Path)
    args = parser.parse_args()

    if bool(
        args.paper_bundle
    ) != bool(
        args.paper_review
    ):
        parser.error(
            "--paper-bundle and --paper-review "
            "must be supplied together"
        )

    # ---------------------------------------------------------
    # 1. Load HPO
    # ---------------------------------------------------------

    names, parents, alt = load_hpo()
    anc = make_closure(parents)

    # ---------------------------------------------------------
    # 2. Build base graph
    # ---------------------------------------------------------

    G = build_graph(
        names,
        alt,
    )

    print(
        "== Base graph =="
    )

    print(
        f"  nodes: {G.number_of_nodes()}"
    )

    print(
        f"  edges: {G.number_of_edges()}"
    )

    # ---------------------------------------------------------
    # 3. Add reviewed paper evidence BEFORE validation
    #    and BEFORE clustering/matching.
    # ---------------------------------------------------------

    if args.paper_bundle:
        from paper_graph import (
            add_reviewed_papers,
            add_curated_mechanisms,
            load_aliases,
        )
        from paper_security import load_json, MAX_BUNDLE_BYTES

        print("\n== Adding reviewed papers ==")

        before_nodes = G.number_of_nodes()
        before_edges = G.number_of_edges()

        paper_bundle = load_json(args.paper_bundle, MAX_BUNDLE_BYTES)
        paper_review = load_json(args.paper_review)

        aliases = load_aliases(args.aliases) if args.aliases else None
        G = add_reviewed_papers(G, paper_bundle, paper_review, aliases=aliases)

        if args.mechanisms:
            G = add_curated_mechanisms(G, load_json(args.mechanisms), paper_bundle)

        texts = {p["source"]["source_id"]: p["source"]["text"]
                 for p in paper_bundle["papers"]}
        print("  unverified claim quotes:", len(S.unverified_claims(G, texts)))

        print("  nodes added:", G.number_of_nodes() - before_nodes)
        print("  edges added:", G.number_of_edges() - before_edges)

    # ---------------------------------------------------------
    # 4. Graph summary
    # ---------------------------------------------------------

    print(
        "\n== Graph =="
    )

    kinds = defaultdict(int)

    for _, data in G.nodes(
        data=True
    ):
        kinds[data["type"]] += 1

    rels = defaultdict(int)

    for _, _, _, data in G.edges(
        keys=True,
        data=True,
    ):
        rels[data["rel"]] += 1

    print(
        " nodes:",
        dict(kinds),
    )

    print(
        " edges:",
        dict(rels),
    )

    unknown_phenotypes = [
        node
        for node, data in G.nodes(
            data=True
        )
        if (
            data["type"] == "Phenotype"
            and data.get("name") == node
        )
    ]

    print(
        " phenotype IDs without a name "
        f"in hp.json: "
        f"{len(unknown_phenotypes)}"
    )

    genes_without_hgnc = [
        data["name"]
        for _, data in G.nodes(
            data=True
        )
        if (
            data["type"] == "Gene"
            and not data.get("hgnc_id")
        )
    ]

    print(
        " genes without HGNC ID:",
        genes_without_hgnc or "none",
    )

    # ---------------------------------------------------------
    # 5. Validation AFTER paper integration
    # ---------------------------------------------------------

    print(
        "\n== Graph validation =="
    )

    violations = S.schema_violations(G)
    unsupported = S.unsupported_inferences(G)
    weak = S.single_weak_source(G)

    print(
        f"Schema violations: "
        f"{len(violations)}"
    )

    print(
        f"Unsupported inferences: "
        f"{len(unsupported)}"
    )

    print(
        f"Weak-source edges: "
        f"{len(weak)}"
    )

    for item in violations:
        print(
            " ",
            item,
        )

    for item in unsupported:
        print(
            " ",
            item,
        )

    for item in weak:
        print(
            " ",
            item,
        )

    # ---------------------------------------------------------
    # 6. Disease clustering
    # ---------------------------------------------------------

    print(
        "\n== Disease clusters =="
    )

    P, communities = S.cluster(G)

    disease_count = sum(
        data["type"] == "Disease"
        for _, data in G.nodes(
            data=True
        )
    )

    possible_pairs = (
        disease_count
        * (disease_count - 1)
        // 2
    )

    for i, community in enumerate(
        communities
    ):
        print(
            f"cluster {i}:",
            sorted(
                G.nodes[node].get(
                    "name",
                    node,
                )
                for node in community
            ),
        )

    print(
        f"links kept at "
        f"MIN_LINK_WEIGHT="
        f"{S.MIN_LINK_WEIGHT}: "
        f"{P.number_of_edges()} "
        f"of {possible_pairs} possible pairs"
    )

    # ---------------------------------------------------------
    # 7. HPO phenotype similarity
    # ---------------------------------------------------------

    print(
        "\n== Phenotype similarity =="
    )

    M, top, ic = phenotype_similarity(
        G,
        anc,
        alt,
    )

    print(
        M.round(2).to_string()
    )

    phenotype_matrix_path = (
        PROC
        / "phenotype_similarity.csv"
    )

    M.to_csv(
        phenotype_matrix_path
    )

    print(
        "\nMost informative shared "
        "terms per pair:"
    )

    for (
        label_a,
        label_b,
    ), terms in sorted(
        top.items()
    ):
        print(
            f"  {label_a} ~ {label_b} "
            f"{M.loc[label_a, label_b]:.2f}  "
            + "; ".join(
                f"{names.get(term, term)} "
                f"({ic(term):.1f})"
                for term in terms
            )
        )

    # ---------------------------------------------------------
    # 8. Stable disease-ID phenotype scores
    # ---------------------------------------------------------

    disease_labels = {
        node: G.nodes[node].get(
            "short",
            node,
        )
        for node, data in G.nodes(
            data=True
        )
        if data.get("type")
        == "Disease"
    }

    label_to_id = {
        label: node
        for node, label in disease_labels.items()
    }

    phenotype_scores = {}
    informative_terms = {}

    for (
        label_a,
        label_b,
    ), terms in top.items():

        disease_a = label_to_id.get(
            label_a
        )

        disease_b = label_to_id.get(
            label_b
        )

        if (
            disease_a is None
            or disease_b is None
        ):
            continue

        pair_key = tuple(
            sorted(
                (
                    disease_a,
                    disease_b,
                )
            )
        )

        phenotype_scores[
            pair_key
        ] = float(
            M.loc[
                label_a,
                label_b,
            ]
        )

        informative_terms[
            pair_key
        ] = terms

    # ---------------------------------------------------------
    # 9. Evidence-aware disease matching
    # ---------------------------------------------------------

    print(
        "\n== Evidence-aware "
        "disease connections =="
    )

    matches = S.all_connections(
        G,
        phenotype_scores=phenotype_scores,
        informative_terms=informative_terms,
        min_score=20.0,
    )

    if not matches:
        print(
            "No disease connections "
            "passed the score threshold."
        )

    for match in matches:

        disease_a = match[
            "disease_a"
        ]

        disease_b = match[
            "disease_b"
        ]

        name_a = G.nodes[
            disease_a
        ].get(
            "name",
            disease_a,
        )

        name_b = G.nodes[
            disease_b
        ].get(
            "name",
            disease_b,
        )

        # Human-readable directly attached phenotypes
        match[
            "shared_phenotype_labels"
        ] = [
            names.get(
                hp,
                hp,
            )
            for hp in match.get(
                "shared_phenotypes",
                [],
            )
        ]

        # Human-readable informative ancestors
        pair_key = tuple(
            sorted(
                (
                    disease_a,
                    disease_b,
                )
            )
        )

        match[
            "informative_shared_phenotype_labels"
        ] = [
            names.get(
                hp,
                hp,
            )
            for hp in informative_terms.get(
                pair_key,
                [],
            )
        ]

        # Evidence quality is not the same thing
        # as biological certainty.
        evidence_quality = match.pop(
            "confidence",
            0.0,
        )

        match[
            "evidence_quality"
        ] = evidence_quality

        if evidence_quality >= 0.85:
            match["confidence"] = "high"
        elif evidence_quality >= 0.60:
            match["confidence"] = "moderate"
        else:
            match["confidence"] = "low"

        # -----------------------------------------------------
        # Build deterministic explanation
        # -----------------------------------------------------

        why_connected = []

        if match.get(
            "shared_mechanisms"
        ):
            why_connected.append(
                "Both diseases involve: "
                + ", ".join(
                    match[
                        "shared_mechanisms"
                    ]
                )
                + "."
            )

        if match.get(
            "shared_genes"
        ):
            why_connected.append(
                "Shared gene(s): "
                + ", ".join(
                    match[
                        "shared_genes"
                    ]
                )
                + "."
            )

        informative_labels = match[
            "informative_shared_phenotype_labels"
        ]

        if informative_labels:
            why_connected.append(
                "Meaningful phenotype overlap: "
                + ", ".join(
                    informative_labels[
                        :3
                    ]
                )
                + "."
            )

        if match.get(
            "same_gene_different_mechanism"
        ):
            why_connected.append(
                "The diseases share a gene "
                "but have different supported "
                "mechanisms, so this is not "
                "treated as a direct mechanistic "
                "match."
            )

        if not why_connected:
            why_connected.append(
                "No supported route was found "
                "in the current graph coverage."
            )

        match[
            "why_connected"
        ] = why_connected

        print(
            f"\n{name_a} <-> {name_b}"
        )

        print(
            "  score:",
            match["score"],
        )

        print(
            "  type:",
            match[
                "connection_type"
            ],
        )

        print(
            "  confidence:",
            match[
                "confidence"
            ],
        )

        print(
            "  evidence quality:",
            match[
                "evidence_quality"
            ],
        )

        print(
            "  mechanisms:",
            match[
                "shared_mechanisms"
            ],
        )

        print(
            "  genes:",
            match[
                "shared_genes"
            ],
        )

        print(
            "  phenotypes:",
            match[
                "shared_phenotype_labels"
            ],
        )

        for reason in match[
            "why_connected"
        ]:
            print(
                "  why:",
                reason,
            )

    # ---------------------------------------------------------
    # 10. Save disease connections
    # ---------------------------------------------------------

    disease_connections_path = (
        PROC
        / "disease_connections.json"
    )

    save_json(
        disease_connections_path,
        matches,
    )

    # ---------------------------------------------------------
    # 11. Save complete scientific graph
    # ---------------------------------------------------------

    graph_path = (
        PROC / "graph.json"
    )

    save_json(
        graph_path,
        node_link_data(G),
    )

    # ---------------------------------------------------------
    # 12. Save frontend graph
    # ---------------------------------------------------------
    # This contains the full graph PLUS computed
    # DISEASE_MATCH edges with why_connected.
    # The scientific G itself is not modified.

    ui_graph = add_ui_match_edges(
        G,
        matches,
    )

    add_ui_variant_edges(ui_graph)
    
    ui_graph_path = (
        PROC / "ui_graph.json"
    )

    save_json(
        ui_graph_path,
        node_link_data(ui_graph),
    )

    # -------------------------------------------------
    # DEBUG: find and inspect one GRIN2B variant
    # -------------------------------------------------

    target_variant_name = (
        "NM_000834.5(GRIN2B):c.1108G>T (p.Glu370Ter)"
    )

    variant_id = None

    for node_id, data in G.nodes(data=True):
        if (
            data.get("type") == "Variant"
            and data.get("name") == target_variant_name
        ):
            variant_id = node_id
            break

    print("\n== DEBUG VARIANT ==")

    if variant_id is None:
        print("Variant not found:", target_variant_name)

    else:
        print("ID:", variant_id)
        print("NODE:")
        print(G.nodes[variant_id])

        print("\nINCOMING EDGES:")
        for u, _, d in G.in_edges(variant_id, data=True):
            print(u, d)

        print("\nOUTGOING EDGES:")
        for _, v, d in G.out_edges(variant_id, data=True):
            print(v, d)
        print("\n== Top variants for GRIN2B disease ==")

    top_variants = rank_variants_for_disease(
        G,
        "MONDO:0014505",
        top_k=5,
    )

    for i, v in enumerate(top_variants, 1):
        print(
            f"{i}. {v['name']}\n"
            f"   score: {v['score']}/100\n"
            f"   classification: {v['classification']}\n"
            f"   consequence: {v['consequence']}\n"
            f"   reasons: {', '.join(v['reasons'])}"
        )

if __name__ == "__main__":
    main()