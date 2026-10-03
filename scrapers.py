"""
Unified Scrapers Module for Global AI Hackathon (Track 5: Atlas Graph).
Provides a single interface to query both:
  1. RARe-SOURCE (NIH NCATS): Disease IDs, Aliases, Genes, and PubMed literature.
  2. RareConnect (EURORDIS): Patient communities, member counts, and discussions.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Optional

from nord_scraper import NORDScraper
from rareconnect_scraper import RareConnectScraper
from raresource_scraper import RAReSourceScraper


def get_disease_knowledge_bundle(
    disease_name: str,
    include_posts: bool = True,
    posts_limit: int = 5,
    include_nord_orgs: bool = True,
) -> Dict[str, Any]:
    """Retrieves an aggregated knowledge bundle combining clinical/genomic data
    from RARe-SOURCE, patient community data from RareConnect, and patient organization
    contact profiles (name, address, website, phone, email, description) from NORD.

    Args:
        disease_name: Disease name or alias (e.g. 'Dravet syndrome', 'Cystic fibrosis').
        include_posts: Whether to include sample patient discussions from RareConnect.
        posts_limit: Maximum number of community posts to include.
        include_nord_orgs: Whether to include NORD patient organizations with full contact details.

    Returns:
        Structured dictionary ready for graph ingestion or API consumers:
          - disease: { canonical_name, gard_id, synonyms, database_ids }
          - genes: [ { gene_symbol, hgnc_id, uniprot_id, description } ]
          - literature: [ { pmid, title, authors, journal, year } ]
          - patient_community: { name, slug, url, members, posts_count, discussions }
          - patient_organizations: [ { name, adresse, website, nummer, email, description } ]
    """
    ra_client = RAReSourceScraper()
    rc_client = RareConnectScraper()
    nord_client = NORDScraper()


    # 1. Fetch clinical / genomic data from RARe-SOURCE
    ra_data = ra_client.get_disease_details(disease_name)

    # 2. Search for matching patient community on RareConnect
    # Try searching with primary disease name first, then original input query
    search_queries = [disease_name]
    if ra_data.get("disease_name") and ra_data["disease_name"] not in search_queries:
        search_queries.insert(0, ra_data["disease_name"])

    matched_community: Optional[Dict[str, Any]] = None
    for q in search_queries:
        comms = rc_client.search_communities(q, limit=1)
        if comms:
            matched_community = comms[0]
            break

    # If still not found, check synonyms
    if not matched_community and ra_data.get("synonyms"):
        for syn in ra_data["synonyms"][:5]:
            comms = rc_client.search_communities(syn, limit=1)
            if comms:
                matched_community = comms[0]
                break

    community_bundle = None
    if matched_community:
        stream_id = matched_community.get("stream_id")
        posts = []
        if include_posts and stream_id:
            posts = rc_client.get_community_posts(stream_id, limit=posts_limit)

        community_bundle = {
            "name": matched_community["name"],
            "slug": matched_community["slug"],
            "url": matched_community["url"],
            "total_members": matched_community["total_members"],
            "total_posts": matched_community["total_posts"],
            "description": matched_community["description"],
            "stream_id": stream_id,
            "sample_posts": posts,
        }

    # 3. Fetch patient organizations from NORD (with contact details)
    nord_orgs = []
    if include_nord_orgs:
        try:
            lookup_name = ra_data.get("disease_name") or disease_name
            nord_orgs = nord_client.get_organizations_for_disease(
                lookup_name,
                enrich_profiles=True,
            )
        except Exception as e:
            pass

    return {
        "query": disease_name,
        "disease": {
            "canonical_name": ra_data.get("disease_name") or disease_name,
            "gard_id": ra_data.get("gard_id"),
            "database_ids": ra_data.get("database_ids", {}),
            "synonyms": ra_data.get("synonyms", []),
        },
        "genes": ra_data.get("genes", []),
        "literature": ra_data.get("literature", []),
        "patient_community": community_bundle,
        "patient_organizations": nord_orgs,
    }



def to_atlas_graph_nodes_and_edges(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Converts a knowledge bundle into nodes and edges matching the Atlas Graph schema."""
    nodes = []
    edges = []

    disease = bundle.get("disease", {})
    disease_id = f"Disease:{disease.get('gard_id') or disease.get('canonical_name')}"
    nodes.append(
        {
            "id": disease_id,
            "type": "Disease",
            "name": disease.get("canonical_name"),
            "gard_id": disease.get("gard_id"),
            "synonyms": disease.get("synonyms", []),
            "omim": disease.get("database_ids", {}).get("omim"),
            "orphanet": disease.get("database_ids", {}).get("orphanet"),
            "umls": disease.get("database_ids", {}).get("umls"),
        }
    )

    # Associated Genes
    for g in bundle.get("genes", []):
        gene_id = f"Gene:{g.get('gene_symbol')}"
        nodes.append(
            {
                "id": gene_id,
                "type": "Gene",
                "symbol": g.get("gene_symbol"),
                "hgnc_id": g.get("hgnc_gene_id"),
                "uniprot_id": g.get("uniprot_id"),
                "description": g.get("gene_description"),
            }
        )
        edges.append(
            {
                "src": disease_id,
                "dst": gene_id,
                "rel": "ASSOCIATED_WITH",
                "source": "RARe-SOURCE",
                "source_tier": 1,
                "retrieved": "2026-10-03",
                "method": "curated_import",
                "status": "observation",
            }
        )

    # Literature / Papers and Claims
    for p in bundle.get("literature", []):
        pmid = p.get("pmid")
        if not pmid:
            continue
        paper_id = f"PMID:{pmid}"
        claim_id = f"CLAIM:{pmid}:1"
        title_quote = p.get("title") or f"Literature citation for {disease.get('canonical_name')}"

        nodes.append(
            {
                "id": paper_id,
                "type": "Paper",
                "pmid": pmid,
                "title": p.get("title"),
                "authors": p.get("authors"),
                "journal": p.get("journal"),
                "year": p.get("year"),
            }
        )
        nodes.append(
            {
                "id": claim_id,
                "type": "Claim",
                "quote": title_quote,
                "pmid": paper_id,
                "status": "observation",
                "confidence": 1.0,
                "model": "TOTEM/NCATS",
                "prompt_version": "v1",
            }
        )
        edges.append(
            {
                "src": paper_id,
                "dst": claim_id,
                "rel": "CONTAINS",
                "source": paper_id,
                "source_tier": 2,
                "retrieved": "2026-10-03",
                "method": "curated_import",
                "status": "observation",
            }
        )
        edges.append(
            {
                "src": claim_id,
                "dst": disease_id,
                "rel": "ABOUT",
                "source": paper_id,
                "source_tier": 2,
                "retrieved": "2026-10-03",
                "method": "curated_import",
                "status": "observation",
            }
        )

    # Patient Organization / Community (RareConnect)
    comm = bundle.get("patient_community")
    if comm:
        org_id = f"PatientOrg:{comm.get('slug')}"
        nodes.append(
            {
                "id": org_id,
                "type": "PatientOrg",
                "name": comm.get("name"),
                "slug": comm.get("slug"),
                "url": comm.get("url"),
                "total_members": comm.get("total_members"),
                "total_posts": comm.get("total_posts"),
            }
        )
        edges.append(
            {
                "src": disease_id,
                "dst": org_id,
                "rel": "REPRESENTED_BY",
                "source": "RareConnect",
                "source_tier": 3,
                "retrieved": "2026-10-03",
                "method": "curated_import",
                "status": "observation",
            }
        )

    # Patient Organizations (NORD with full contact info)
    import re
    for org in bundle.get("patient_organizations", []):
        name_slug = re.sub(r"[^a-zA-Z0-9]+", "-", org["name"].lower()).strip("-")
        org_id = f"PatientOrg:nord:{name_slug}"
        nodes.append(
            {
                "id": org_id,
                "type": "PatientOrg",
                "name": org["name"],
                "url": org.get("website") or org.get("nord_url"),
                "address": org.get("adresse", ""),
                "phone": org.get("nummer", ""),
                "email": org.get("email", ""),
                "description": org.get("description", ""),
            }
        )
        edges.append(
            {
                "src": disease_id,
                "dst": org_id,
                "rel": "REPRESENTED_BY",
                "source": "NORD",
                "source_tier": 3,
                "retrieved": "2026-10-04",
                "method": "curated_import",
                "status": "observation",
            }
        )

    return {"nodes": nodes, "edges": edges}



