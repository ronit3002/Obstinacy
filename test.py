# summarize_ui_graph.py   usage: python summarize_ui_graph.py data/processed/ui_graph.json
import json, sys
from collections import Counter, defaultdict

g = json.load(open(sys.argv[1], encoding="utf-8"))
nodes = g["nodes"]
edges = g.get("edges") or g.get("links")
ntype = {n["id"]: n.get("type") for n in nodes}
name = {n["id"]: (n.get("name") or n["id"]) for n in nodes}

EXPECTED_TYPES = ["Disease", "Gene", "Variant", "Mechanism", "Phenotype", "Paper", "Claim",
                  "Study", "PatientOrg", "Registry", "Researcher", "Intervention", "Outcome"]
EXPECTED_RELS = ["ASSOCIATED_WITH", "HAS_PHENOTYPE", "IN_GENE", "INVOLVES", "DISRUPTS",
                 "CONTAINS", "ABOUT", "AUTHORED", "STUDIES", "REPRESENTED_BY",
                 "MAINTAINS", "DISEASE_MATCH"]

types = Counter(ntype.values())
rels = Counter(e.get("rel") for e in edges)
print("nodes:", len(nodes), " edges:", len(edges))
print("\nnode types:", dict(types))
print("  absent types:", [t for t in EXPECTED_TYPES if t not in types])
print("\nrelations:", dict(rels))
print("  absent relations:", [r for r in EXPECTED_RELS if r not in rels])

print("\nstatus / tier / method per relation:")
by = defaultdict(Counter)
for e in edges:
    by[e.get("rel")][(e.get("status"), e.get("source_tier"), e.get("method"))] += 1
for r, c in by.items():
    print(" ", r, dict(c))

mention = [n for n in nodes if str(n["id"]).startswith("MENTION:")]
print("\nMENTION (unresolved) nodes:", dict(Counter(n.get("type") for n in mention)))

ev = Counter()
for e in edges:
    if e.get("rel") in {"ASSOCIATED_WITH", "HAS_PHENOTYPE", "IN_GENE", "INVOLVES", "DISRUPTS"}:
        ev[(e["rel"], bool(e.get("supported_by")), bool(e.get("contradicted")))] += 1
print("\nscientific edges (rel, has_claim_support, contradicted):", dict(ev))

print("\nper disease (out-edge rels | claims about it):")
claims_about = Counter(e["target"] for e in edges if e.get("rel") == "ABOUT")
out = defaultdict(Counter)
for e in edges:
    if ntype.get(e["source"]) == "Disease" and e.get("rel") != "DISEASE_MATCH":
        out[e["source"]][e["rel"]] += 1
for d, t in ntype.items():
    if t == "Disease":
        print(f"  {d} {name[d][:45]!r}: {dict(out[d])} | claims={claims_about[d]}")

print("\nDISEASE_MATCH edges:")
for e in sorted((e for e in edges if e.get("rel") == "DISEASE_MATCH"),
                key=lambda e: -e.get("score", 0)):
    print(f"  {e['source']} ~ {e['target']}  score={e.get('score')}  "
          f"type={e.get('connection_type')}  conf={e.get('confidence')}")

print("\nclaims by polarity / category:")
print(" ", dict(Counter((n.get("polarity"), n.get("category")) for n in nodes if n.get("type") == "Claim")))