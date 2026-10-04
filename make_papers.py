#!/usr/bin/env python3
"""
Build papers.json for paper_pipeline.py from PubMed IDs.

Usage:  python3 make_papers.py 28377535 27616483 28538134
        python3 make_papers.py 28377535 --out papers.json

Produces the format the pipeline expects:
    Title: ...
    Authors: Last AB; Last CD; ...
    Abstract:
    <one abstract section per line>
Papers without an abstract are skipped with a warning.
Optional env vars: NCBI_API_KEY, NCBI_EMAIL
Deps: pip install requests
"""
import argparse, json, os, sys, time
import xml.etree.ElementTree as ET
import requests

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def fetch_xml(pmids):                     # the only network call (mocked in tests)
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "tool": "rare-disease-atlas"}
    if os.environ.get("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    if os.environ.get("NCBI_EMAIL"):
        params["email"] = os.environ["NCBI_EMAIL"]
    r = requests.get(EFETCH, params=params, timeout=60)
    r.raise_for_status()
    time.sleep(0.4)
    return r.text


def text_of(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def parse(xml_text):
    papers = []
    for art in ET.fromstring(xml_text).iter("PubmedArticle"):
        pmid = text_of(art.find(".//MedlineCitation/PMID"))
        title = text_of(art.find(".//Article/ArticleTitle"))
        authors = []
        for a in art.findall(".//Article/AuthorList/Author"):
            if a.find("CollectiveName") is not None:
                authors.append(text_of(a.find("CollectiveName")))
            else:
                last, ini = text_of(a.find("LastName")), text_of(a.find("Initials"))
                if last:
                    authors.append(f"{last} {ini}".strip())
        lines = []
        for part in art.findall(".//Article/Abstract/AbstractText"):
            body = text_of(part)
            label = part.get("Label")
            if body:
                lines.append(f"{label.upper()}: {body}" if label else body)
        papers.append({"pmid": pmid, "title": title, "authors": authors, "abstract_lines": lines})
    return papers


def to_record(p):
    text = (f"Title: {p['title']}\nAuthors: {'; '.join(p['authors'])}\nAbstract:\n"
            + "\n".join(p["abstract_lines"]))
    return {"source_id": f"PMID:{p['pmid']}", "text": text, "title": p["title"],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/",
            "source_kind": "abstract", "source_tier": 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pmids", nargs="+")
    ap.add_argument("--out", default="papers.json")
    args = ap.parse_args()
    records = []
    for p in parse(fetch_xml([x.replace("PMID:", "").strip() for x in args.pmids])):
        if not p["abstract_lines"]:
            print(f"warning: PMID {p['pmid']} has no abstract in PubMed; skipped", file=sys.stderr)
            continue
        if not p["authors"]:
            print(f"warning: PMID {p['pmid']} has no author list; authorship checks will not run", file=sys.stderr)
        records.append(to_record(p))
        print(f"PMID {p['pmid']}: {len(p['authors'])} authors, {len(p['abstract_lines'])} abstract lines")
    if not records:
        sys.exit("nothing to write")
    json.dump(records, open(args.out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"wrote {args.out} ({len(records)} papers)")


if __name__ == "__main__":
    main()