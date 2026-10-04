# Bison Atlas: 8-hour plan to a working demo

Target for the judges (Challenge 5, page 6, "What good looks like"):
**Maria searches her disease → follows a mechanism to another gene → a related disease → its patient group,
finds a reusable registry or study, and leaves with a sourced next step.** Every edge has a source.
If no lead is supported, the atlas says so and explains what evidence is missing.

## Where we stand vs. the brief

| Brief requirement | Status | Gap |
|---|---|---|
| Disease, gene, variant, phenotype nodes (MONDO, HGNC, ClinVar, HPO) | ✅ in `graph.json` | – |
| Provenance on every edge (source, tier, status, method) | ✅ schema + validator | `source` name lost in export (node-link key clash), patched in `export_ui_data.py` |
| **Mechanism** layer (LoF/GoF, pathway); "names hide mechanisms" | ❌ 2 empty Mechanism nodes | **Most important gap.** No disease→mechanism→disease path exists |
| Papers → claims → investigators (PubMed + LLM extraction) | ❌ schema only | needed for evidence and the "connector" persona |
| Patient orgs / registries (NORD, Orphanet, RareConnect) | ⚠️ scrapers exist, not in graph | needed for the patient action view |
| Studies / trials (ClinicalTrials.gov) | ❌ | the "reusable asset" in the demo story |
| Clustering by mechanism + phenotype | ⚠️ `schema.cluster()` exists, not used in UI | |
| Uncertainty, contradictions, honest "no supported route" | ⚠️ status shown, nothing else | |
| **OpenAI used** (required for track prizes) | ❌ | extraction + plain-language explanations must use OpenAI |
| UI: one global search, progressive reveal, explain every edge, patient action view | ⚠️ search ✓, rest partial | iOS-style redesign is in progress |
| Deployed prototype, README (architecture and reproduce steps), 1-minute video, 10× argument | ❌ | |

**Is the disease set wrong?** No. It's a good slice, but the story has to run through mechanism, not genes:
- GRIN1, GRIN2A, GRIN2B and GRIN2D are all **NMDA-receptor subunits**. Different gene names, same receptor. That is exactly the brief's "names hide mechanisms" point.
- GRIN2A and GRIN2B carry both **loss- and gain-of-function** variants with different phenotypes. That gives us the counterexample judges ask for (same gene, different mechanism); `schema.same_gene_different_mechanism` already exists for this.
- SCN1A (Dravet) has approved drugs, registries and trials. Those are the **reusable assets** a GRIN family could learn from.
- STXBP1 and CDKL5 are synaptic and signalling DEEs with active foundations and trials.

So we don't need new diseases. We need the **mechanism, paper, patient-group and trial layers**.
Optionally, add 3–6 diseases later (e.g. GRIN2B-related ID without seizures, SCN2A, SCN8A, KCNQ2) for richer clusters.

## Graph path the UI will support
```
Disease ──ASSOCIATED_WITH── Gene ──MEMBER_OF── Gene group (HGNC, e.g. "NMDA receptor subunits") ── Gene ── Disease
                              └─ Variant ──DISRUPTS── Mechanism (LoF / GoF) ──INVOLVES── Disease   (claims w/ quotes)
Disease ──HAS_PHENOTYPE── Phenotype ── HPO category (e.g. "Movement disorder") ── other diseases
Disease ──REPRESENTED_BY── PatientOrg ──MAINTAINS── Registry;  Study ──STUDIES── Disease
Paper ──CONTAINS── Claim ──ABOUT── Gene/Variant/Mechanism;  Researcher ──AUTHORED── Paper
```

## Timeline (4 people in parallel; with fewer people, merge tracks A+D and B+C)

### Hour 0–1: unblock (everyone)
1. `graph.py` imports `test as S`, but the file is `schema.py`. Fix the import.
2. Export with `nx.node_link_data(G, source="from", target="to")` so the edge provenance `source` survives.
3. Re-download `data/raw` (gitignored) and check that `extractor.py → resolve.py → clinvar.py → graph.py → export_ui_data.py` runs end to end.
4. Agree on the demo journey (below). Everything else serves it.

