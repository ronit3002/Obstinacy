"""
RareConnect (EURORDIS) Scraper & API Client
Scrapes and queries rare disease patient communities, member stats, descriptions,
translations, and discussion stream posts.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("rareconnect_scraper")


class RareConnectScraper:
    """Client for querying the EURORDIS RareConnect platform.

    Supports:
      - Live querying of the RareConnect API (communities list and discussion stream posts).
      - Offline fallback using the provided HAR file.
      - Searching communities across 13 supported languages.
      - Fetching community posts and patient discussions.
    """

    BASE_URL = "https://www.rareconnect.org"
    COMMUNITIES_LIST_URL = f"{BASE_URL}/api/v1/communities-list"
    POSTS_URL = f"{BASE_URL}/api/v1/posts"
    DEFAULT_HAR_PATH = Path(__file__).resolve().parent / "rareconnect_search.har"

    def __init__(
        self,
        har_path: Optional[str | Path] = None,
        timeout: int = 15,
    ) -> None:
        self.har_path = Path(har_path) if har_path else self.DEFAULT_HAR_PATH
        self.timeout = timeout
        self._communities_cache: Optional[Dict[str, Dict[str, Any]]] = None

    def _get_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

    def load_raw_communities(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Loads all raw community objects from the live API or local HAR file."""
        if not force_refresh:
            # 1. Try live API
            try:
                resp = requests.get(
                    self.COMMUNITIES_LIST_URL,
                    headers=self._get_headers(),
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    return resp.json()
            except Exception as e:
                logger.warning("Live API call failed (%s), falling back to HAR file", e)

        # 2. Fallback to HAR file
        if self.har_path.exists():
            try:
                return self._parse_from_har(self.har_path)
            except Exception as e:
                logger.error("Failed to parse HAR file %s: %s", self.har_path, e)

        raise RuntimeError("Unable to load RareConnect communities from live API or HAR file.")

    def _parse_from_har(self, har_path: Path) -> List[Dict[str, Any]]:
        with open(har_path, "r", encoding="utf-8", errors="ignore") as f:
            har_data = json.load(f)

        for entry in har_data.get("log", {}).get("entries", []):
            url = entry.get("request", {}).get("url", "")
            if "/api/v1/communities-list" in url:
                text = entry.get("response", {}).get("content", {}).get("text", "")
                if text:
                    return json.loads(text)

        raise ValueError(f"No communities-list found in HAR file: {har_path}")

    def get_all_communities(
        self,
        lang: str = "en",
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Returns all unique rare disease communities, aggregated across languages.

        Args:
            lang: Preferred language code ('en', 'de', 'fr', 'es', etc.) for name and description.
            force_refresh: Whether to bypass in-memory cache and re-fetch from API.

        Returns:
            List of unique community dictionaries sorted alphabetically by name.
        """
        if self._communities_cache is None or force_refresh:
            raw_list = self.load_raw_communities(force_refresh=force_refresh)
            by_slug: Dict[str, Dict[str, Any]] = {}

            for item in raw_list:
                slug = item.get("slug")
                if not slug:
                    continue

                if slug not in by_slug:
                    by_slug[slug] = {
                        "id": item.get("id"),
                        "slug": slug,
                        "default_name": item.get("default_name", "").strip(),
                        "default_description": item.get("default_description", "").strip(),
                        "stream_id": item.get("stream_id"),
                        "total_members": int(item.get("total_members") or 0),
                        "total_posts": int(item.get("total_posts") or 0),
                        "url": f"{self.BASE_URL}/{lang}/community/{slug}",
                        "translations": {},
                    }

                item_lang = item.get("lang")
                if item_lang:
                    by_slug[slug]["translations"][item_lang] = {
                        "name": item.get("name", "").strip(),
                        "description": item.get("description", "").strip(),
                    }

            self._communities_cache = by_slug

        # Format output according to requested language
        results: List[Dict[str, Any]] = []
        for slug, comm in self._communities_cache.items():
            trans = comm["translations"].get(lang) or comm["translations"].get("en") or {}
            display_name = trans.get("name") or comm["default_name"]
            display_desc = trans.get("description") or comm["default_description"]

            results.append(
                {
                    "id": comm["id"],
                    "slug": comm["slug"],
                    "name": display_name,
                    "description": display_desc,
                    "default_name": comm["default_name"],
                    "total_members": comm["total_members"],
                    "total_posts": comm["total_posts"],
                    "stream_id": comm["stream_id"],
                    "url": f"{self.BASE_URL}/{lang}/community/{slug}",
                    "available_languages": sorted(comm["translations"].keys()),
                }
            )

        results.sort(key=lambda x: x["name"].lower())
        return results

    def search_communities(
        self,
        query: str,
        lang: str = "en",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Searches for communities matching a query string across names, descriptions, and slugs.

        Args:
            query: Keyword or disease name to search (e.g. 'dravet', 'epilepsy').
            lang: Language for display names.
            limit: Maximum results to return.

        Returns:
            List of matching community dictionaries sorted by relevance and member count.
        """
        all_comms = self.get_all_communities(lang=lang)
        q = query.strip().lower()
        if not q:
            return all_comms[:limit]

        exact: List[Dict[str, Any]] = []
        name_matches: List[Dict[str, Any]] = []
        desc_matches: List[Dict[str, Any]] = []

        for comm in all_comms:
            name_lower = comm["name"].lower()
            def_name_lower = comm["default_name"].lower()
            slug_lower = comm["slug"].lower()
            desc_lower = comm["description"].lower()

            if q == name_lower or q == def_name_lower or q == slug_lower:
                exact.append(comm)
            elif q in name_lower or q in def_name_lower or q in slug_lower:
                name_matches.append(comm)
            elif q in desc_lower:
                desc_matches.append(comm)

        # Sort matches within each tier by total_members descending
        exact.sort(key=lambda x: x["total_members"], reverse=True)
        name_matches.sort(key=lambda x: x["total_members"], reverse=True)
        desc_matches.sort(key=lambda x: x["total_members"], reverse=True)

        results = exact + name_matches + desc_matches
        return results[:limit]

    def get_community_by_slug(self, slug: str, lang: str = "en") -> Optional[Dict[str, Any]]:
        """Retrieves a single community by its slug."""
        all_comms = self.get_all_communities(lang=lang)
        slug_clean = slug.strip().lower()
        for comm in all_comms:
            if comm["slug"].lower() == slug_clean:
                return comm
        return None

    def get_community_posts(
        self,
        stream_id: str,
        limit: int = 10,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """Fetches discussion posts from a community's stream.

        Args:
            stream_id: UUID of the community stream.
            limit: Number of posts to retrieve (max 50).
            skip: Offset for pagination.

        Returns:
            List of cleaned post objects with id, title, body, lang, created_at, comment_count.
        """
        params = {
            "stream_id": stream_id,
            "$limit": limit,
            "$skip": skip,
        }

        try:
            resp = requests.get(
                self.POSTS_URL,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Failed fetching stream posts for %s: %s", stream_id, e)
            return []

        posts = []
        for p in data.get("data", []):
            posts.append(
                {
                    "id": p.get("id"),
                    "title": p.get("title", "").strip(),
                    "body": p.get("body", "").strip(),
                    "lang": p.get("lang"),
                    "post_type": p.get("post_type"),
                    "comment_count": p.get("comment_count", 0),
                    "reaction_score": p.get("reaction_score", 0),
                    "created_at": p.get("created_at"),
                }
            )

        return posts


def main() -> None:
    parser = argparse.ArgumentParser(description="RareConnect (EURORDIS) Scraper & Query Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Search command
    search_parser = subparsers.add_parser("search", help="Search RareConnect communities")
    search_parser.add_argument("query", help="Keyword or disease name to search")
    search_parser.add_argument("--lang", default="en", help="Language code (default: en)")
    search_parser.add_argument("--limit", type=int, default=10, help="Max results to display")
    search_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    # List command
    list_parser = subparsers.add_parser("list", help="List all RareConnect communities")
    list_parser.add_argument("--limit", type=int, default=15, help="Number of communities to list")
    list_parser.add_argument("--lang", default="en", help="Language code")
    list_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    # Posts command
    posts_parser = subparsers.add_parser("posts", help="Fetch posts from a community by slug or stream_id")
    posts_parser.add_argument("target", help="Community slug (e.g. 'dravet-syndrome') or stream_id UUID")
    posts_parser.add_argument("--limit", type=int, default=5, help="Number of posts to fetch")
    posts_parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()
    scraper = RareConnectScraper()

    if args.command == "search":
        results = scraper.search_communities(args.query, lang=args.lang, limit=args.limit)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"\nFound {len(results)} RareConnect communities matching '{args.query}':\n")
            for i, c in enumerate(results, 1):
                desc_snippet = (c["description"][:120] + "...") if len(c["description"]) > 120 else c["description"]
                print(f"[{i}] {c['name']} (slug: {c['slug']})")
                print(f"    Members: {c['total_members']} | Posts: {c['total_posts']} | Languages: {len(c['available_languages'])}")
                print(f"    URL: {c['url']}")
                print(f"    About: {desc_snippet or 'No description'}\n")

    elif args.command == "list":
        results = scraper.get_all_communities(lang=args.lang)
        if args.json:
            print(json.dumps(results[: args.limit], indent=2))
        else:
            print(f"\nTotal RareConnect Communities: {len(results)} (showing first {args.limit}):\n")
            for i, c in enumerate(results[: args.limit], 1):
                print(f"[{i}] {c['name']} (slug: {c['slug']}, {c['total_members']} members, {c['total_posts']} posts)")

    elif args.command == "posts":
        target = args.target.strip()
        stream_id = target
        # If target looks like a slug rather than a UUID, resolve to stream_id
        if "-" in target and len(target) != 36:
            comm = scraper.get_community_by_slug(target)
            if not comm:
                print(f"Community with slug '{target}' not found.")
                return
            stream_id = comm["stream_id"]
            print(f"Found community '{comm['name']}' (Stream ID: {stream_id})")

        posts = scraper.get_community_posts(stream_id, limit=args.limit)
        if args.json:
            print(json.dumps(posts, indent=2))
        else:
            print(f"\nFetched {len(posts)} posts from stream {stream_id}:\n")
            for i, p in enumerate(posts, 1):
                body_snippet = (p["body"][:140] + "...") if len(p["body"]) > 140 else p["body"]
                print(f"[{i}] {p['title'] or '(No title)'}")
                print(f"    Date: {p['created_at']} | Comments: {p['comment_count']} | Lang: {p['lang']}")
                print(f"    Content: {body_snippet}\n")


if __name__ == "__main__":
    main()
