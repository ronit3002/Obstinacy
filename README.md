# Bison
Source code for Global AI Hackathon: Challenge Track 5

## Demo data pipeline (what feeds the web app)

```sh
python graph.py --paper-bundle data/processed/paper_candidates_real.json                 --aliases data/raw/disease_aliases.json --mechanisms data/raw/mechanism.json
python enrich.py            # trials, patient groups, NIH grants/PIs, HGNC gene families (cached in data/raw/enrichment_cache)
python export_ui_data.py    # -> ui/public/graph.json
cd ui && npm install && npm run dev
```

`enrich.py` uses structured sources only (no LLM): ClinicalTrials.gov API v2, NIH RePORTER API v2, HGNC REST,
and the repo's NORD, RareConnect and RARe-SOURCE scrapers. Every edge records its source, retrieval date and a
`match_reason` (e.g. "lists Dravet syndrome", "mentions the gene CDKL5"). `export_ui_data.py` then adds
`DISEASE_BRIDGE` links between diseases that share a gene family, trial, tested drug, NIH-funded investigator
(matched on RePORTER profile ID, never on name) or patient organisation.

Mechanisms: `data/curated/mechanisms.json` lists disease -> mechanism links (loss/gain of function plus the
biological process: NMDA receptor dysfunction, Nav1.1 sodium channel dysfunction, impaired neurotransmitter
release, loss of kinase signalling). Each row carries a PMID and a sentence quoted from its abstract; `enrich.py`
fetches the abstract from PubMed and drops any row whose quote is not found verbatim. Curation was AI-assisted
and is labelled "AI-curated, quote verified" in the UI until an expert has checked it. These links are added for
the app only; to let `schema.all_connections` score shared mechanisms, the new mechanism IDs would also need to be
added to `schema.MECHANISMS` and imported in `graph.py`.

Known gaps: NORD blocks automated requests from some networks, so only diseases already in the scraper's cache
(currently Dravet) get NORD organisations; run `enrich.py --refresh` from a network NORD accepts to fill the rest.

## Quick path: papers into the graph (no manual approval)

The typed `APPROVE` prompt and the HMAC signing key are no longer required. Every claim that passed
the pipeline's own checks (second-model verification, verbatim evidence, source hashes, injection
screening) is accepted automatically and marked `review_status="auto_verified"`, and the UI labels it
"AI-verified, no human review". Nothing is deleted: the human path below still works.

```sh
python paper_pipeline.py papers.json --output data/processed/paper_candidates_new.json
python graph.py --paper-bundle data/processed/paper_candidates_new.json     # one or several bundles
python export_ui_data.py --include-pending                                  # refresh the web app data
```

`python paper_review.py <bundle> <out.json>` writes the review file explicitly if you want to inspect it.
Add `--decisions <file>` (and `--sign`) to go back to a hand-picked, signed human review.

## Evidence-first paper pipeline

