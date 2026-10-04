"""Explicit live test; loads only API settings from .env, never review secrets."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paper_pipeline import make_backend, provider_settings, Vocabulary, run_pipeline, validate_bundle
from paper_security import load_json, write_new_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--provider', choices=['anthropic', 'openai'])
    args = parser.parse_args()
    try:
        provider, model, verifier = provider_settings(args.provider)
    except ValueError as exc:
        raise SystemExit(str(exc))
    print(f'Provider: {provider}; extractor: {model}; verifier: {verifier}', flush=True)
    backend = make_backend(provider, model, verifier)
    original_ask = backend.ask
    def traced_ask(schema, prompt, payload, **kwargs):
        print(f'  {schema.__name__}: requesting', flush=True)
        result = original_ask(schema, prompt, payload, **kwargs)
        print(f'  {schema.__name__}: completed', flush=True)
        return result
    backend.ask = traced_ask
    # Avoid retry storms during account/model availability checks.
    backend.client = backend.client.with_options(max_retries=0, timeout=180)
    papers = load_json(args.input)[:args.limit]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = ROOT / 'data/processed/live-tests' / stamp
    output.mkdir(parents=True, exist_ok=False)
    reports = []
    for index, paper in enumerate(papers):
        print(f'Testing {paper["source_id"]}', flush=True)
        try:
            bundle = run_pipeline([paper], backend, Vocabulary.from_directory(ROOT / 'data'))
            validate_bundle(bundle)
            write_new_json(output / f'candidates-{index}.json', bundle)
            record = bundle['papers'][0]
            report = {'source_id': paper['source_id'], 'status': 'completed',
                      'claims': len(record['claims']), 'summary_sentences': len(record['summary']),
                      'rejected': len(record['rejected']), 'published': False}
        except Exception as exc:
            # Never print raw API exceptions: auth errors can contain key fragments.
            code = getattr(exc, 'code', None)
            body = getattr(exc, 'body', {})
            error = body.get('error', body) if isinstance(body, dict) else {}
            message = error.get('message', '') if isinstance(error, dict) else ''
            if not isinstance(message, str):
                message = ''
            for name, value in os.environ.items():
                if value and ('KEY' in name or 'TOKEN' in name or 'SECRET' in name):
                    message = message.replace(value, '[redacted]')
            message = re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', message)[:500]
            report = {'source_id': paper['source_id'], 'status': 'failed',
                      'error_type': type(exc).__name__, 'message': message,
                      'http_status': getattr(exc, 'status_code', None),
                      'error_code': code if isinstance(code, str) and code.isidentifier() else None,
                      'published': False}
            if hasattr(exc, 'errors'):
                report['validation_errors'] = [{"location": e['loc'], "message": e['msg']}
                    for e in exc.errors(include_input=False, include_url=False)]
            if hasattr(backend, 'last_extraction'):
                write_new_json(output / f'failed-extraction-{index}.json', backend.last_extraction)
            reports.append(report)
            print(json.dumps(report), flush=True)
            write_new_json(output / 'report.json', reports)
            print(f'Report: {output / "report.json"}', flush=True)
            return 1
        reports.append(report)
        print(json.dumps(report), flush=True)
    write_new_json(output / 'report.json', reports)
    print(f'Report: {output / "report.json"}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
