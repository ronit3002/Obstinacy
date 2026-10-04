# review_claims.py   usage: python3 review_claims.py data/processed/paper_candidates_real.json
import json, sys

b = json.load(open(sys.argv[1], encoding="utf-8"))
sci, auth = [], []
for p in b["papers"]:
    for c in p["claims"]:
        (auth if c["relation"] == "AUTHORED" else sci).append((p["source"]["source_id"], c))

for i, (src, c) in enumerate(sci):
    print(f"\n[{i}] {src} | {c['relation']} | {c['polarity']} | {c['category']}")
    print("  statement:", c["statement"])
    print("  quote:    ", c["quote"][:300])
    for lid, e in c["entities"].items():
        r = e["resolution"]
        print(f"  {lid}: {e['kind']} {e['mention']!r} -> {r['canonical_id'] or r['status']}")

APPROVE = [0, 1, 2]
REVIEWER = "RONIT"

approved = [sci[i][1]["id"] for i in APPROVE] + [c["id"] for _, c in auth]
json.dump({"bundle_sha256": b["bundle_sha256"], "reviewer": REVIEWER,
           "approved_claim_ids": approved, "approved_summary_indices": {}},
          open("decisions.json", "w"), indent=2)
print(f"\nWrote decisions.json: {len(approved)} approved "
      f"({len(auth)} authorship, {len(APPROVE)} scientific)")