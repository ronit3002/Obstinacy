"""Import explicitly reviewed paper claims into the Atlas graph.

Rules
-----
* Only claims in the signed review are imported; the review is a trusted
  human record, model output is not.
* Every imported claim stays visible as a Claim node (CONTAINS / ABOUT).
* A direct scientific edge is created only for an AFFIRMED OBSERVATION whose
  endpoints are resolved (vocabulary ID or reviewed alias). Unresolved
  Variants are allowed on ASSOCIATED_WITH / IN_GENE only.
* If that edge already exists, the paper CORROBORATES it (evidence is appended)
  instead of creating a parallel edge.
* Negated / uncertain claims never create positive links. If they concern an
  existing edge, they are attached to it as counter_evidence and flagged.
* Nodes that exist only because of a paper are marked paper_scoped=True so
  clustering / matching can ignore them.
* Researchers are never merged across papers (name_key is stored for an
  explicitly unverified name match).
"""
import copy
from datetime import date

import schema as S
from paper_pipeline import digest, norm
from paper_review import validate_review
from paper_security import load_json

PROMOTABLE = {"ASSOCIATED_WITH", "HAS_PHENOTYPE", "IN_GENE"}
VARIANT_OK = {"ASSOCIATED_WITH", "IN_GENE"}   # unresolved variants allowed here


# ------------------------------------------------------------- helpers ------

def _clean(resolution):
    """Drop machine-local paths / hashes before they reach graph outputs."""
    return {k: v for k, v in resolution.items() if k != "vocabulary_snapshots"}


def _add(G, src, dst, rel, props, **extra):
    """add_edge with private copies, so edges never share mutable lists."""
    S.add_edge(G, src, dst, rel, **{**copy.deepcopy(props), **extra})


def _paper_id(source):
    return "PAPER:" + digest([source["source_id"], source["sha256"]])


def _ensure_paper(G, source):
    pid = _paper_id(source)
    if pid not in G:
        S.add_node(G, pid, "Paper", name=source["title"] or source["source_id"],
                   source_id=source["source_id"], source_sha256=source["sha256"],
                   source_chars=len(source["text"]), url=source["url"],
                   source_kind=source["source_kind"])
    return pid


def _evidence_item(source, claim_id, evidence, polarity):
    return {"via": source["source_id"], "claim": claim_id,
            "quote": evidence["quote"], "start": evidence["start"],
            "end": evidence["end"], "polarity": polarity}


# ------------------------------------------------------------- aliases ------

def load_aliases(path):
    """Reviewed mention -> canonical ID overrides (human decisions)."""
    aliases = {}
    for mention, row in load_json(path).items():
        if not str(row.get("canonical_id", "")).strip() or not str(row.get("reviewer", "")).strip():
            raise ValueError(f"alias {mention!r} needs canonical_id and reviewer")
        aliases[norm(mention)] = row
    return aliases


def _apply_alias(entity, aliases):
    if (not aliases or entity["kind"] != "Disease"
            or entity["resolution"].get("canonical_id")):
        return entity
    hit = aliases.get(norm(entity["mention"]))
    if not hit:
        return entity
    resolution = {**entity["resolution"], "canonical_id": hit["canonical_id"],
                  "status": "resolved", "method": "reviewed_alias",
                  "reviewer": hit["reviewer"], "note": hit.get("note", "")}
    return {**entity, "resolution": resolution}


def _endpoint_ok(entity, rel):
    if entity["resolution"].get("canonical_id"):
        return True
    return entity["kind"] == "Variant" and rel in VARIANT_OK


# ------------------------------------------------------- claim import -------

def _import_claim(G, bundle, review, source, pid, claim, aliases, today):
    cid = claim["id"]
    if cid in G:                      # re-importing the same bundle is a no-op
        return
    item = _evidence_item(source, cid, claim["evidence"], claim["polarity"])

    S.add_node(G, cid, "Claim", quote=claim["quote"], pmid=source["source_id"],
               status=claim["status"], confidence=None, model=bundle["model"],
               prompt_version=bundle["prompt_version"], statement=claim["statement"],
               polarity=claim["polarity"], category=claim.get("category", "finding"),
               study_context=claim["study_context"], limitations=claim["limitations"],
               evidence=claim["evidence"], verification=claim["verification"],
               reviewer=review["reviewer"], bundle_sha256=bundle["bundle_sha256"],
               review_status="approved")

    props = dict(source=source["source_id"], source_tier=source["source_tier"],
                 retrieved=today, status=claim["status"], method="llm_extracted",
                 supported_by=[cid], source_sha256=source["sha256"],
                 evidence=[item], polarity=claim["polarity"], review_status="approved")

    _add(G, pid, cid, "CONTAINS", props)

    nodes, entities = {"PAPER": pid}, {}
    for local_id, raw in claim["entities"].items():
        entity = _apply_alias(raw, aliases)
        entities[local_id] = entity
        res = entity["resolution"]
        nid = res["canonical_id"] or "MENTION:" + digest(
            [pid, entity["kind"], entity["mention"]])
        nodes[local_id] = nid
        if nid in G:
            if G.nodes[nid].get("type") != entity["kind"]:
                raise ValueError(f"{nid}: canonical ID conflicts with existing node type")
        elif res.get("method") == "reviewed_alias":
            raise ValueError(f"alias target {nid} is not in the graph")
        else:
            extra = {}
            # unresolved, or a disease that is not one of the seed diseases
            if not res["canonical_id"] or entity["kind"] == "Disease":
                extra["paper_scoped"] = True
            if entity["kind"] == "Researcher":
                extra.update(name_key=norm(entity["mention"]), identity="name_match_only")
            S.add_node(G, nid, entity["kind"], name=entity["mention"],
                       resolution=_clean(res), **extra)
        _add(G, cid, nid, "ABOUT", props, mention=entity["mention"],
             resolution=_clean(res))

    rel = claim["relation"]

    if rel == "AUTHORED" and claim["object"] == "PAPER":
        sid = nodes.get(claim["subject"])
        if sid and claim["polarity"] == "affirmed":
            _add(G, sid, pid, "AUTHORED", props)
        return

    if rel not in PROMOTABLE:
        return
    s_ent, o_ent = entities.get(claim["subject"]), entities.get(claim["object"])
    if not (s_ent and o_ent and _endpoint_ok(s_ent, rel) and _endpoint_ok(o_ent, rel)):
        return
    s, o = nodes[claim["subject"]], nodes[claim["object"]]
    existing = [d for d in (G.get_edge_data(s, o) or {}).values() if d.get("rel") == rel]

    if claim["polarity"] != "affirmed":
        for d in existing:            # surface contradictions, never hide them
            d.setdefault("counter_evidence", []).append(copy.deepcopy(item))
            d["contradicted" if claim["polarity"] == "negated" else "uncertain"] = True
        return
    if claim["status"] != "observation":
        return

    if existing:
        d = existing[0]
        d.setdefault("evidence", []).append(copy.deepcopy(item))
        if cid not in d.setdefault("supported_by", []):
            d["supported_by"].append(cid)
        if d.get("status") == "hypothesis":
            d["status"] = "observation"
            d["source_tier"] = min(d["source_tier"], source["source_tier"])
    else:
        _add(G, s, o, rel, props)


