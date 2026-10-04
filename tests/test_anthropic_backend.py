import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paper_pipeline import AnthropicBackend, Extraction, Summary, SummarySentence, provider_settings, make_backend
from paper_security import MAX_MODEL_CALLS, MAX_PAYLOAD_CHARS


class AnthropicTests(unittest.TestCase):
    def backend(self, stop='end_turn', parsed=True):
        requests = []
        def parse(**kwargs):
            requests.append(kwargs)
            return SimpleNamespace(id='msg_fixture', model='claude-test', stop_reason=stop,
                parsed_output=Extraction(entities=[], claims=[]) if parsed else None)
        backend = AnthropicBackend.__new__(AnthropicBackend)
        backend.client = SimpleNamespace(messages=SimpleNamespace(parse=parse))
        backend.model, backend.verifier_model = 'extract-model', 'verify-model'
        backend.calls = []
        return backend, requests

    def test_structured_request_keeps_untrusted_content_out_of_system(self):
        backend, requests = self.backend()
        result = backend.ask(Extraction, 'Extract.', {'text': 'untrusted paper'}, verify=True)
        request = requests[0]
        self.assertEqual(request['model'], 'verify-model')
        self.assertEqual(request['tools'], [])
        self.assertEqual(request['max_tokens'], 8000)
        self.assertIs(request['output_format'], Extraction)
        self.assertNotIn('untrusted paper', request['system'])
        self.assertEqual(json.loads(request['messages'][0]['content']), {'text': 'untrusted paper'})
        self.assertEqual(result.claims, [])
        self.assertEqual(backend.calls[0]['provider'], 'anthropic')
        self.assertNotIn('store', request)  # OpenAI-specific option must not leak across providers.

    def test_refusal_truncation_and_missing_output_fail_closed(self):
        for reason, parsed in [('refusal', True), ('max_tokens', True), ('tool_use', True), ('end_turn', False)]:
            with self.subTest(reason=reason, parsed=parsed):
                backend, _ = self.backend(reason, parsed)
                with self.assertRaises(RuntimeError):
                    backend.extract('paper')

    def test_request_limits_apply_before_network(self):
        backend, requests = self.backend()
        with self.assertRaises(ValueError):
            backend.extract('x' * MAX_PAYLOAD_CHARS)
        backend.calls = [{}] * MAX_MODEL_CALLS
        with self.assertRaises(RuntimeError):
            backend.extract('paper')
        self.assertEqual(requests, [])

    @patch('dotenv.dotenv_values')
    def test_only_selected_provider_settings_are_loaded(self, values):
        values.return_value = {'LLM_PROVIDER': 'anthropic', 'ANTHROPIC_API_KEY': 'fixture-key',
            'ANTHROPIC_MODEL': 'claude-test', 'OPENAI_API_KEY': 'do-not-load',
            'PAPER_REVIEW_SIGNING_KEY': 'do-not-load'}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(provider_settings(), ('anthropic', 'claude-test', 'claude-test'))
            self.assertNotIn('OPENAI_API_KEY', os.environ)
            self.assertNotIn('PAPER_REVIEW_SIGNING_KEY', os.environ)
        self.assertFalse(values.call_args.kwargs['interpolate'])

    @patch('dotenv.dotenv_values')
    def test_missing_anthropic_key_never_falls_back_to_openai(self, values):
        values.return_value = {'LLM_PROVIDER': 'anthropic', 'OPENAI_API_KEY': 'fixture-key',
                               'OPENAI_MODEL': 'other-model'}
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'ANTHROPIC_API_KEY'):
                provider_settings()

    @patch('dotenv.dotenv_values')
    def test_environment_and_explicit_overrides(self, values):
        values.return_value = {'LLM_PROVIDER': 'anthropic', 'OPENAI_MODEL': 'file-model'}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key', 'OPENAI_MODEL': 'env-model'}, clear=True):
            self.assertEqual(provider_settings('openai'), ('openai', 'env-model', 'env-model'))
            self.assertEqual(provider_settings('openai', 'explicit', 'verifier'), ('openai', 'explicit', 'verifier'))

    def test_actual_sdk_serialization_and_parsing_without_network(self):
        import anthropic
        import httpx2
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx2.Response(200, json={
                'id': 'msg_fixture', 'type': 'message', 'role': 'assistant',
                'model': 'claude-test', 'content': [{'type': 'text', 'text': '{"entities":[],"claims":[]}'}],
                'stop_reason': 'end_turn', 'stop_sequence': None,
                'usage': {'input_tokens': 10, 'output_tokens': 10}})
        backend, _ = self.backend()
        backend.client = anthropic.Anthropic(api_key='offline-test-only',
            http_client=httpx2.Client(transport=httpx2.MockTransport(respond)))
        try:
            self.assertEqual(backend.extract('paper').claims, [])
            self.assertEqual(requests[0]['output_config']['format']['type'], 'json_schema')
            self.assertEqual(requests[0]['tools'], [])
        finally:
            backend.client.close()

    def test_summary_citation_aliases_map_only_to_supplied_claims(self):
        backend, _ = self.backend()
        sent = []
        def ask(schema, prompt, payload):
            sent.extend(payload["claims"])
            return Summary(sentences=[
                SummarySentence(text='Supported.', claim_ids=['S1']),
                SummarySentence(text='Unsupported.', claim_ids=['C1']),
                SummarySentence(text='Wrong source.', claim_ids=['S99'])])
        backend.ask = ask
        claim = {'id': 'CLAIM:durable', 'local_id': 'C1', 'statement': 'Finding',
                 'quote': 'Finding', 'polarity': 'affirmed', 'study_context': 'People',
                 'limitations': 'Small study'}
        result = backend.summarize([claim])
        self.assertEqual(sent[0]['id'], 'S1')
        self.assertNotIn('local_id', sent[0])
        self.assertNotIn('limitations', sent[0])
        self.assertNotIn('study_context', sent[0])
        self.assertEqual(result.sentences[0].claim_ids, ['CLAIM:durable'])
        self.assertEqual(result.sentences[1].claim_ids, ['UNRECOGNIZED:C1'])
        self.assertEqual(result.sentences[2].claim_ids, ['UNRECOGNIZED:S99'])

    def test_unknown_provider_is_not_a_network_destination(self):
        with self.assertRaises(ValueError):
            make_backend('https://attacker.example', 'model')


if __name__ == '__main__':
    unittest.main()
