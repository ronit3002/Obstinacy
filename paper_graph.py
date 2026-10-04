"""Import explicitly reviewed claims; never promote negated/uncertain relations."""
import copy
from datetime import date

try:
    import schema as S
except ImportError:
    import test as S
from paper_pipeline import digest
from paper_review import validate_review


def add_reviewed_papers(graph, bundle, review):
    """Return a copy. Review is a trusted human-authored record, not model output."""
    validate_review(bundle, review)
    approved = set(review["approved_claim_ids"])
    result = copy.deepcopy(graph)
    for paper in bundle["papers"]:
        source = paper["source"]
        pid = "PAPER:" + digest([source["source_id"], source["sha256"]])
        selected = [c for c in paper["claims"] if c["id"] in approved]
        if not selected:
            continue
        S.add_node(result, pid, "Paper", name=source["title"] or source["source_id"],
                   source_id=source["source_id"], source_sha256=source["sha256"],
                   source_text=source["text"], url=source["url"], source_kind=source["source_kind"])
        for claim in selected:
            cid = claim["id"]
            if cid in result:  # importing the same reviewed bundle is idempotent
                continue
            S.add_node(result, cid, "Claim", quote=claim["quote"], pmid=source["source_id"],
                       status=claim["status"], confidence=None, model=bundle["model"],
                       prompt_version=bundle["prompt_version"], statement=claim["statement"],
                       polarity=claim["polarity"], category=claim.get("category", "finding"), study_context=claim["study_context"],
                       limitations=claim["limitations"], evidence=claim["evidence"],
                       verification=claim["verification"], reviewer=review["reviewer"],
                       bundle_sha256=bundle["bundle_sha256"], review_status="approved")
            props = dict(source=source["source_id"], source_tier=source["source_tier"],
                         retrieved=date.today().isoformat(), status=claim["status"],
                         method="llm_extracted", supported_by=[cid],
                         source_sha256=source["sha256"], evidence=claim["evidence"],
                         polarity=claim["polarity"], review_status="approved")
            S.add_edge(result, pid, cid, "CONTAINS", **props)
            nodes = {"PAPER": pid}
            for local_id, entity in claim["entities"].items():
                resolution = entity["resolution"]
                # Unresolved variants and researchers are scoped to this source;
                # identical names in different papers do not establish identity.
                nid = resolution["canonical_id"] or "MENTION:" + digest(
                    [pid, entity["kind"], entity["mention"]])
                nodes[local_id] = nid
                if nid in result and result.nodes[nid].get("type") != entity["kind"]:
                    raise ValueError("canonical ID conflicts with existing node type")
                if nid not in result:
                    S.add_node(result, nid, entity["kind"], name=entity["mention"],
                               resolution=resolution)
                S.add_edge(result, cid, nid, "ABOUT", **props,
                           mention=entity["mention"], resolution=resolution)
            # Keep all claims, but do not turn negative/uncertain statements into
            # positive biological links used by existing graph projections.
            if (claim["relation"] != "ABOUT" and claim["polarity"] == "affirmed"
                    and claim["status"] == "observation"):
                S.add_edge(result, nodes[claim["subject"]], nodes[claim["object"]],
                           claim["relation"], **props)
    errors = S.schema_violations(result)
    if errors:
        raise ValueError(f"Graph schema violations: {errors}")
    return result


def reviewed_summary(bundle, review, source_id):
    """Explicit sentence indices in review are required in addition to claim approval."""
    validate_review(bundle, review)
    approved = set(review.get("approved_claim_ids", []))
    paper = next(p for p in bundle["papers"] if p["source"]["source_id"] == source_id)
    indices = review.get("approved_summary_indices", {}).get(source_id, [])
    selected = []
    for index in indices:
        if type(index) is not int or index < 0 or index >= len(paper["summary"]):
            raise ValueError("invalid summary sentence index")
        sentence = paper["summary"][index]
        if not set(sentence["claim_ids"]) <= approved:
            raise ValueError("summary cites an unapproved claim")
        selected.append(sentence)
    return selected
