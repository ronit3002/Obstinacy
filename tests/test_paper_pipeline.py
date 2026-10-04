import unittest
from unittest.mock import patch
from paper_review import sign_review

import networkx as nx
try:
    import schema
except ImportError:
    import test as schema
from paper_graph import add_reviewed_papers, reviewed_summary
from paper_pipeline import (Claim, Entity, Extraction, Summary, SummarySentence,
                            Verification, Vocabulary, chunks, run_pipeline, span)

TEXT = 'Example disease was not associated with GENE-X in mice.'


class FakeBackend:
    model = verifier_model = 'offline-test'

    def __init__(self):
        self.quote = TEXT
        self.verdict = True
        self.bad_citation = False

    def extract(self, text):
        return Extraction(entities=[
            Entity(local_id='d', kind='Disease', mention='Example disease', quote=TEXT),
            Entity(local_id='g', kind='Gene', mention='GENE-X', quote=TEXT)], claims=[
            Claim(local_id='c', statement=TEXT, quote=self.quote, subject='d', object='g',
                  relation='ASSOCIATED_WITH', polarity='negated', status='observation',
                  study_context='mice', limitations='No human evidence')])

    def verify(self, candidate, context):
        return Verification(supported=self.verdict, entities_correct=True,
                            relation_correct=True, polarity_correct=self.verdict,
                            context_preserved=True, reason='fixture check')

    def summarize(self, claims):
        return Summary(sentences=[SummarySentence(text='The study found no link in mice.',
            claim_ids=['invented'] if self.bad_citation else [claims[0]['id']])])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict('os.environ', {'PAPER_REVIEW_SIGNING_KEY': 'test-only-review-key-never-use-live-12345'})
        env.start()
        self.addCleanup(env.stop)

    def bundle(self, backend=None):
        return run_pipeline([{'source_id': 'demo', 'text': TEXT}], backend or FakeBackend())

    def review(self, bundle):
        return sign_review(bundle, {'bundle_sha256': bundle['bundle_sha256'], 'reviewer': 'Test reviewer',
                'approved_claim_ids': [c['id'] for c in bundle['papers'][0]['claims']],
                'approved_summary_indices': {'demo': [0]}})

    def test_fabricated_quote_rejected(self):
        backend = FakeBackend()
        backend.quote = 'GENE-X cures Example disease.'
        result = self.bundle(backend)['papers'][0]
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['summary'], [])
        self.assertIn('not found', result['rejected'][0]['reason'])

    def test_semantic_failure_rejected(self):
        backend = FakeBackend()
        backend.verdict = False
        self.assertEqual(self.bundle(backend)['papers'][0]['claims'], [])

    def test_unknown_summary_citation_rejected(self):
        backend = FakeBackend()
        backend.bad_citation = True
        self.assertEqual(self.bundle(backend)['papers'][0]['summary'], [])

    def test_no_review_no_facts(self):
        bundle = self.bundle()
        review = self.review(bundle)
        review['approved_claim_ids'] = []
        with self.assertRaises(ValueError):
            reviewed_summary(bundle, review, 'demo')
        review['approved_summary_indices'] = {}
        review = sign_review(bundle, review)
        self.assertEqual(len(add_reviewed_papers(nx.MultiDiGraph(), bundle, review)), 0)

    def test_negation_is_not_positive_graph_relation(self):
        bundle = self.bundle()
        graph = add_reviewed_papers(nx.MultiDiGraph(), bundle, self.review(bundle))
        self.assertFalse(any(e['rel'] == 'ASSOCIATED_WITH' for *_, e in graph.edges(data=True)))
        self.assertEqual(schema.schema_violations(graph), [])
        self.assertEqual(schema.unsupported_inferences(graph), [])
        self.assertEqual(schema.unverified_claims(graph, {'demo': TEXT}), [])
        self.assertEqual(len(reviewed_summary(bundle, self.review(bundle), 'demo')), 1)
        again = add_reviewed_papers(graph, bundle, self.review(bundle))
        self.assertEqual(again.number_of_edges(), graph.number_of_edges())

    def test_affirmed_observation_imports_with_provenance(self):
        class Positive(FakeBackend):
            def extract(self, text):
                extraction = super().extract(text)
                extraction.claims[0].polarity = 'affirmed'
                return extraction
        # Fake verifier is deliberately not a factual evaluator; this exercises
        # the importer contract with a mechanically approved test candidate.
        bundle = self.bundle(Positive())
        graph = add_reviewed_papers(nx.MultiDiGraph(), bundle, self.review(bundle))
        edges = [e for *_, e in graph.edges(data=True) if e['rel'] == 'ASSOCIATED_WITH']
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]['source'], 'demo')
        self.assertTrue(edges[0]['supported_by'])

    def test_hypothesis_does_not_enter_positive_projection(self):
        class Hypothesis(FakeBackend):
            def extract(self, text):
                extraction = super().extract(text)
                extraction.claims[0].polarity = 'affirmed'
                extraction.claims[0].status = 'hypothesis'
                return extraction
        bundle = self.bundle(Hypothesis())
        graph = add_reviewed_papers(nx.MultiDiGraph(), bundle, self.review(bundle))
        self.assertFalse(any(e['rel'] == 'ASSOCIATED_WITH' for *_, e in graph.edges(data=True)))

    def test_tampering_invalidates_review(self):
        bundle = self.bundle()
        review = self.review(bundle)
        bundle['papers'][0]['claims'][0]['polarity'] = 'affirmed'
        with self.assertRaises(ValueError):
            add_reviewed_papers(nx.MultiDiGraph(), bundle, review)

    def test_source_ids_must_be_unique(self):
        with self.assertRaises(ValueError):
            run_pipeline([{'source_id': 'a', 'text': TEXT}] * 2, FakeBackend())

    def test_exact_resolution_preserves_ambiguity(self):
        vocab = Vocabulary()
        vocab.add('Disease', 'MONDO:1', 'Example disease', ['Alias'])
        self.assertEqual(vocab.resolve('Disease', 'alias')['canonical_id'], 'MONDO:1')
        vocab.add('Disease', 'MONDO:2', 'Other disease', ['Alias'])
        self.assertEqual(vocab.resolve('Disease', 'Alias')['status'], 'ambiguous')
        self.assertIsNone(vocab.resolve('Disease', 'Alias')['canonical_id'])
        self.assertEqual(vocab.resolve('Disease', 'Almost Alias')['status'], 'unresolved')

    def test_offsets_and_chunk_coverage(self):
        text = '0123456789' * 50
        covered = set()
        for offset, chunk in chunks(text, 50, 10):
            self.assertEqual(chunk, text[offset:offset + len(chunk)])
            covered.update(range(offset, offset + len(chunk)))
        self.assertEqual(len(covered), len(text))
        self.assertEqual(span('abc def', 'def', 10), {'quote': 'def', 'start': 14, 'end': 17})
        for quote in ('', 'abc'):
            with self.assertRaises(ValueError):
                span('abc abc', quote)

    def test_model_failure_does_not_return_partial_results(self):
        class Broken(FakeBackend):
            def verify(self, candidate, context):
                raise RuntimeError('refused')
        with self.assertRaises(RuntimeError):
            self.bundle(Broken())

    def test_multiple_papers_keep_separate_sources(self):
        bundle = run_pipeline([{'source_id': x, 'text': TEXT} for x in ['a', 'b']], FakeBackend())
        a, b = bundle['papers']
        self.assertNotEqual(a['claims'][0]['id'], b['claims'][0]['id'])


if __name__ == '__main__':
    unittest.main()
