"""Re-audit lay summaries from saved evidence-checked candidates; never publish."""
import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paper_pipeline import make_backend, provider_settings, summarize_checked, validate_bundle, digest
from paper_security import load_json, write_new_json, MAX_BUNDLE_BYTES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--index', type=int, help='Refine only one saved paper index')
    args = parser.parse_args()
    backend = make_backend(*provider_settings())
    backend.client = backend.client.with_options(timeout=180, max_retries=0)
    dest = ROOT / 'data/processed/live-tests' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-lay')
    reports = []
    for path in sorted(args.run.glob('candidates-*.json')):
        if args.index is not None and path.name != f'candidates-{args.index}.json':
            continue
        bundle = load_json(path, MAX_BUNDLE_BYTES)
        validate_bundle(bundle)
        original_hash = bundle['bundle_sha256']
        for output in bundle['papers']:
            print('Refining', output['source']['source_id'], flush=True)
            # Preserve prior drafts and decisions in the existing rejected audit trail.
            output['previous_summary'] = copy.deepcopy(output['summary'])
            for claim in output['claims']:
                if claim['relation'] != 'AUTHORED':
                    claim['limitations'] = 'Not separately extracted; see source evidence and limitation-category claims.'
                    claim['id'] = 'CLAIM:' + digest({k:v for k,v in claim.items() if k != 'id'})
            summarize_checked(output, backend)
            output['quality']['summary_status'] = 'ready_for_review' if output['summary'] else 'withheld'
            reports.append({'source_id': output['source']['source_id'],
                'scientific_claims': output['quality']['scientific_claims'],
                'authorship_claims': output['quality']['authorship_claims'],
                'summary_sentences': len(output['summary']), 'summary_audit': output.get('summary_audit'),
                'published': False})
            print('Summary sentences:', len(output['summary']), flush=True)
        bundle['summary_revision'] = {'parent_bundle_sha256': original_hash,
            'purpose': 'Stricter plain-language audit', 'api_calls': list(backend.calls)}
        bundle['bundle_sha256'] = digest({k:v for k,v in bundle.items() if k != 'bundle_sha256'})
        validate_bundle(bundle)
        write_new_json(dest / path.name, bundle)
    write_new_json(dest / 'report.json', reports)
    print('Results:',dest,flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Summary refinement failed: {type(exc).__name__}; no publication performed') from None
