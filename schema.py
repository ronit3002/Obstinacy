"""
Atlas graph: schema, validator, evidence rules, clustering, and a tiny worked example.

ALL DATA IN build_example() IS ILLUSTRATIVE PLACEHOLDER DATA (fake IDs, made-up
papers). Replace it with real ingested records. Run:  python atlas_schema.py
"""
import networkx as nx
from networkx.algorithms.community import louvain_communities

# ---------------------------------------------------------------- schema ----
NODE_TYPES = {
    "Disease", "Gene", "Variant", "Mechanism", "Phenotype",
    "Paper", "Claim", "Study", "PatientOrg", "Registry", "Researcher", "Intervention", "Outcome",
}

# Small hand-made list. Do NOT let the LLM invent mechanisms.
MECHANISMS = {
    "MECH:loss_of_function": "Loss of function",
    "MECH:gain_of_function": "Gain of function",
}

# edge relation -> (allowed source types, allowed target types)
EDGE_TYPES = {
    "IN_GENE":         ({"Variant"}, {"Gene"}),
    "DISRUPTS":        ({"Variant"}, {"Mechanism"}),
    "ASSOCIATED_WITH": ({"Disease"}, {"Gene", "Variant"}),
    "HAS_PHENOTYPE":   ({"Disease"}, {"Phenotype"}),
    "INVOLVES":        ({"Disease"}, {"Mechanism"}),   # derived or stated: see status
    "CONTAINS":        ({"Paper"}, {"Claim"}),
    "ABOUT":           ({"Claim"}, {"Disease", "Gene", "Variant", "Mechanism", "Phenotype", "Researcher", "Study", "Intervention", "Outcome"}),
    "AUTHORED":        ({"Researcher"}, {"Paper"}),
    "STUDIES":         ({"Study"}, {"Disease"}),
    "REPRESENTED_BY":  ({"Disease"}, {"PatientOrg"}),
    "MAINTAINS":       ({"PatientOrg"}, {"Registry"}),
}

# Required on every edge
REQUIRED_EDGE_PROPS = {"rel", "source", "source_tier", "retrieved", "status", "method"}
# status: observation | inference | hypothesis
# source_tier: 1 = curated DB, 2 = peer-reviewed paper, 3 = preprint / org website
# method: curated_import | llm_extracted | computed
STATUSES = {"observation", "inference", "hypothesis"}

# Required on Claim nodes
REQUIRED_CLAIM_PROPS = {"quote", "pmid", "status", "confidence", "model", "prompt_version"}


# ------------------------------------------------------------- build helpers --
def add_node(G, nid, ntype, **props):
    assert ntype in NODE_TYPES, f"unknown node type {ntype}"
    G.add_node(nid, type=ntype, **props)


def add_edge(G, src, dst, rel, **props):
    G.add_edge(src, dst, key=f"{rel}:{src}->{dst}:{len(G.get_edge_data(src, dst) or {})}",
               rel=rel, **props)


# ------------------------------------------------------------- validation ----
def schema_violations(G):
    """Structural problems. Anything returned here is excluded from the app graph."""
    out = []
    for n, d in G.nodes(data=True):
        if d.get("type") not in NODE_TYPES:
            out.append(("node", n, "missing or unknown type"))
        if d.get("type") == "Claim" and not REQUIRED_CLAIM_PROPS <= d.keys():
            out.append(("node", n, f"claim missing {REQUIRED_CLAIM_PROPS - d.keys()}"))
    for u, v, k, d in G.edges(keys=True, data=True):
        missing = REQUIRED_EDGE_PROPS - d.keys()
        if missing:
            out.append(("edge", k, f"missing props {sorted(missing)}"))
            continue
        rel = d["rel"]
        if rel not in EDGE_TYPES:
            out.append(("edge", k, f"unknown relation {rel}"))
            continue
        src_ok, dst_ok = EDGE_TYPES[rel]
        if G.nodes[u].get("type") not in src_ok or G.nodes[v].get("type") not in dst_ok:
            out.append(("edge", k, f"{rel} not allowed between "
                                   f"{G.nodes[u].get('type')} and {G.nodes[v].get('type')}"))
        if d["status"] not in STATUSES:
            out.append(("edge", k, f"bad status {d['status']}"))
    return out


# ---------------------------------------------------------- evidence rules ---
def unverified_claims(G, source_texts):
    """The anti-hallucination check: a Claim's quote must appear verbatim in its source."""
    bad = []
    for n, d in G.nodes(data=True):
        if d.get("type") == "Claim":
            text = source_texts.get(d.get("pmid"), "")
            if d.get("quote", "") not in text or not d.get("quote"):
                bad.append((n, "quote not found in source text"))
    return bad