### Hour 1–5: four parallel tracks
**A: Mechanism + papers (OpenAI, Module 1/2)**
- PubMed E-utilities: ~20 top abstracts per gene (reviews + functional studies). Authors and affiliations come from PubMed metadata, not the LLM.
- OpenAI structured output → `Claim{quote, pmid, subject(gene/variant), mechanism, direction(LoF|GoF), confidence}`.
- Keep a claim only if `unverified_claims()` finds the quote verbatim in the abstract. Then add `DISRUPTS`/`INVOLVES` edges with `supported_by`.
- Record contradictions: same gene, claims with opposite directions → `contradicted_by` on the edge.
- Add HGNC **gene groups** (`gene_group` field in the HGNC REST API) as `MEMBER_OF` edges. This is the curated, LLM-free path GRIN1 ↔ GRIN2B.

**B: Patient groups, registries and trials (Module 3 assets)**
- NORD / Orphanet scrapers → `PatientOrg` (+ url) → `REPRESENTED_BY`; registries → `MAINTAINS`.
- ClinicalTrials.gov API v2, query per disease and gene → `Study` nodes (status, phase, intervention, NCT link) → `STUDIES`.
- Mark each asset as reusable or not (registry, natural-history study, model).

**C: UI (Module "make it understandable")**
- iOS-style redesign: floating search, bubble nodes, soft cluster clouds, bottom-sheet card. *(in progress)*
- Phenotype **categories**: group the 177 HPO terms under their top-level HPO ancestor. Clicking a category shows which diseases share it.
- **Path view.** "Why is X connected to Y?" shows the shortest evidence path as a step list. Each step shows its source and confidence, and observation vs. inference.
- **Patient action view** (card tab "What can we do?"): patient groups, registries, trials, researchers, suggested next step.
- **Honest gap state:** "No supported mechanistic link found. Searched: N papers, M trials. Missing: …"

**D: Explanations, clustering and 10× story**
- Clustering: phenotype simGIC + shared mechanism + shared gene group → Louvain (`schema.cluster` extended). Export the cluster ID and name for each disease.
- OpenAI "Explain", precomputed at build time and cached into `graph.json` (no API key in the browser):
  per-disease summary and per-connection plain-language explanation. The prompt gets only graph facts plus claim quotes and must cite edge IDs.
- Write the 10× argument: e.g. "time to a shared natural-history study for GRIN disorders: today ~3–5 years of
  outreach, with the atlas weeks". State the assumptions.

### Hour 5–6.5: integrate
- Merge all layers into one `graph.json`, rerun the validators (`schema_violations`, `unsupported_inferences`), export, and check the UI.
- Freeze the data. From here on, UI polish and bug fixes only.

### Hour 6.5–8: ship
- Deploy `ui/dist` to Vercel/Netlify (static; `npm run build`). Test on a phone.
- README: architecture diagram, data sources, how to reproduce, validation rules, limitations.
- Record the 1-minute walkthrough (script below) and the team video. Submit.

## Demo journey (script for the video)
1. Maria (GRIN2B parent) types "GRIN2B" → disease card: summary, gene, 3 closest diseases.
2. She taps the gene → gene group "NMDA receptor" → GRIN1 and GRIN2A light up (different names, same receptor).
3. She taps the link GRIN2B ↔ GRIN2A → "Why connected": shared receptor (HGNC), shared rare phenotypes
   (e.g. hyperkinetic movements), LoF claim with PubMed quote. The counterexample: GoF variants differ.
4. "What can we do?" → CureGRIN / GRIN2B Foundation, existing registry, a trial in a neighbouring disease, two researchers
   who appear on papers for both genes → suggested next step: "Ask registry X whether GRIN2B patients can join; validate Y."
5. Honest gap: SCN1A ↔ GRIN2B has phenotype overlap but no mechanistic support → shown as "unsupported, needs Z".

## About the old "similarity %"
The percentage was **simGIC**: an information-content-weighted Jaccard over each disease's HPO terms plus all their
ancestors. IC = −log2(share of all HPO-annotated diseases that have the term), so rare features weigh more than
"Seizure". Score = IC of shared terms ÷ IC of all terms of both diseases.
The method is valid, but a bare % is not meaningful to a family. Replace it with:
a strength label (strong / moderate / weak), a rank ("closest of N diseases"), and the 3 most informative shared features.
