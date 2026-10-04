"""Reviewer-only signing command. Never expose this command or its key to models."""
import argparse
from pathlib import Path

from pydantic import Field
from paper_pipeline import StrictModel, validate_bundle
from paper_security import (load_json, write_new_json, review_signature,
                            require_signed_review, MAX_BUNDLE_BYTES)


class Review(StrictModel):
    bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1, max_length=256)
    approved_claim_ids: list[str] = Field(max_length=12000)
    approved_summary_indices: dict[str, list[int]]
    signature: str | None = None


def validate_review(bundle, review, *, require_signature=True, key=None):
    Review.model_validate(review)
    validate_bundle(bundle)
    if require_signature:
        require_signed_review(review, key)
    if not review["reviewer"].strip() or review["bundle_sha256"] != bundle["bundle_sha256"]:
        raise ValueError("review must identify a reviewer and match the bundle")
    approved = set(review["approved_claim_ids"])
    all_ids = {c["id"] for p in bundle["papers"] for c in p["claims"]}
    if len(approved) != len(review["approved_claim_ids"]) or not approved <= all_ids:
        raise ValueError("duplicate or unknown approved claim IDs")
    papers = {p["source"]["source_id"]: p for p in bundle["papers"]}
    for source_id, indices in review["approved_summary_indices"].items():
        if source_id not in papers or len(indices) != len(set(indices)):
            raise ValueError("unknown summary source or duplicate indices")
        for index in indices:
            if index < 0 or index >= len(papers[source_id]["summary"]):
                raise ValueError("invalid summary sentence index")
            if not set(papers[source_id]["summary"][index]["claim_ids"]) <= approved:
                raise ValueError("summary cites an unapproved claim")


def sign_review(bundle, review, *, key=None):
    validate_review(bundle, review, require_signature=False)
    signed = {**review, "signature": review_signature(review, key)}
    return signed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("decisions", type=Path, help="Human-authored selection of approved claims/sentences")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    bundle = load_json(args.bundle, MAX_BUNDLE_BYTES)
    decisions = load_json(args.decisions)
    validate_review(bundle, decisions, require_signature=False)
    # No paper/model-controlled text is printed in the confirmation prompt.
    print(f"Selected {len(decisions['approved_claim_ids'])} claims for bundle {bundle['bundle_sha256']}.")
    if input("After inspecting the source evidence and selected summary sentences, type APPROVE: ") != "APPROVE":
        raise SystemExit("Not approved; no review written")
    write_new_json(args.output, sign_review(bundle, decisions))


if __name__ == "__main__":
    main()