STRUCTURAL_RELS = {"CONTAINS", "ABOUT"}  # provenance plumbing: they ARE the claim links


def unsupported_inferences(G):
    """Inference/hypothesis edges must point at at least one existing Claim node."""
    bad = []
    for u, v, k, d in G.edges(keys=True, data=True):
        if d.get("rel") in STRUCTURAL_RELS:
            continue
        if d.get("status") in {"inference", "hypothesis"} or d.get("method") == "llm_extracted":
            ids = d.get("supported_by", [])
            if not ids or not all(G.nodes.get(c, {}).get("type") == "Claim" for c in ids):
                bad.append((k, "inferred edge without valid supporting claim"))
    return bad


def single_weak_source(G):
    """Edges whose only support is a tier-3 source."""
    return [(k, "only tier-3 source") for _, _, k, d in G.edges(keys=True, data=True)
            if d.get("source_tier") == 3 and d.get("status") != "observation"]


def same_gene_different_mechanism(G):
    """The brief's counterexample: one gene, variants with different mechanisms."""
    out = {}
    for var, d in G.nodes(data=True):
        if d.get("type") != "Variant":
            continue
        genes = [v for _, v, e in G.out_edges(var, data=True) if e["rel"] == "IN_GENE"]
        mechs = [v for _, v, e in G.out_edges(var, data=True) if e["rel"] == "DISRUPTS"]
        for g in genes:
            out.setdefault(g, {}).setdefault(tuple(sorted(mechs)), []).append(var)
    return {g: m for g, m in out.items() if len(m) > 1}


# --------------------------------------------------------------- clustering --
MIN_LINK_WEIGHT = 1.0  # a single shared broad symptom (e.g. seizures) is NOT enough to link


def disease_projection(G):
    """Link diseases by shared mechanism and shared phenotypes (rarer phenotype = heavier)."""
    diseases = [n for n, d in G.nodes(data=True) if d["type"] == "Disease"]
    mech = {x: {v for _, v, e in G.out_edges(x, data=True) if e["rel"] == "INVOLVES"} for x in diseases}
    phen = {x: {v for _, v, e in G.out_edges(x, data=True) if e["rel"] == "HAS_PHENOTYPE"} for x in diseases}
    freq = {}
    for s in phen.values():
        for p in s:
            freq[p] = freq.get(p, 0) + 1
    P = nx.Graph()
    P.add_nodes_from(diseases)
    for i, a in enumerate(diseases):
        for b in diseases[i + 1:]:
            shared_m = mech[a] & mech[b]
            shared_p = phen[a] & phen[b]
            w = 2.0 * len(shared_m) + sum(1.0 / freq[p] for p in shared_p)
            if w >= MIN_LINK_WEIGHT:
                P.add_edge(a, b, weight=w, shared_mechanisms=sorted(shared_m),
                           shared_phenotypes=sorted(shared_p))
    return P


def cluster(G):
    P = disease_projection(G)
    comms = louvain_communities(P, weight="weight", seed=42)  # fixed seed = reproducible demo
    return P, comms

from math import sqrt


# ---------------------------------------------------------- match scoring ---

STATUS_WEIGHT = {
    "observation": 1.00,
    "inference": 0.80,
    "hypothesis": 0.50,
}

TIER_WEIGHT = {
    1: 1.00,   # curated database
    2: 0.90,   # peer-reviewed paper
    3: 0.65,   # preprint / organization website
}

METHOD_WEIGHT = {
    "curated_import": 1.00,
    "computed": 0.95,
    "llm_extracted": 0.90,
}


def edge_evidence_score(G, u, v, edge_data):
    """
    Convert provenance metadata into a 0..1 evidence-quality score.
    This measures support quality, not biological truth.
    """
    status = STATUS_WEIGHT.get(edge_data.get("status"), 0.0)
    tier = TIER_WEIGHT.get(int(edge_data.get("source_tier", 3)), 0.0)
    method = METHOD_WEIGHT.get(edge_data.get("method"), 0.0)

    score = status * tier * method

    # For LLM-extracted edges, use the verified Claim confidence when present.
    claim_ids = edge_data.get("supported_by", [])
    claim_scores = []

    for cid in claim_ids:
        claim = G.nodes.get(cid, {})
        if claim.get("type") == "Claim":
            try:
                claim_scores.append(float(claim.get("confidence", 0.0)))
            except (TypeError, ValueError):
                pass

    if claim_scores:
        score *= sum(claim_scores) / len(claim_scores)

    return max(0.0, min(1.0, score))