def main() -> None:
    parser = argparse.ArgumentParser(description="Query unified rare disease knowledge bundle")
    parser.add_argument("disease", help="Name or alias of disease (e.g. 'Dravet syndrome')")
    parser.add_argument("--limit-posts", type=int, default=3, help="Max posts to retrieve from RareConnect")
    parser.add_argument("--graph", action="store_true", help="Output in Atlas Graph nodes/edges format")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()
    bundle = get_disease_knowledge_bundle(args.disease, posts_limit=args.limit_posts)

    if args.graph:
        graph_data = to_atlas_graph_nodes_and_edges(bundle)
        print(json.dumps(graph_data, indent=2))
        return

    if args.json:
        print(json.dumps(bundle, indent=2))
        return

    d = bundle["disease"]
    print(f"\n==================================================")
    print(f"  Disease Knowledge Bundle: {d['canonical_name']}")
    print(f"==================================================")
    print(f"GARD ID: {d['gard_id']}")
    print(f"Cross-References: {d['database_ids']}")
    print(f"Synonyms count: {len(d['synonyms'])}")

    print(f"\nAssociated Genes ({len(bundle['genes'])}):")
    for g in bundle["genes"]:
        print(f"  - {g['gene_symbol']}: {g['gene_description']}")

    print(f"\nLiterature Citations ({len(bundle['literature'])}):")
    for p in bundle["literature"]:
        print(f"  - PMID {p['pmid']} ({p['year']}): {p['title']}")

    comm = bundle["patient_community"]
    if comm:
        print(f"\nRareConnect Patient Community:")
        print(f"  - Name: {comm['name']}")
        print(f"  - URL: {comm['url']}")
        print(f"  - Members: {comm['total_members']} | Posts: {comm['total_posts']}")
        print(f"  - Sample Discussions ({len(comm.get('sample_posts', []))}):")
        for post in comm.get("sample_posts", []):
            print(f"      * {post['title']}")
    else:
        print(f"\nNo direct RareConnect patient community found.")


if __name__ == "__main__":
    main()
