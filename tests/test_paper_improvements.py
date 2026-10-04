import unittest
import networkx as nx
from paper_graph import add_reviewed_papers
from paper_review import sign_review
from unittest.mock import patch

from paper_pipeline import (AnchoredClaim, AnchoredEntity, AnchoredExtraction, AnthropicBackend,
    BatchVerification, ClaimCheck, SummaryAudit, Vocabulary, materialize_extraction,
    source_passages, run_pipeline, validate_bundle, Extraction, include_metadata_authors)
try:
    from test_paper_pipeline import FakeBackend, TEXT
except ModuleNotFoundError:
    from tests.test_paper_pipeline import FakeBackend, TEXT


class ImprovementsTests(unittest.TestCase):
    def test_passage_selection_preserves_variant_punctuation_and_offsets(self):
        text = 'Title: Study\nThe GRIN2D mutation (c.1999G>A [p.Val667Ile]) was studied.'
        passages = source_passages(text)
        response = AnchoredExtraction(entities=[
            AnchoredEntity(local_id='v', kind='Variant', mention='c.1999G>A', evidence_id='P2'),
            AnchoredEntity(local_id='g', kind='Gene', mention='GRIN2D', evidence_id='P2')], claims=[
            AnchoredClaim(local_id='c', statement='The variant occurs in GRIN2D.', evidence_id='P2',
                subject='v', object='g', relation='IN_GENE', polarity='affirmed', status='observation',
                study_context='Study', limitations='No comparison group', category='finding')])
        result = materialize_extraction(response, passages)
        self.assertEqual(result.claims[0].quote, text.split('\n')[1])
        self.assertIn('[p.Val667Ile]', result.claims[0].quote)
        self.assertNotIn('No comparison group', result.claims[0].limitations)
        response.claims[0].evidence_id = 'P999'
        with self.assertRaises(ValueError):
            materialize_extraction(response, passages)

    def test_explicit_author_metadata_is_preserved_without_inventing_authors(self):
        extraction = Extraction(entities=[], claims=[])
        text = 'Title: Paper\nAuthors: Jane Doe; Alex Smith\nAbstract:\nStudy findings.'
        result = include_metadata_authors(extraction, text)
        self.assertEqual([e.mention for e in result.entities], ['Jane Doe', 'Alex Smith'])
        self.assertTrue(all(c.relation == 'AUTHORED' and c.category == 'authorship' for c in result.claims))
        self.assertEqual(include_metadata_authors(result, text), result)
        self.assertEqual(include_metadata_authors(extraction, 'Authors: Jane Doe'), extraction)

    def test_metadata_author_verification_cannot_accept_extra_claim(self):
        backend = AnthropicBackend.__new__(AnthropicBackend)
        text = 'Title: Paper\nAuthors: Jane Doe\nAbstract:\nStudy findings.'
        extracted = include_metadata_authors(Extraction(entities=[], claims=[]), text)
        candidate = extracted.claims[0].model_dump()
        candidate['entities'] = {extracted.entities[0].local_id: extracted.entities[0].model_dump()}
        backend._verify_many_model = lambda candidates, context: [] if not candidates else (_ for _ in ()).throw(RuntimeError('Needs semantic verification'))
        self.assertTrue(backend.verify_many([candidate], text)[0].passes())
        candidate['statement'] += ' This treatment is safe for everyone.'
        with self.assertRaises(RuntimeError):
            backend.verify_many([candidate], text)

    def test_study_result_entities_import_as_supported_claim_links(self):
        class Backend(FakeBackend):
            def extract(self, text):
                data = super().extract(text)
                data.entities[0].kind = 'Intervention'
                data.entities[1].kind = 'Outcome'
                data.claims[0].relation = 'ABOUT'
                data.claims[0].category = 'result'
                return data
        bundle = run_pipeline([{'source_id': 'demo', 'text': TEXT}], Backend())
        review = {'bundle_sha256': bundle['bundle_sha256'], 'reviewer': 'Fixture',
            'approved_claim_ids': [bundle['papers'][0]['claims'][0]['id']], 'approved_summary_indices': {}}
        with patch.dict('os.environ', {'PAPER_REVIEW_SIGNING_KEY': 'offline-key-only-not-production-123456'}):
            graph = add_reviewed_papers(nx.MultiDiGraph(), bundle, sign_review(bundle, review))
        self.assertIn('Intervention', {d['type'] for _, d in graph.nodes(data=True)})
        self.assertIn('Outcome', {d['type'] for _, d in graph.nodes(data=True)})
        self.assertTrue(all(e['rel'] in {'CONTAINS', 'ABOUT'} for *_, e in graph.edges(data=True)))

    def test_batch_verifier_requires_exact_candidate_set(self):
        backend = AnthropicBackend.__new__(AnthropicBackend)
        good = dict(supported=True, entities_correct=True, relation_correct=True,
                    polarity_correct=True, context_preserved=True, reason='Test')
        backend.ask = lambda *args, **kwargs: BatchVerification(checks=[ClaimCheck(candidate_id='V9', **good)])
        with self.assertRaises(ValueError):
            backend.verify_many([{'statement': 'test'}], 'source')
        backend.ask = lambda *args, **kwargs: BatchVerification(checks=[ClaimCheck(candidate_id='V0', **good)] * 2)
        with self.assertRaises(ValueError):
            backend.verify_many([{'statement': 'test'}], 'source')

    def test_failed_whole_summary_is_not_partially_published(self):
        class Backend(FakeBackend):
            attempts = 0
            def summarize(self, claims, feedback=''):
                self.attempts += 1
                return super().summarize(claims)
            def audit_summary(self, sentences, claims, source):
                return SummaryAudit(supported=True, coherent=False, main_findings_covered=False,
                                    limitations_preserved=True, reason='Dangling reference; main findings missing')
        backend = Backend()
        result = run_pipeline([{'source_id': 'demo', 'text': TEXT}], backend)
        self.assertEqual(result['papers'][0]['summary'], [])
        self.assertEqual(backend.attempts, 2)
        self.assertFalse(result['papers'][0]['summary_audit']['coherent'])
        validate_bundle(result)

    def test_whole_summary_repair_is_reaudited(self):
        class Backend(FakeBackend):
            calls = 0
            def summarize(self, claims, feedback=''):
                return super().summarize(claims)
            def audit_summary(self, sentences, claims, source):
                self.calls += 1
                return SummaryAudit(supported=True, coherent=self.calls > 1, main_findings_covered=True,
                                    limitations_preserved=True, reason='Fixture audit')
        backend = Backend()
        result = run_pipeline([{'source_id': 'demo', 'text': TEXT}], backend)
        self.assertEqual(len(result['papers'][0]['summary']), 1)
        self.assertEqual(backend.calls, 2)
        validate_bundle(result)

    def test_similar_name_suggestions_do_not_merge_identity(self):
        vocab = Vocabulary()
        vocab.add('Disease', 'MONDO:1', 'GRIN2B related encephalopathy')
        match = vocab.resolve('Disease', 'GRIN2B encephalopathy')
        self.assertIsNone(match['canonical_id'])
        self.assertEqual(match['status'], 'unresolved')
        self.assertTrue(match['candidates'][0]['suggestion_only'])


if __name__ == '__main__':
    unittest.main()