def best_edge_support(G, u, v, rel):
    """Best provenance score among parallel edges of a relation."""
    values = []

    for _, _, data in G.edges(u, v, data=True):
        if data.get("rel") == rel:
            values.append(edge_evidence_score(G, u, v, data))

    return max(values, default=0.0)


def node_link_map(G, node_type, rel):
    """
    Return:
        node -> {neighbor: best evidence score}
    """
    out = {}

    for node, data in G.nodes(data=True):
        if data.get("type") != node_type:
            continue

        links = {}

        for _, target, edge in G.out_edges(node, data=True):
            if edge.get("rel") != rel:
                continue

            target_type = G.nodes[target].get("type")
            if target_type not in {"Gene", "Mechanism", "Phenotype"}:
                continue

            score = edge_evidence_score(G, node, target, edge)
            links[target] = max(links.get(target, 0.0), score)

        out[node] = links

    return out


def disease_feature_maps(G):
    """
    Extract evidence-weighted disease -> mechanism/gene/phenotype maps.
    """
    mechanisms = {}
    genes = {}
    phenotypes = {}

    for disease, d in G.nodes(data=True):
        if d.get("type") != "Disease":
            continue

        mechanisms[disease] = {}
        genes[disease] = {}
        phenotypes[disease] = {}

        for _, target, edge in G.out_edges(disease, data=True):
            rel = edge.get("rel")
            target_type = G.nodes[target].get("type")
            support = edge_evidence_score(G, disease, target, edge)

            if rel == "INVOLVES" and target_type == "Mechanism":
                mechanisms[disease][target] = max(
                    mechanisms[disease].get(target, 0.0),
                    support,
                )

            elif rel == "HAS_PHENOTYPE" and target_type == "Phenotype":
                phenotypes[disease][target] = max(
                    phenotypes[disease].get(target, 0.0),
                    support,
                )

            elif rel == "ASSOCIATED_WITH" and target_type == "Gene":
                genes[disease][target] = max(
                    genes[disease].get(target, 0.0),
                    support,
                )

    return mechanisms, genes, phenotypes


def phenotype_link_weight(phenotypes, a, b):
    """
    Existing projection idea:
    shared broad phenotypes get low weight because they occur in many diseases.
    """
    pa = set(phenotypes[a])
    pb = set(phenotypes[b])
    shared = pa & pb

    frequency = {}
    for disease_terms in phenotypes.values():
        for p in disease_terms:
            frequency[p] = frequency.get(p, 0) + 1

    weight = sum(
        1.0 / max(frequency.get(p, 1), 1)
        for p in shared
    )

    return weight, sorted(
        shared,
        key=lambda p: 1.0 / max(frequency.get(p, 1), 1),
        reverse=True,
    )


def weighted_jaccard(map_a, map_b):
    """
    Evidence-weighted Jaccard for maps {feature: support}.
    """
    a = set(map_a)
    b = set(map_b)

    if not a and not b:
        return 0.0

    union = a | b
    inter = a & b

    numerator = sum(
        min(map_a[x], map_b[x])
        for x in inter
    )

    denominator = sum(
        max(
            map_a.get(x, 0.0),
            map_b.get(x, 0.0),
        )
        for x in union
    )

    return numerator / denominator if denominator else 0.0


def shared_feature_support(map_a, map_b):
    shared = set(map_a) & set(map_b)

    if not shared:
        return 0.0

    # Conservative: both diseases must have good evidence.
    return sum(
        sqrt(map_a[x] * map_b[x])
        for x in shared
    ) / len(shared)


def genetic_similarity(genes_a, genes_b):
    a = set(genes_a)
    b = set(genes_b)

    if not a and not b:
        return 0.0

    return len(a & b) / len(a | b)


