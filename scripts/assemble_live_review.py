"""Assemble this test corpus's reviewed-by-model drafts, never human approvals."""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paper_pipeline import make_backend, provider_settings, validate_bundle, digest, Verification
from paper_security import load_json, write_new_json, MAX_BUNDLE_BYTES


def main():
    paths = [
        ROOT/'data/processed/live-tests/20261003T230004Z-lay/candidates-0.json',
        ROOT/'data/processed/live-tests/20261003T230945Z-lay/candidates-1.json',
        ROOT/'data/processed/live-tests/20261003T230004Z-lay/candidates-2.json',
    ]
    output = ROOT/'data/processed/improved-review-candidates'
    backend = make_backend(*provider_settings())
    backend.client = backend.client.with_options(timeout=180,max_retries=0)
    report = []
    readable = ['REVIEW CANDIDATES — NOT APPROVED OR PUBLISHED',
        'Automated checks do not establish medical accuracy. Original source evidence and signed human review remain required.\n']
    for i, path in enumerate(paths):
        bundle = load_json(path, MAX_BUNDLE_BYTES)
        validate_bundle(bundle)
        original_hash = bundle['bundle_sha256']
        paper = bundle['papers'][0]
        if i == 2:
            # Preserve the source's statistic explicitly in this review draft.
            paper['previous_summary'] = copy.deepcopy(paper['summary'])
            for sentence in paper['summary']:
                if sentence['text'].startswith('Over 14 weeks, convulsive seizures per month fell'):
                    sentence['text'] = sentence['text'].replace(
                        'convulsive seizures per month fell',
                        'the median (middle value) number of convulsive seizures per month fell', 1)
            audit = backend.audit_summary(paper['summary'],paper['claims'],paper['source']['text'])
            paper['summary_audit'] = audit.model_dump()
            if not audit.passes():
                raise RuntimeError('Corrected summary failed audit; nothing approved')
            for sentence in paper['summary']:
                sentence['verification'] = Verification(supported=True,entities_correct=True,
                    relation_correct=True,polarity_correct=True,context_preserved=True,
                    reason='Whole-summary audit: '+audit.reason).model_dump()
        bundle['review_packet'] = {'parent_bundle_sha256': original_hash,
            'status': 'pending_human_review', 'correction': 'Statistical label preserved in Dravet draft' if i == 2 else None}
        bundle['bundle_sha256'] = digest({k:v for k,v in bundle.items() if k != 'bundle_sha256'})
        validate_bundle(bundle)
        write_new_json(output/f'candidates-{i}.json',bundle)
        row = {'source_id':paper['source']['source_id'],
               'scientific_claims':paper['quality']['scientific_claims'],
               'authorship_claims':paper['quality']['authorship_claims'],
               'summary_sentences':len(paper['summary']),
               'source_url':paper['source']['url'], 'published':False}
        report.append(row)
        readable += [paper['source']['title'],paper['source']['url'],
                     ' '.join(s['text'] for s in paper['summary']),
                     f"{row['scientific_claims']} scientific claims; {row['authorship_claims']} authorship claims.\n"]
        print(json.dumps(row),flush=True)
    write_new_json(output/'report.json',report)
    (output/'READ-ME.txt').write_text('\n\n'.join(readable))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Review assembly failed: {type(exc).__name__}; no publication performed') from None