def add_reviewed_papers(graph, bundle, review, aliases=None):
    """Return a copy of graph with the approved claims imported."""
    validate_review(bundle, review)
    approved = set(review["approved_claim_ids"])
    result = copy.deepcopy(graph)

    # DEBUG: inspect the graph BEFORE importing papers
    print("\n== Checking base graph ==")
    bad_count = 0

    for u, v, key, data in result.edges(keys=True, data=True):
        missing = S.REQUIRED_EDGE_PROPS - set(data.keys())

        if missing:
            bad_count += 1
            if bad_count <= 30:
                print(
                    "BAD EDGE:",
                    repr(u),
                    "--",
                    data.get("rel"),
                    "-->",
                    repr(v),
                    "missing:",
                    sorted(missing),
                    "data:",
                    data,
                )

    print(f"Base graph edges missing required props: {bad_count}")

    today = date.today().isoformat()

    for paper in bundle["papers"]:
        source = paper["source"]
        selected = [c for c in paper["claims"] if c["id"] in approved]

        if not selected:
            continue

        pid = _ensure_paper(result, source)

        for claim in selected:
            _import_claim(
                result,
                bundle,
                review,
                source,
                pid,
                claim,
                aliases,
                today,
            )

    errors = S.schema_violations(result)

    if errors:
        print("\n== Schema errors after paper import ==")
        print(f"Total: {len(errors)}")
        for error in errors[:30]:
            print(error)

        raise ValueError(f"Graph schema violations: {errors}")

    return result


# ------------------------------------------------- curated mechanisms -------

def add_curated_mechanisms(graph, curation, bundle):
    """Human-recorded Disease INVOLVES Mechanism, each with a verbatim quote.

    curation: [{"disease": "MONDO:..", "mechanism": "MECH:..", "source_id": "PMID:..",
                "quote": "<verbatim from the paper>", "reviewer": "name"}]
    The quote must appear verbatim in the bundle's source text.
    """
    result = copy.deepcopy(graph)
    sources = {p["source"]["source_id"]: p["source"] for p in bundle["papers"]}
    today = date.today().isoformat()
    for row in curation:
        src = sources.get(row["source_id"])
        if src is None:
            raise ValueError(f"unknown source {row['source_id']}")
        if not row.get("quote") or row["quote"] not in src["text"]:
            raise ValueError(f"quote not found verbatim in {row['source_id']}")
        if result.nodes.get(row["disease"], {}).get("type") != "Disease":
            raise ValueError(f"unknown disease {row['disease']}")
        if row["mechanism"] not in S.MECHANISMS:
            raise ValueError(f"unknown mechanism {row['mechanism']}")
        if not str(row.get("reviewer", "")).strip():
            raise ValueError("curated mechanism needs a reviewer")

        cid = "CLAIM:" + digest([row["source_id"], row["disease"],
                                 row["mechanism"], row["quote"]])
        if cid in result:
            continue
        pid = _ensure_paper(result, src)
        start = src["text"].find(row["quote"])
        evidence = {"quote": row["quote"], "start": start, "end": start + len(row["quote"])}
        item = _evidence_item(src, cid, evidence, "affirmed")

        S.add_node(result, cid, "Claim", quote=row["quote"], pmid=row["source_id"],
                   status="observation", confidence=None, model="human-curated",
                   prompt_version="n/a", polarity="affirmed", category="mechanism",
                   statement=(f"{result.nodes[row['disease']].get('name')} involves "
                              f"{S.MECHANISMS[row['mechanism']].lower()}"),
                   evidence=evidence, reviewer=row["reviewer"], review_status="curated")

        props = dict(source=row["source_id"], source_tier=src["source_tier"],
                     retrieved=today, status="observation", method="curated_import",
                     supported_by=[cid], evidence=[item], polarity="affirmed",
                     review_status="curated")
        _add(result, pid, cid, "CONTAINS", props)
        _add(result, cid, row["disease"], "ABOUT", props)
        _add(result, cid, row["mechanism"], "ABOUT", props)
        _add(result, row["disease"], row["mechanism"], "INVOLVES", props)

    errors = S.schema_violations(result)
    if errors:
        raise ValueError(f"Graph schema violations: {errors}")
    return result