def pair_connection(
    G,
    a,
    b,
    mechanisms,
    genes,
    phenotypes,
    phenotype_similarity_score=None,
    informative_phenotypes=None,
):
    """
    Produce one frontend-ready disease-disease connection record.
    """

    shared_m = set(mechanisms[a]) & set(mechanisms[b])
    shared_g = set(genes[a]) & set(genes[b])
    shared_p = set(phenotypes[a]) & set(phenotypes[b])

    # Mechanism similarity
    mechanism_score = weighted_jaccard(
        mechanisms[a],
        mechanisms[b],
    )

    mechanism_support = shared_feature_support(
        mechanisms[a],
        mechanisms[b],
    )

    # Gene similarity
    gene_score = genetic_similarity(
        genes[a],
        genes[b],
    )

    gene_support = shared_feature_support(
        genes[a],
        genes[b],
    )

    # Phenotype similarity:
    # Prefer the stronger IC-weighted score already calculated in graph.py.
    if phenotype_similarity_score is not None:
        phenotype_score = max(
            0.0,
            min(1.0, float(phenotype_similarity_score)),
        )
    else:
        phenotype_score = 0.0

    # Guardrail from disease_projection():
    # one ordinary shared phenotype must not manufacture a strong connection.
    pheno_weight, weighted_shared_p = phenotype_link_weight(
        phenotypes,
        a,
        b,
    )

    meaningful_phenotype_link = pheno_weight >= MIN_LINK_WEIGHT

    if not meaningful_phenotype_link:
        phenotype_score *= 0.35

    # Overall evidence quality for the actual overlapping features.
    evidence_values = []

    if shared_m:
        evidence_values.append(mechanism_support)

    if shared_g:
        evidence_values.append(gene_support)

    if shared_p:
        for p in shared_p:
            evidence_values.append(
                min(
                    phenotypes[a][p],
                    phenotypes[b][p],
                )
            )

    evidence_score = (
        sum(evidence_values) / len(evidence_values)
        if evidence_values else 0.0
    )

    # Only score dimensions for which we actually have evidence.
    # Missing mechanism/gene evidence should not unfairly suppress
    # a legitimate phenotype-based connection.
    components = []
    weights = []
    
    if shared_m:
        components.append(mechanism_score)
        weights.append(0.50)
    
    if shared_g:
        components.append(gene_score)
        weights.append(0.20)
    
    if phenotype_score > 0:
        components.append(phenotype_score)
        weights.append(0.30)
    
    if components:
        raw = sum(
            score * weight
            for score, weight in zip(components, weights)
        ) / sum(weights)
    else:
        raw = 0.0

    final_score = 100.0 * raw * (
        0.60 + 0.40 * evidence_score
    )

    # Important counterexample from your existing test.py:
    # same gene does NOT imply same disease mechanism.
    same_gene_different_mechanism = (
        bool(shared_g)
        and bool(mechanisms[a])
        and bool(mechanisms[b])
        and not shared_m
    )

    if same_gene_different_mechanism:
        final_score *= 0.35

    # Relationship label used by the UI.
    if shared_m and meaningful_phenotype_link:
        connection_type = "mechanistic_and_phenotypic"
    elif shared_m:
        connection_type = "mechanistic"
    elif shared_g and not same_gene_different_mechanism:
        connection_type = "genetic_overlap"
    elif meaningful_phenotype_link:
        connection_type = "phenotypic_neighbor"
    elif same_gene_different_mechanism:
        connection_type = "same_gene_different_mechanism"
    else:
        connection_type = "no_supported_route"

    # Explain the connection deterministically.
    why = []

    if shared_m:
        why.append(
            f"Both diseases involve: "
            f"{', '.join(sorted(shared_m))}."
        )

    if shared_g:
        why.append(
            f"Shared gene(s): "
            f"{', '.join(sorted(shared_g))}."
        )

    if meaningful_phenotype_link:
        terms = informative_phenotypes or weighted_shared_p
        if terms:
            why.append(
                f"Meaningful phenotype overlap: "
                f"{', '.join(terms[:3])}."
            )

    if same_gene_different_mechanism:
        why.append(
            "The diseases share a gene but have different supported "
            "mechanisms, so this is not treated as a direct mechanistic match."
        )

    if not why:
        why.append(
            "No supported route was found in the current graph coverage."
        )

    return {
        "disease_a": a,
        "disease_b": b,
        "score": round(final_score, 2),
        "confidence": round(evidence_score, 3),
        "connection_type": connection_type,

        "components": {
            "mechanism": round(mechanism_score, 3),
            "phenotype": round(phenotype_score, 3),
            "genetic": round(gene_score, 3),
        },

        "shared_mechanisms": sorted(shared_m),
        "shared_genes": sorted(shared_g),
        "shared_phenotypes": sorted(shared_p),

        "meaningful_phenotype_link": meaningful_phenotype_link,
        "same_gene_different_mechanism": same_gene_different_mechanism,

        "why_connected": why,
    }