The default provider is now **Anthropic**. Both CLI entry points read the selected
provider's API settings from `.env` without executing it. Add:

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_MODEL=claude-sonnet-5-5
ANTHROPIC_VERIFIER_MODEL=claude-sonnet-5-5
```

The provider adapter uses [Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
with the same typed schemas, prompts, local validation and mandatory signed manual
review. Refusals, truncated output and missing parsed content fail closed. The SDK
is installed in `.venv`. An organization-level key may additionally require
`ANTHROPIC_WORKSPACE_ID` in `.env`; it is sent as the `anthropic-workspace-id` header.
Alternatively use a workspace-scoped API key. Live requests succeed after configuring a workspace accepted by the API key.
Current model IDs are listed in [Anthropic's model overview](https://platform.claude.com/docs/en/models/overview).

```sh
.venv/bin/python scripts/live_paper_test.py data/raw/live-test-pubmed/papers.json --limit 3
```

OpenAI remains available with `LLM_PROVIDER=openai` and its `OPENAI_*` settings.
No automatic provider fallback is performed. Environment variables override `.env`;
`--provider`, `--model` and `--verifier-model` override settings on `paper_pipeline.py`.
The live runner also accepts `--provider`. Provider identity is recorded in new
candidate bundles. The signing key is never loaded by provider configuration.

`paper_pipeline.py` accepts one or multiple papers/abstracts as a JSON list. Each
paper needs a unique `source_id` and its original `text`; optional fields are
`title`, `url`, `source_kind` (`abstract` or `full_text`) and `source_tier` (2 for
caller-confirmed peer-reviewed sources, otherwise 3). Keep papers separate to
preserve attribution. Input is text; PDF/OCR conversion is upstream.

```sh
python3 -m pip install -r requirements-papers.txt
# Configure ANTHROPIC_API_KEY and model IDs in .env as above; never commit keys.
python3 paper_pipeline.py examples/papers.json --output data/processed/paper_candidates.json
python3 -m unittest discover -s tests -v
```

The example is explicitly fictional, not a scientific source. API calls send
paper text to the selected provider. OpenAI calls use `store=False`; that option is
not sent to Anthropic. Provider retention policies still apply. Model selection is
explicit; set `ANTHROPIC_VERIFIER_MODEL` (or `OPENAI_VERIFIER_MODEL` for OpenAI) to use
a different model for the verification pass.
The OpenAI adapter uses the official [Responses Structured Outputs API](https://developers.openai.com/api/docs/guides/structured-outputs).
Structured Outputs enforce shape, **not factual correctness**.

### What is extracted

Genes, variants, diseases, phenotypes and investigators become entity mentions;
atomic claims link them with evidence. Authors are Researcher nodes and explicit
authorship becomes AUTHORED; other investigator mentions remain claim subjects.
Every retained claim includes a source ID and hash, exact quote and character
span, polarity, study context, limitations and verification result. Source text
is retained in the bundle for audit. URLs and titles are caller metadata, not
model-generated bibliographic assertions. Full texts are processed in overlapping
12,000-character chunks; cross-chunk claims without sufficient context are omitted.

Name resolution has explicit `mention`, `canonical_id`, `status`, `candidates`,
`method` and vocabulary snapshot hashes. It uses local `data/raw/mondo.json`,
`data/raw/hp.json`, and `data/processed/genes_resolved.json` from the existing
preparation scripts. Only exact labels and exact ontology synonyms are matched;
ambiguous names remain ambiguous. No files means unresolved names, not guessed IDs.
Variants and people remain source-local mentions until a separate identity review;
this avoids merging people with identical names or variants without transcript data.
No automatic cross-ontology equivalence is asserted from broad synonyms or xrefs.

### Hallucination controls and review

1. Strict typed output, closed relation vocabulary and endpoint validation.
2. Nonempty evidence must match the supplied text verbatim at a unique location.
   Entity mentions must also occur inside their evidence.
3. A separate model call checks semantic support, negation, context and identity.
   Any failed check rejects the claim. Refusals/API failures abort without writing
   a new output. Rejections remain in the audit bundle when the run completes.
4. Each plain-language abstract sentence cites candidate claim IDs and receives
   its own evidence check. Unsupported sentences are omitted; an empty summary is
   allowed. Candidates and summaries remain marked `pending`.
5. A human reviews original evidence, entity mappings and summary wording before
   publication. The review names the exact bundle hash and specific approved IDs.
   Altering the bundle invalidates that review. Reviews require an HMAC signature made in the reviewer environment. Keep the
   signing key restricted to the reviewer and publisher, separate from extraction.
6. Negative, uncertain and hypothetical claims remain Claim nodes; they never
   become positive biological relations used by the existing graph projections.

**Zero hallucinations cannot be guaranteed.** Verifier models can share extraction
errors; exact quotes can be misleading out of context; source papers can themselves
be wrong. This pipeline establishes source attribution, not scientific truth or
clinical validity. Contradictory papers stay as separate attributed claims. Before
production, measure precision/recall and summary faithfulness on an expert-labelled
corpus including negation, animal studies, cited authors, ambiguous aliases,
contradictions and malicious instructions in text. The offline tests verify guard
behavior, not biomedical model accuracy. No live API or clinical evaluation has
been performed as part of implementation.

### Import reviewed results into the existing graph

Create a review JSON after inspecting the candidate bundle (do not ask the model
to approve itself):

```json
{
  "bundle_sha256": "COPY_EXACT_BUNDLE_HASH",
  "reviewer": "Reviewer identifier",
  "approved_claim_ids": ["CLAIM:COPY_SELECTED_ID"],
  "approved_summary_indices": {"your-source-id": [0, 1]}
}
```

```sh
# Reviewer/publisher environment only: set PAPER_REVIEW_SIGNING_KEY to a
# securely generated random secret of at least 32 bytes, stored outside the repo.
# The extractor must NOT receive this secret. review.json is the human selection above.
python3 paper_review.py data/processed/paper_candidates.json review.json signed-review.json
# The signing command requires an explicit APPROVE confirmation after manual inspection.
python3 graph.py --paper-bundle data/processed/paper_candidates.json --paper-review signed-review.json
```

This runs the existing graph preparation, then imports approved paper claims into
`data/processed/graph.json`. Existing raw/processed graph inputs are still required.
Curated phenotype similarity is calculated before paper import. All new edges have
provenance and supporting claim IDs; repeat imports are idempotent. Unresolved
mentions use source-local IDs. Claim ABOUT edges now also support Phenotype and
Researcher nodes in the existing schema (`test.py`).

For an already loaded NetworkX graph, use
`paper_graph.add_reviewed_papers(graph, bundle, review)`; it returns a validated copy.
Use `paper_graph.reviewed_summary(bundle, review, source_id)` to obtain individually
approved summary sentences with their claim citations. An approved claim alone does
not approve the wording of its summary.

### Security boundaries

Manual review remains mandatory; there is no auto-publish option. Version-1 bundles
must be regenerated and reviewed with the version-2 pipeline. Never run the signing
command automatically on extractor output. A signature authenticates possession of
the signing key and binds the reviewer, bundle and selections; it cannot prove that
a human performed a competent review. Shared HMAC keys do not provide individual
reviewer identity or non-repudiation. For a hosted application, place signing behind
authenticated, authorized reviewer accounts and keep the extraction worker unable to
access the key or write to published graph storage. This repository provides a local
CLI, not an authenticated multi-user service.

Implemented defenses:

- Fixed instruction messages; paper and model content stays in user payloads. All
  three prompts explicitly treat embedded commands as data. No model tools, shell,
  URL fetching, code execution, or approval capability. API destination is fixed to
  `https://api.anthropic.com` or `https://api.openai.com/v1` according to provider; source URLs are metadata and never fetched.
