"""
RARe-SOURCE (NIH NCATS) Scraper & API Client
Scrapes and queries rare disease records, aliases, cross-database IDs (GARD, OMIM, Orphanet, UMLS, MeSH),
associated genes, and PubMed literature references.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("raresource_scraper")


class RAReSourceScraper:
    """Client for querying the NIH NCATS RARe-SOURCE knowledgebase.

    Supports:
      - Live querying of the official RARe-SOURCE API (with automatic CSRF & session handling).
      - Fast offline search using cached/parsed disease table from HAR file or local cache.
      - Full disease entity retrieval: GARD ID, OMIM, Orphanet, UMLS, causative genes,
        PubMed publications, and all synonyms/aliases.
    """

    BASE_URL = "https://raresource.nih.gov"
    DISEASES_URL = f"{BASE_URL}/diseases/"
    DISEASE_INFO_URL = f"{BASE_URL}/diseases/disease_info/"
    DEFAULT_HAR_PATH = Path(__file__).resolve().parent / "raresource_search_aliases.har"
    CACHE_FILE = Path(__file__).resolve().parent / "raresource_catalog.json"

    def __init__(
        self,
        har_path: Optional[str | Path] = None,
        cache_file: Optional[str | Path] = None,
        timeout: int = 15,
    ) -> None:
        self.har_path = Path(har_path) if har_path else self.DEFAULT_HAR_PATH
        self.cache_file = Path(cache_file) if cache_file else self.CACHE_FILE
        self.timeout = timeout
        self._session: Optional[requests.Session] = None
        self._csrf_token: Optional[str] = None
        self._catalog: Optional[List[Dict[str, Any]]] = None

    def _get_session(self) -> requests.Session:
        """Initializes an HTTP session and fetches CSRF token if needed."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Referer": self.DISEASES_URL,
                }
            )
            try:
                resp = self._session.get(self.DISEASES_URL, timeout=self.timeout)
                resp.raise_for_status()
                self._csrf_token = self._session.cookies.get("csrftoken")
            except Exception as e:
                logger.warning("Could not establish live session with RARe-SOURCE: %s", e)
        return self._session

    def load_catalog(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Loads all ~7,200 rare disease entries from cache, HAR file, or live web page."""
        if self._catalog and not force_refresh:
            return self._catalog

        # 1. Try local JSON cache
        if not force_refresh and self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self._catalog = json.load(f)
                    logger.debug("Loaded %d diseases from cache %s", len(self._catalog), self.cache_file)
                    return self._catalog
            except Exception as e:
                logger.warning("Failed reading cache %s: %s", self.cache_file, e)

        # 2. Try parsing from HAR file if available
        if self.har_path.exists():
            try:
                self._catalog = self._parse_catalog_from_har(self.har_path)
                self._save_catalog_cache(self._catalog)
                return self._catalog
            except Exception as e:
                logger.warning("Failed parsing catalog from HAR %s: %s", self.har_path, e)

        # 3. Fallback: scrape live page HTML
        try:
            session = self._get_session()
            resp = session.get(self.DISEASES_URL, timeout=self.timeout)
            resp.raise_for_status()
            self._catalog = self._parse_catalog_from_html(resp.text)
            self._save_catalog_cache(self._catalog)
            return self._catalog
        except Exception as e:
            logger.error("Failed fetching live catalog: %s", e)
            if self._catalog:
                return self._catalog
            raise RuntimeError(f"Unable to load disease catalog from cache, HAR, or live web: {e}") from e

    def _save_catalog_cache(self, catalog: List[Dict[str, Any]]) -> None:
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2, ensure_ascii=False)
            logger.info("Saved %d disease records to %s", len(catalog), self.cache_file)
        except Exception as e:
            logger.warning("Could not write cache file %s: %s", self.cache_file, e)

    def _parse_catalog_from_har(self, har_path: Path) -> List[Dict[str, Any]]:
        with open(har_path, "r", encoding="utf-8", errors="ignore") as f:
            har_data = json.load(f)

        for entry in har_data.get("log", {}).get("entries", []):
            url = entry.get("request", {}).get("url", "")
            if "raresource.nih.gov/diseases" in url and entry.get("request", {}).get("method") == "GET":
                text = entry.get("response", {}).get("content", {}).get("text", "")
                if "<table id='summary-table'" in text or 'id="summary-table"' in text or "GRACILE syndrome" in text:
                    return self._parse_catalog_from_html(text)

        raise ValueError(f"No summary-table found in HAR file: {har_path}")

    def _parse_catalog_from_html(self, html_text: str) -> List[Dict[str, Any]]:
        rows = re.findall(r"<tr>(.*?)</tr>", html_text, re.DOTALL)
        if not rows:
            return []

        catalog: List[Dict[str, Any]] = []
        for row in rows[1:]:  # skip the <th> header row
            cells = [
                re.sub(r"<[^>]+>", "", c).strip()
                for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            ]
            if len(cells) < 17:
                continue

            disease_name = cells[1]
            aliases_raw = cells[2]
            aliases = [a.strip() for a in aliases_raw.split("//") if a.strip()]
            genes = [g.strip() for g in cells[3].split("//") if g.strip()]
            gard_id = cells[6].strip()
            omim = cells[7].strip()
            orphanet = cells[8].strip()
            umls = cells[9].strip()
            mesh = cells[10].strip()
            icd10cm = cells[11].strip()
            gene_desc = cells[12].strip()
            annotation_url = cells[5].strip()
            pmid_count = int(cells[16]) if cells[16].isdigit() else 0

            catalog.append(
                {
                    "name": disease_name,
                    "gard_id": gard_id,
                    "aliases": aliases,
                    "genes": genes,
                    "gene_description": gene_desc,
                    "omim": omim,
                    "orphanet": orphanet,
                    "umls": umls,
                    "mesh": mesh,
                    "icd10cm": icd10cm,
                    "annotation_url": annotation_url,
                    "pmid_count": pmid_count,
                }
            )

        return catalog

    def search(
        self,
        query: str,
        search_aliases: bool = True,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Searches the disease catalog for matches against name or aliases.

        Args:
            query: Substring or keyword to search for (case-insensitive).
            search_aliases: Whether to search through aliases/synonyms in addition to primary names.
            limit: Maximum number of records to return.

        Returns:
            List of matching disease catalog dictionaries.
        """
        catalog = self.load_catalog()
        q = query.strip().lower()
        if not q:
            return catalog[:limit]

        matches: List[Dict[str, Any]] = []
        exact_matches: List[Dict[str, Any]] = []

        for item in catalog:
            name_lower = item["name"].lower()
            aliases_lower = [a.lower() for a in item["aliases"]] if search_aliases else []

            # Check exact match first
            if name_lower == q or q in aliases_lower:
                exact_matches.append(item)
            elif q in name_lower or any(q in a for a in aliases_lower):
                matches.append(item)

        results = exact_matches + matches
        return results[:limit]

    def get_disease_details(self, disease_name: str) -> Dict[str, Any]:
        """Fetches detailed entity information for a disease via the RARe-SOURCE API.

        Queries `POST /diseases/disease_info/` to get:
          - GARD ID
          - Associated genes (with HGNC, Ensembl, UniProt IDs)
          - Database IDs (GARD, OMIM, Orphanet, UMLS)
          - Full list of synonyms/aliases
          - TOTEM PubMed literature articles (PMIDs, titles, authors, journals)

        If the direct query fails (e.g. due to case sensitivity or because the input
        is an alias rather than the primary disease name), it automatically resolves
        the input against the 7,200-disease catalog and retries with the canonical primary name.

        Args:
            disease_name: The name or alias of the disease.

        Returns:
            Dictionary with parsed fields:
              gard_id, disease_name, synonyms, genes, database_ids, literature, error.
        """
        session = self._get_session()
        csrf = self._csrf_token or session.cookies.get("csrftoken") or ""

        def _do_post(name: str) -> Dict[str, Any]:
            resp = session.post(
                self.DISEASE_INFO_URL,
                data={"disease_name": name},
                headers={
                    "X-CSRFToken": csrf,
                    "Referer": self.DISEASES_URL,
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()

        # Resolve to canonical primary name from catalog if available
        primary_name = disease_name
        catalog_matches = self.search(disease_name, search_aliases=True, limit=1)
        if catalog_matches:
            primary_name = catalog_matches[0]["name"]

        # Attempt 1: Query with the canonical primary name
        raw = _do_post(primary_name)

        # If not found or empty, retry with the verbatim user-provided name
        if not raw.get("gardId") and primary_name.lower() != disease_name.lower():
            raw = _do_post(disease_name)


        # Normalize and structure the response
        totem_raw = raw.get("totem")
        literature = []
        if isinstance(totem_raw, list):
            for article in totem_raw:
                literature.append(
                    {
                        "pmid": str(article.get("pmid") or "").strip(),
                        "title": article.get("articleTitle", "").strip(),
                        "authors": article.get("authors", "").strip(),
                        "journal": article.get("journalTitle", "").strip(),
                        "year": str(article.get("publicationYear") or "").strip(),
                        "volume": article.get("volume"),
                        "source": article.get("source", "nlm"),
                    }
                )

        genes = []
        for g in raw.get("geneInfo") or []:
            genes.append(
                {
                    "gene_symbol": g.get("gene_symbol"),
                    "gene_id": g.get("gene_id"),
                    "ensembl_gene_id": g.get("ensembl_gene_id"),
                    "hgnc_gene_id": g.get("hgnc_gene_id"),
                    "uniprot_id": g.get("uniprot_id"),
                    "gene_description": g.get("gene_description"),
                }
            )

        disease_ids = {}
        raw_ids_list = raw.get("diseaseIds") or []
        if raw_ids_list and isinstance(raw_ids_list, list):
            first_id_dict = raw_ids_list[0]
            disease_ids = {
                "gard": first_id_dict.get("gard", ""),
                "omim": first_id_dict.get("omim", ""),
                "orphanet": first_id_dict.get("orphanet", ""),
                "umls": first_id_dict.get("umls", ""),
            }

        synonyms = raw.get("diseaseSynonyms") or []

        return {
            "disease_name": disease_name,
            "gard_id": raw.get("gardId"),
            "database_ids": disease_ids,
            "synonyms": synonyms,
            "genes": genes,
            "literature": literature,
            "is_found": bool(raw.get("gardId")),
            "error": raw.get("error", False),
        }

    def get_disease_by_gard_id(self, gard_id: str) -> Optional[Dict[str, Any]]:
        """Finds a disease in the catalog by GARD ID, then fetches its full details."""
        clean_id = gard_id.strip().lstrip("0")
        catalog = self.load_catalog()
        for item in catalog:
            item_gard = item["gard_id"].strip().lstrip("0")
            if item_gard == clean_id:
                details = self.get_disease_details(item["name"])
                details["catalog_entry"] = item
                return details
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="RARe-SOURCE (NIH NCATS) Scraper & Query Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Search command
    search_parser = subparsers.add_parser("search", help="Search rare diseases and aliases in catalog")
    search_parser.add_argument("query", help="Keyword or disease name to search")
    search_parser.add_argument("--limit", type=int, default=10, help="Max results to display")
    search_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    # Details command
    details_parser = subparsers.add_parser("details", help="Fetch detailed genes, IDs, and papers for a disease")
    details_parser.add_argument("disease", help="Exact name or alias of the disease")
    details_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    # Catalog command
    cat_parser = subparsers.add_parser("catalog", help="Inspect or export full disease catalog")
    cat_parser.add_argument("--limit", type=int, default=10, help="Number of records to show")
    cat_parser.add_argument("--export", type=str, help="Export entire catalog to a JSON file")

    args = parser.parse_args()
    scraper = RAReSourceScraper()

    if args.command == "search":
        results = scraper.search(args.query, limit=args.limit)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"\nFound {len(results)} matches for '{args.query}':\n")
            for i, r in enumerate(results, 1):
                aliases_preview = ", ".join(r["aliases"][:3])
                if len(r["aliases"]) > 3:
                    aliases_preview += f" (+{len(r['aliases'])-3} more)"
                genes_preview = ", ".join(r["genes"]) if r["genes"] else "None listed"
                print(f"[{i}] {r['name']} (GARD: {r['gard_id']})")
                print(f"    Genes: {genes_preview}")
                print(f"    OMIM: {r['omim'] or 'N/A'} | Orphanet: {r['orphanet'] or 'N/A'} | UMLS: {r['umls'] or 'N/A'}")
                print(f"    Aliases: {aliases_preview or 'None'}\n")

    elif args.command == "details":
        details = scraper.get_disease_details(args.disease)
        if args.json:
            print(json.dumps(details, indent=2))
        else:
            if not details.get("is_found"):
                print(f"Disease '{args.disease}' not found in RARe-SOURCE.")
                return

            print(f"\n=== RARe-SOURCE Details: {details['disease_name']} ===")
            print(f"GARD ID: {details['gard_id']}")
            print("Database Cross-References:")
            for db, db_id in details["database_ids"].items():
                print(f"  - {db.upper()}: {db_id or 'N/A'}")

            print(f"\nAssociated Genes ({len(details['genes'])}):")
            for g in details["genes"]:
                print(f"  - {g['gene_symbol']} (HGNC: {g['hgnc_gene_id']}, UniProt: {g['uniprot_id']}): {g['gene_description']}")

            print(f"\nSynonyms / Aliases ({len(details['synonyms'])}):")
            for s in details["synonyms"][:8]:
                print(f"  - {s}")
            if len(details["synonyms"]) > 8:
                print(f"  ... (+{len(details['synonyms'])-8} more)")

            print(f"\nLiterature / TOTEM PubMed Articles ({len(details['literature'])}):")
            for pub in details["literature"]:
                print(f"  - PMID {pub['pmid']} ({pub['year']}): {pub['title']}")
                print(f"    Authors: {pub['authors']} | Journal: {pub['journal']}")

    elif args.command == "catalog":
        catalog = scraper.load_catalog()
        print(f"Catalog loaded: {len(catalog)} total diseases.")
        if args.export:
            with open(args.export, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2)
            print(f"Successfully exported {len(catalog)} records to {args.export}")
        else:
            for item in catalog[: args.limit]:
                print(f"- {item['name']} (GARD: {item['gard_id']}, Genes: {','.join(item['genes']) or 'N/A'})")


if __name__ == "__main__":
    main()