def all_connections(
    G,
    phenotype_scores=None,
    informative_terms=None,
    min_score=20.0,
):
    """
    Build all disease-pair connections for the frontend.
    phenotype_scores:
        {(disease_a, disease_b): IC_weighted_similarity}
    informative_terms:
        {(disease_a, disease_b): [HPO terms]}
    """
    mechanisms, genes, phenotypes = disease_feature_maps(G)

    diseases = sorted(mechanisms)

    results = []

    for i, a in enumerate(diseases):
        for b in diseases[i + 1:]:
            score_key = (a, b)

            rec = pair_connection(
                G,
                a,
                b,
                mechanisms,
                genes,
                phenotypes,
                phenotype_similarity_score=(
                    phenotype_scores.get(score_key, 0.0)
                    if phenotype_scores else None
                ),
                informative_phenotypes=(
                    informative_terms.get(score_key, [])
                    if informative_terms else None
                ),
            )

            if rec["score"] >= min_score:
                results.append(rec)

    return sorted(
        results,
        key=lambda x: x["score"],
        reverse=True,
    )

# ------------------------------------------------------------ example data ---
def build_example():
    G = nx.MultiDiGraph()
    T = "2026-10-03"

    # Nodes (placeholder IDs)
    add_node(G, "MONDO:EX_A", "Disease", name="Example disease A (early-onset)")
    add_node(G, "MONDO:EX_B", "Disease", name="Example disease B (neurodevelopmental)")
    add_node(G, "MONDO:EX_C", "Disease", name="Example disease C (different gene)")
    add_node(G, "HGNC:EX_X", "Gene", name="GENE-X")
    add_node(G, "HGNC:EX_Y", "Gene", name="GENE-Y")
    add_node(G, "CLINVAR:EX_1", "Variant", name="GENE-X variant 1")
    add_node(G, "CLINVAR:EX_2", "Variant", name="GENE-X variant 2")
    add_node(G, "CLINVAR:EX_3", "Variant", name="GENE-Y variant 1")
    for mid, name in MECHANISMS.items():
        add_node(G, mid, "Mechanism", name=name)
    add_node(G, "HP:EX_seizures", "Phenotype", name="Seizures")
    add_node(G, "HP:EX_rare", "Phenotype", name="Example rare feature")
    add_node(G, "ORG:EX_1", "PatientOrg", name="Example Foundation", url="https://example.org")
    add_node(G, "REG:EX_1", "Registry", name="Example Registry", collects="clinical history")

    # Curated edges (observations from curated databases)
    cur = dict(source="ClinVar", source_tier=1, retrieved=T, status="observation", method="curated_import")
    add_edge(G, "CLINVAR:EX_1", "HGNC:EX_X", "IN_GENE", **cur)
    add_edge(G, "CLINVAR:EX_2", "HGNC:EX_X", "IN_GENE", **cur)
    add_edge(G, "CLINVAR:EX_3", "HGNC:EX_Y", "IN_GENE", **cur)
    add_edge(G, "MONDO:EX_A", "HGNC:EX_X", "ASSOCIATED_WITH", **cur)
    add_edge(G, "MONDO:EX_C", "HGNC:EX_Y", "ASSOCIATED_WITH", **cur)
    hpo = dict(source="HPO", source_tier=1, retrieved=T, status="observation", method="curated_import")
    add_edge(G, "MONDO:EX_A", "HP:EX_seizures", "HAS_PHENOTYPE", **hpo)
    add_edge(G, "MONDO:EX_B", "HP:EX_seizures", "HAS_PHENOTYPE", **hpo)
    add_edge(G, "MONDO:EX_C", "HP:EX_seizures", "HAS_PHENOTYPE", **hpo)
    add_edge(G, "MONDO:EX_A", "HP:EX_rare", "HAS_PHENOTYPE", **hpo)
    add_edge(G, "MONDO:EX_C", "HP:EX_rare", "HAS_PHENOTYPE", **hpo)
    org = dict(source="Orphanet", source_tier=1, retrieved=T, status="observation", method="curated_import")
    add_edge(G, "MONDO:EX_C", "ORG:EX_1", "REPRESENTED_BY", **org)
    add_edge(G, "ORG:EX_1", "REG:EX_1", "MAINTAINS", **org)

    # LLM-extracted: Papers -> Claims -> mechanisms, each with a verbatim quote
    papers = {
        "PMID:1001": "We show that variant 1 in GENE-X causes loss of function of the channel.",
        "PMID:1002": "Variant 2 in GENE-X results in gain of function and a distinct phenotype.",
        "PMID:1003": "Loss of function variants in GENE-Y disrupt the same pathway.",
    }
    quotes = {
        "CLAIM:1": ("PMID:1001", "variant 1 in GENE-X causes loss of function", "CLINVAR:EX_1"),
        "CLAIM:2": ("PMID:1002", "Variant 2 in GENE-X results in gain of function", "CLINVAR:EX_2"),
        "CLAIM:3": ("PMID:1003", "Loss of function variants in GENE-Y", "CLINVAR:EX_3"),
    }
    mech_of = {"CLAIM:1": "MECH:loss_of_function", "CLAIM:2": "MECH:gain_of_function",
               "CLAIM:3": "MECH:loss_of_function"}
    for pmid in papers:
        add_node(G, pmid, "Paper", title=f"Placeholder paper {pmid}")
    llm = dict(source_tier=2, retrieved=T, method="llm_extracted")
    for cid, (pmid, quote, var) in quotes.items():
        add_node(G, cid, "Claim", quote=quote, pmid=pmid, status="observation",
                 confidence=0.9, model="<model-name>", prompt_version="v1")
        add_edge(G, pmid, cid, "CONTAINS", source=pmid, status="observation", **llm)
        add_edge(G, cid, var, "ABOUT", source=pmid, status="observation", **llm)
        add_edge(G, var, mech_of[cid], "DISRUPTS", source=pmid, status="observation",
                 supported_by=[cid], **llm)

    # Derived inference: disease -> mechanism, only because of variant path + claim
    inf = dict(source="derived from claims", source_tier=2, retrieved=T, method="computed", status="inference")
    add_edge(G, "MONDO:EX_A", "MECH:loss_of_function", "INVOLVES", supported_by=["CLAIM:1"], **inf)
    add_edge(G, "MONDO:EX_B", "MECH:gain_of_function", "INVOLVES", supported_by=["CLAIM:2"], **inf)
    add_edge(G, "MONDO:EX_C", "MECH:loss_of_function", "INVOLVES", supported_by=["CLAIM:3"], **inf)

    # Deliberately bad data, to show the rules firing:
    add_node(G, "CLAIM:BAD", "Claim", quote="this sentence is not in the paper", pmid="PMID:1001",
             status="observation", confidence=0.8, model="<model-name>", prompt_version="v1")
    add_edge(G, "MONDO:EX_B", "MECH:loss_of_function", "INVOLVES", source="a blog", source_tier=3,
             retrieved=T, method="llm_extracted", status="inference")  # no supporting claim
    add_edge(G, "MONDO:EX_B", "MONDO:EX_C", "HAS_PHENOTYPE", rel_note="wrong types", source="x",
             source_tier=1, retrieved=T, method="curated_import", status="observation")

    return G, papers