- Input/output screening quarantines recognizable instruction overrides, role
  spoofing, approval bypasses, secret requests, active HTML and hidden control
  characters. Original evidence is preserved. This is conservative heuristic
  screening: false positives and missed/encoded attacks are possible. A flagged
  paper yields no candidates; investigate upstream and ingest a vetted source anew.
- Strict typed fields, real boolean verification values, bounded extraction lists,
  relation/identity checks, and validation repeated at publication. No guessed
  canonical IDs for variants or people. Summary citations must belong to their
  own source and refer to approved claims; their verification is checked again.
- HMAC-SHA256 signatures are checked for every graph import and summary release.
  Changing selections or content requires a new manual review and signature.
- At most 20 papers, 500,000 characters per paper and 2 million text characters per
  batch. Input JSON is capped at 8 MB; imported bundles at 32 MB. Model requests are
  limited to 160,000 payload characters, 16,000 extraction output tokens (8,000 for other calls) and 300 calls per backend
  instance (SDK retries can add up to two attempts per call). Excess work fails
  closed; split large batches. These are resource bounds, not a dollar budget.
- JSON loading rejects duplicate keys and nonfinite numbers. Candidate/review files
  use exclusive creation and owner-only permissions; existing destinations, including
  symlinks, are refused. Use a new output filename for each run. Output directories
  must be trusted and not writable by untrusted users. The existing graph exporter
  still replaces its configured graph output as before.

