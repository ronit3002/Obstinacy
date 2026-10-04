"""Fetch a fixed small PubMed test corpus. No credentials or model calls."""
import json
from pathlib import Path
from urllib.request import urlopen
import xml.etree.ElementTree as ET

PMIDS = ['28377535', '27616483', '28538134']
url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id=' + ','.join(PMIDS)
with urlopen(url, timeout=30) as response:
    xml = response.read(2_000_000)
root = ET.fromstring(xml)
papers = []
for record in root.findall('PubmedArticle'):
    citation = record.find('MedlineCitation')
    pmid = citation.findtext('PMID')
    article = citation.find('Article')
    title = ''.join(article.find('ArticleTitle').itertext())
    authors = []
    for author in article.findall('AuthorList/Author'):
        name = author.findtext('CollectiveName') or ' '.join(filter(None, [author.findtext('ForeName'), author.findtext('LastName')]))
        if name:
            authors.append(name)
    paragraphs = []
    for section in article.findall('Abstract/AbstractText'):
        text = ''.join(section.itertext())
        paragraphs.append((section.get('Label', '') + ': ' if section.get('Label') else '') + text)
    if not paragraphs:
        raise ValueError('Abstract missing')
    papers.append({'source_id': 'PMID:' + pmid, 'title': title,
                   'url': 'https://pubmed.ncbi.nlm.nih.gov/' + pmid + '/',
                   'source_kind': 'abstract', 'source_tier': 2,
                   'text': 'Title: ' + title + '\nAuthors: ' + '; '.join(authors) + '\nAbstract:\n' + '\n'.join(paragraphs)})
if {p['source_id'].split(':')[1] for p in papers} != set(PMIDS):
    raise ValueError('Incomplete corpus')
path = Path(__file__).resolve().parents[1] / 'data/raw/live-test-pubmed'
path.mkdir(parents=True, exist_ok=True)
(path / 'pubmed.xml').write_bytes(xml)
(path / 'papers.json').write_text(json.dumps(papers, indent=2))
print('Saved', len(papers), 'PubMed abstracts to', path / 'papers.json')