# --------------------------------------------------------------------- demo --
if __name__ == "__main__":
    G, source_texts = build_example()

    print("== Schema violations ==")
    for v in schema_violations(G):
        print(" ", v)
    print("== Unverified claim quotes ==")
    for v in unverified_claims(G, source_texts):
        print(" ", v)
    print("== Inferences without support ==")
    for v in unsupported_inferences(G):
        print(" ", v)

    # Build the clean graph: drop rejected edges and claims
    bad_edges = {x[1] for x in schema_violations(G) if x[0] == "edge"} | \
                {x[0] for x in unsupported_inferences(G)}
    bad_nodes = {x[0] for x in unverified_claims(G, source_texts)}
    clean = nx.MultiDiGraph()
    clean.add_nodes_from((n, d) for n, d in G.nodes(data=True) if n not in bad_nodes)
    for u, v, k, d in G.edges(keys=True, data=True):
        if k not in bad_edges and u not in bad_nodes and v not in bad_nodes:
            clean.add_edge(u, v, key=k, **d)

    print("\n== Counterexample: same gene, different mechanism ==")
    for gene, groups in same_gene_different_mechanism(clean).items():
        print(" ", clean.nodes[gene]["name"], "->", groups)

    print("\n== Clusters (by shared mechanism + phenotype) ==")
    P, comms = cluster(clean)
    for i, c in enumerate(comms):
        print(f"  cluster {i}:", [clean.nodes[n]["name"] for n in sorted(c)])
    for a, b, d in P.edges(data=True):
        print(f"  why {a} ~ {b}: mechanisms={d['shared_mechanisms']} phenotypes={d['shared_phenotypes']}")