Treat *all* retained source text, quotes, rejection reasons and summaries as untrusted
when building a UI: render as text with escaping, never raw HTML or executable
Markdown. Do not auto-fetch links or render remote images. The pipeline does not
supply a browser UI, tenant isolation, rate limiting across users, or an API auth
layer. Enforce those at the hosting boundary before exposing it to uploads. Review
artifacts contain paper text; use controlled storage and retention. `store=False`
is not a promise of zero provider retention.

The controls follow [OpenAI's prompt-injection guidance](https://developers.openai.com/api/docs/guides/agent-builder-safety).
They reduce attack paths but do not establish immunity to prompt injection or
scientific misinformation. Offline adversarial tests cover deterministic controls
and request construction; live model attack-resistance evaluation is still needed.

### API key and image-based tests

Set `ANTHROPIC_API_KEY` in the project-root `.env` or the environment. Both CLI
entry points parse `.env` safely with variable interpolation disabled. They load only
the selected provider's API key/model settings and never the review signing key.
No shell `source` command is needed. Never send the key through chat.

```sh
.venv/bin/python paper_pipeline.py examples/image_disease_papers.json --output data/processed/image-candidates.json
```

`examples/image_disease_cases.json` transcribes selected disease, gene, variant and
phenotype fields from the supplied image. `examples/image_disease_papers.json` is a
runnable **unverified table-text input**, not seven real papers. Neither file asserts
that the screenshot's classifications or identifiers are medically correct.

`tests/test_image_diseases.py` covers all seven rows (DEE27, NDHMSD, GRIN2A-related
encephalopathy, DEE46, DEE4/STXBP1, DEE2/CDKL5, and Dravet). It uses hand-authored
model responses to exercise evidence spans, source isolation, pending review,
signature requirements, source-local variants and injection quarantine. Test-only
disease aliases come from the processed seed snapshot; HPO mappings come from the
image. Passing these tests does not validate the underlying ontology mappings,
variant pathogenicity, model extraction, or medical accuracy. No test approval is
written to disk and the production graph is not changed.

### Reproducible live smoke test

The live test runner explicitly reads API settings from `.env` (without shell
execution or variable interpolation). The main pipeline CLI uses the same settings loader. The runner never reads the
review signing key and never publishes.

```sh
.venv/bin/python scripts/fetch_test_abstracts.py
.venv/bin/python scripts/live_paper_test.py data/raw/live-test-pubmed/papers.json --limit 3
```

The corpus contains PubMed abstracts 28377535 (GRIN2B), 27616483 (GRIN2D), and
28538134 (Dravet syndrome). The XML response and extracted text are retained under
`data/raw/live-test-pubmed/`. Candidate bundles and safe error reports are saved in
separate timestamped directories under `data/processed/live-tests/`. The runner
stops on the first error and prints no raw authentication exception or API key.
A completed run is a smoke test of extraction/evidence plumbing, not a validated
clinical accuracy benchmark.


### Live test outcome (4 October 2026, Europe/Berlin)

Three public PubMed abstracts were processed using `claude-sonnet-5-5` for both
extraction and verification. The first run exposed confusing temporary vs durable
summary citation IDs. Version `papers-v3-summary-citations` now presents short,
unambiguous citation aliases to the summarizer and maps only known aliases back to
durable IDs. A regression test covers unknown aliases. The verifier prompt now
clarifies that a missing canonical vocabulary ID alone does not disprove an
unambiguous source-local mention.

The rerun retained 5 claims/3 summary sentences for PMID:28377535, 0/0 for
PMID:27616483 (five non-verbatim quote rejections), and 1/3 for PMID:28538134.
Results and import-gate checks are in
`data/processed/live-tests/20261003T224137Z/`. All outputs remain pending, all three
bundles pass deterministic validation, and unsigned publication is blocked.
The 38 offline tests pass.

These are operational tests, not precision/recall or clinical validation. Coverage
is incomplete: treatment results may not fit the current entity/relation schema;
summary sentences may lack context after other sentences are rejected. Exact quote
matching can reject useful candidates and currently withheld all GRIN2D candidates.
The output is not ready for unreviewed patient-facing use. No source claims were
approved or published by these tests.

### Version 4: broader coverage and coherent summaries

`papers-v4-anchored-evidence` replaces generated evidence quotations with passage
selection: the model selects a numbered input passage and Python copies its exact
text. Quotes and offsets still undergo deterministic validation. Entity mentions
must still occur verbatim; missing/ambiguous entity references cannot be inferred.
An exact unique entity name used instead of an ID can be normalized to that ID;
no fuzzy reference repair is performed.

The extraction schema includes Intervention, Outcome and Study alongside Disease,
Gene, Variant, Phenotype and Researcher. Claims carry a category (background,
study_design, result, limitation, authorship or finding). General study findings
use claim ABOUT links rather than inventing new biological relationships. Explicit
`Title:/Authors:/Abstract:` source metadata preserves all named authors as
source-local researchers. Their exact metadata assertions are checked deterministically;
scientific claims still require model verification. Metadata authors are not also
generated by the model, preventing duplicate entries in large author lists.

The separate verifier audits batches of at most six claims; every candidate must
receive exactly one explicitly keyed verdict. No missing or duplicated verdict can
pass. Quotes, qualifiers, numbers, negation, experimental setting and limitations
remain checked. A broad ABOUT link is structural, not a causal assertion.

The summary is generated from non-authorship claims, then checked as a whole
against cited claims and the original source for factual support, coherence,
central findings and limitations. One revision is allowed and audited again. A
failing summary is withheld entirely instead of dropping sentences and leaving
pronouns or incomplete paragraphs. This checks coverage with a model; it is not a
formal proof of completeness or clinical validity. `summary_audit`, `coverage` and
`quality` report omissions, unresolved terms and review state.

Official MONDO and HPO files can be installed with:

```sh
.venv/bin/python scripts/fetch_vocabularies.py
```

The downloaded snapshots are hashed in resolution provenance. Unique exact names
or exact synonyms resolve automatically. Similar names yield `suggestion_only`
candidates with lexical scores, while `canonical_id` remains null. Review these
suggestions; a score is not medical equivalence. Missing transcript identity still
prevents automatic variant merging, and names alone do not merge researchers
across papers. No inferred relationship or identity is published without the
existing signed human approval.

### Improved live review packet

The current review packet is `data/processed/improved-review-candidates/`:
`READ-ME.txt` contains the three lay drafts, `report.json` gives counts,
`candidates-*.json` contains full sources, spans, identity resolution and rejection
history, and `audit.json` records final checks. Nothing has been approved or published.

| PubMed paper | Scientific claims | Named authorship claims | Lay sentences |
| --- | ---: | ---: | ---: |
| 28377535 (GRIN2B) | 10 | 75 | 8 |
| 27616483 (GRIN2D) | 5 | 24 | 7 |
| 28538134 (Dravet) | 10 | 10 | 8 |

All three final drafts passed source-support, coherence, central-findings,
limitations and plain-language model audits. Final bundle/span validation and
unsigned-import rejection passed; 46 offline tests pass. Counts are **retained
candidates**, not precision/recall measurements. This test corpus contains three
abstracts, not a representative full-paper evaluation.

Live testing exposed unsupported free-text caveats and inaccurate simplification
of laboratory potency measurements. Free-text context/limitation metadata is now
excluded from summary evidence. New extraction stores explicit limitations as
anchored claims instead of inferred caveats, and lay summaries leave secondary
laboratory measurements in the evidence-linked claims. Statistical labels such as
median must be preserved. Whole-summary failures remain visible and are withheld.
The final Dravet draft also received an explicit median wording correction and a
fresh source audit before inclusion in the review packet.

`scripts/refine_live_summaries.py RUN --index N` regenerates one saved paper's
summary without repeating extraction. Each regeneration changes the bundle hash
and therefore needs fresh human approval. Failed drafts remain in the audit trail.
`scripts/assemble_live_review.py` records the specific sources used for this test
packet; it is a corpus-specific assembly utility, not an automatic publication path.
Similar-name ontology suggestions still require review; variants without transcript
context and investigator names remain source-local. Medical accuracy and complete
recall require expert evaluation before deployment.
