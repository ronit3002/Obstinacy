"""
NORD (rarediseases.org) Request-Based Scraper & Patient Organization Client
Scrapes and extracts patient organizations listed at the bottom of rare disease reports,
including: name, adresse (address), website, nummer (phone), email, and description.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("nord_scraper")


def decode_cf_email(cf_hex: str) -> str:
    """Decodes Cloudflare email-protection hex strings."""
    if not cf_hex or len(cf_hex) < 4:
        return ""
    try:
        r = int(cf_hex[:2], 16)
        return "".join([chr(int(cf_hex[i : i + 2], 16) ^ r) for i in range(2, len(cf_hex), 2)])
    except Exception:
        return ""


class NORDScraper:
    """Request-based scraper for NORD (National Organization for Rare Disorders - rarediseases.org).

    Extracts:
      - Patient organizations listed at the bottom of a rare disease report.
      - Per-organization metadata: name, adresse, website, nummer (phone), email, and description.
      - Supports offline parsing from rare_diseases_scraper.har.
    """

    BASE_URL = "https://rarediseases.org"
    SITEMAP_DISEASES_URL = f"{BASE_URL}/wp-sitemap-posts-rare-diseases-1.xml"
    DEFAULT_HAR_PATH = Path(__file__).resolve().parent / "rare_diseases_scraper.har"
    SLUG_CACHE_FILE = Path(__file__).resolve().parent / "nord_disease_slugs.json"

    def __init__(
        self,
        har_path: Optional[str | Path] = None,
        timeout: int = 15,
    ) -> None:
        self.har_path = Path(har_path) if har_path else self.DEFAULT_HAR_PATH
        self.timeout = timeout
        self._session: Optional[requests.Session] = None
        self._disease_slug_map: Optional[Dict[str, str]] = None

    def _get_session(self) -> requests.Session:
        """Initializes an HTTP session with browser-like headers."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "sec-ch-ua-platform": '"macOS"',
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "none",
                }
            )
        return self._session

    def load_disease_sitemap(self, force_refresh: bool = False) -> Dict[str, str]:
        """Loads a map of normalized disease keywords -> NORD report URLs."""
        if self._disease_slug_map and not force_refresh:
            return self._disease_slug_map

        # 1. Try local cache
        if not force_refresh and self.SLUG_CACHE_FILE.exists():
            try:
                with open(self.SLUG_CACHE_FILE, "r", encoding="utf-8") as f:
                    self._disease_slug_map = json.load(f)
                    return self._disease_slug_map
            except Exception as e:
                logger.warning("Failed reading slug cache: %s", e)

        # 2. Scrape WordPress XML sitemap
        slug_map: Dict[str, str] = {}
        try:
            session = self._get_session()
            resp = session.get(self.SITEMAP_DISEASES_URL, timeout=self.timeout)
            if resp.status_code == 200:
                urls = re.findall(
                    r"<loc>(https://rarediseases.org/rare-diseases/([^/<]+)/?)</loc>",
                    resp.text,
                )
                for full_url, slug in urls:
                    clean_slug = slug.strip().lower()
                    name_key = clean_slug.replace("-", " ")
                    slug_map[name_key] = full_url.rstrip("/") + "/"
                    slug_map[clean_slug] = full_url.rstrip("/") + "/"

                try:
                    with open(self.SLUG_CACHE_FILE, "w", encoding="utf-8") as f:
                        json.dump(slug_map, f, indent=2)
                except Exception as e:
                    logger.warning("Could not write slug cache: %s", e)

                self._disease_slug_map = slug_map
                return self._disease_slug_map
        except Exception as e:
            logger.warning("Could not fetch NORD sitemap: %s", e)

        # Fallback minimal mapping
        fallback = {
            "dravet syndrome": f"{self.BASE_URL}/rare-diseases/dravet-syndrome-spectrum/",
            "dravet syndrome spectrum": f"{self.BASE_URL}/rare-diseases/dravet-syndrome-spectrum/",
            "cystic fibrosis": f"{self.BASE_URL}/rare-diseases/cystic-fibrosis/",
            "huntington disease": f"{self.BASE_URL}/rare-diseases/huntingtons-disease/",
            "huntingtons disease": f"{self.BASE_URL}/rare-diseases/huntingtons-disease/",
            "fabry disease": f"{self.BASE_URL}/rare-diseases/fabry-disease/",
        }
        self._disease_slug_map = fallback
        return fallback

    def resolve_disease_url(self, query_or_url: str) -> Optional[str]:
        """Resolves a disease name, slug, or URL to a canonical NORD disease report URL."""
        text = query_or_url.strip()
        if text.startswith("http://") or text.startswith("https://"):
            return text.rstrip("/") + "/"

        # Check if text looks like a slug
        slug_candidate = text.lower().replace(" ", "-")
        direct_url = f"{self.BASE_URL}/rare-diseases/{slug_candidate}/"

        # Check sitemap
        sitemap = self.load_disease_sitemap()
        q_clean = text.lower().strip()

        # Exact match
        if q_clean in sitemap:
            return sitemap[q_clean]
        if slug_candidate in sitemap:
            return sitemap[slug_candidate]

        # Partial substring match
        for key, url in sitemap.items():
            if q_clean in key or key in q_clean:
                return url

        return direct_url

    def get_disease_page_html(
        self,
        query_or_url: str,
        use_har: bool = True,
    ) -> tuple[str, str]:
        """Fetches disease report HTML, falling back to rare_diseases_scraper.har if offline."""
        # 1. Try local HAR file if query specifically matches dravet
        target_norm = query_or_url.lower()
        if use_har and self.har_path.exists() and "dravet" in target_norm:
            har_html = self._parse_disease_html_from_har(self.har_path)
            if har_html:
                logger.debug("Loaded disease page HTML from HAR %s", self.har_path)
                return har_html, f"{self.BASE_URL}/rare-diseases/dravet-syndrome-spectrum/"

        # 2. Live request via session
        url = self.resolve_disease_url(query_or_url)
        if not url:
            raise ValueError(f"Could not resolve disease URL for query: {query_or_url}")

        session = self._get_session()
        try:
            resp = session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.text, url
            elif resp.status_code == 404:
                # Try finding in HAR as fallback
                if self.har_path.exists() and "dravet" in target_norm:
                    har_html = self._parse_disease_html_from_har(self.har_path)
                    if har_html:
                        return har_html, f"{self.BASE_URL}/rare-diseases/dravet-syndrome-spectrum/"
                raise ValueError(f"Disease page not found (404): {url}")
            else:
                resp.raise_for_status()
        except Exception as e:
            # Fallback to HAR if network fails
            if self.har_path.exists():
                har_html = self._parse_disease_html_from_har(self.har_path)
                if har_html:
                    logger.warning("Live request failed (%s); using HAR file.", e)
                    return har_html, f"{self.BASE_URL}/rare-diseases/dravet-syndrome-spectrum/"
            raise RuntimeError(f"Failed fetching disease page from {url}: {e}") from e


        return "", url

    def _parse_disease_html_from_har(self, har_path: Path) -> Optional[str]:
        """Extracts the rare disease report HTML from the HAR file."""
        with open(har_path, "r", encoding="utf-8", errors="ignore") as f:
            har_data = json.load(f)

        for entry in har_data.get("log", {}).get("entries", []):
            url = entry.get("request", {}).get("url", "")
            if "/rare-diseases/" in url and entry.get("request", {}).get("method") == "GET":
                text = entry.get("response", {}).get("content", {}).get("text", "")
                if 'data-id="orgs"' in text or "Patient Organizations" in text:
                    return text
        return None

    def get_organization_profile(self, org_url: str) -> Dict[str, Any]:
        """Fetches and parses a single organization profile page via requests.

        Extracts:
          - adresse (physical / mailing address)
          - website (official URL)
          - nummer (phone)
          - email (decoded email)
          - description (About text)
        """
        session = self._get_session()
        data = {
            "adresse": "",
            "website": "",
            "nummer": "",
            "email": "",
            "description": "",
        }

        try:
            resp = session.get(org_url, timeout=self.timeout)
            if resp.status_code != 200:
                logger.debug("Profile page %s returned status %d", org_url, resp.status_code)
                return data

            soup = BeautifulSoup(resp.text, "html.parser")
            contact_div = soup.find("div", class_="contact-info")

            if contact_div:
                # 1. Adresse / Address (bi-pin-map)
                pin = contact_div.find("i", class_="bi-pin-map")
                if pin and pin.find_next_sibling("p"):
                    data["adresse"] = " ".join(pin.find_next_sibling("p").stripped_strings)

                # 2. Nummer / Telephone (bi-telephone)
                tel = contact_div.find("i", class_="bi-telephone")
                if tel and tel.find_next_sibling("p"):
                    data["nummer"] = tel.find_next_sibling("p").get_text().strip()

                # 3. Email (bi-envelope, with Cloudflare deobfuscation)
                env = contact_div.find("i", class_="bi-envelope")
                if env and env.find_next_sibling("p"):
                    cf = env.find_next_sibling("p").find("span", class_="__cf_email__")
                    if cf and cf.get("data-cfemail"):
                        data["email"] = decode_cf_email(cf["data-cfemail"])
                    else:
                        p_text = env.find_next_sibling("p").get_text().strip()
                        if "@" in p_text and not p_text.startswith("[email"):
                            data["email"] = p_text

                # 4. Website (bi-link)
                link_i = contact_div.find("i", class_="bi-link")
                if link_i and link_i.find_next_sibling("p"):
                    a_tag = link_i.find_next_sibling("p").find("a")
                    if a_tag and a_tag.get("href"):
                        data["website"] = a_tag["href"].strip()
                    else:
                        data["website"] = link_i.find_next_sibling("p").get_text().strip()

            # 5. Description ("About [Organization]")
            about_h2 = soup.find(lambda t: t.name == "h2" and "about" in t.text.lower())
            if about_h2:
                paragraphs = []
                for sib in about_h2.find_all_next():
                    if sib.name == "h2":
                        break
                    if sib.name == "p":
                        text = sib.get_text().strip()
                        if text:
                            paragraphs.append(text)
                data["description"] = " ".join(paragraphs)

        except Exception as e:
            logger.debug("Failed requesting organization profile %s: %s", org_url, e)

        return data

    def get_organizations_for_disease(
        self,
        disease_query_or_url: str,
        enrich_profiles: bool = True,
        use_har: bool = True,
    ) -> List[Dict[str, Any]]:
        """Scrapes all patient organizations listed at the bottom of a rare disease report.

        Args:
            disease_query_or_url: Disease name (e.g. 'Dravet syndrome'), slug, or NORD URL.
            enrich_profiles: Whether to make HTTP requests to each organization's profile
                             to extract detailed address, official website, and description.
            use_har: Whether to allow fallback to rare_diseases_scraper.har.

        Returns:
            List of organization dictionaries with:
              - name: Organization name
              - adresse: Street / PO Box, City, State, ZIP
              - website: Official external website
              - nummer: Phone number
              - email: Decoded email
              - description: Detailed About description
              - nord_url: NORD profile page URL
              - fax: Fax number if listed
              - related_diseases: List of other diseases supported
        """
        html, source_url = self.get_disease_page_html(disease_query_or_url, use_har=use_har)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Find the organizations section at the bottom (data-id="orgs")
        orgs_section = soup.find("section", attrs={"data-id": "orgs"})
        if not orgs_section:
            # Fallback search for any section or div containing Patient Organizations
            orgs_section = soup.find(
                lambda t: t.name in ["section", "div"]
                and "organizations" in " ".join(t.get("class", []))
            )

        if not orgs_section:
            logger.warning("No Patient Organizations section found on %s", source_url)
            return []

        org_cards = orgs_section.find_all("div", class_="single-rd-resource")
        organizations: List[Dict[str, Any]] = []

        for card in org_cards:
            h5 = card.find("h5")
            if not h5:
                continue

            name = h5.get_text().strip()
            a_tag = h5.find("a")
            nord_url = a_tag["href"].strip() if a_tag and a_tag.get("href") else ""

            # Card contact details (phone, email, fax on the disease page)
            card_phone = ""
            card_email = ""
            card_fax = ""

            phone_span = card.find("span", class_="phone")
            if phone_span:
                phone_a = phone_span.find("a")
                card_phone = (
                    phone_a.get_text().strip()
                    if phone_a
                    else phone_span.get_text().replace("Phone:", "").strip()
                )

            email_span = card.find("span", class_="email")
            if email_span:
                cf = email_span.find("span", class_="__cf_email__")
                if cf and cf.get("data-cfemail"):
                    card_email = decode_cf_email(cf["data-cfemail"])
                else:
                    mail_text = email_span.get_text().replace("Email:", "").strip()
                    if "@" in mail_text and not mail_text.startswith("[email"):
                        card_email = mail_text

            fax_span = card.find("span", class_="fax")
            if fax_span:
                card_fax = fax_span.get_text().replace("Fax:", "").strip()

            # Related diseases listed on card
            related_diseases = []
            rd_span = card.find("div", class_="rd-details")
            if rd_span:
                for rd_a in rd_span.find_all("a"):
                    related_diseases.append(rd_a.get_text().strip())

            org_entry = {
                "name": name,
                "adresse": "",
                "website": "",
                "nummer": card_phone,
                "email": card_email,
                "description": "",
                "nord_url": nord_url,
                "fax": card_fax,
                "related_diseases": related_diseases,
            }

            # Enrich from individual organization profile page via request
            if enrich_profiles and nord_url:
                profile_details = self.get_organization_profile(nord_url)
                if profile_details.get("adresse"):
                    org_entry["adresse"] = profile_details["adresse"]
                if profile_details.get("website"):
                    org_entry["website"] = profile_details["website"]
                if profile_details.get("nummer") and not org_entry["nummer"]:
                    org_entry["nummer"] = profile_details["nummer"]
                if profile_details.get("email") and not org_entry["email"]:
                    org_entry["email"] = profile_details["email"]
                if profile_details.get("description"):
                    org_entry["description"] = profile_details["description"]

            organizations.append(org_entry)

        return organizations

    def to_atlas_graph_patient_orgs(
        self,
        disease_node_id: str,
        organizations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Converts scraped organizations into Atlas Graph PatientOrg nodes and REPRESENTED_BY edges."""
        nodes = []
        edges = []

        for org in organizations:
            # Create a slug-like ID
            name_slug = re.sub(r"[^a-zA-Z0-9]+", "-", org["name"].lower()).strip("-")
            org_id = f"PatientOrg:nord:{name_slug}"

            nodes.append(
                {
                    "id": org_id,
                    "type": "PatientOrg",
                    "name": org["name"],
                    "url": org["website"] or org["nord_url"],
                    "address": org["adresse"],
                    "phone": org["nummer"],
                    "email": org["email"],
                    "description": org["description"],
                    "source": "NORD",
                }
            )

            edges.append(
                {
                    "src": disease_node_id,
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
    parser = argparse.ArgumentParser(description="NORD Request-Based Patient Organization Scraper")
    parser.add_argument(
        "disease",
        nargs="?",
        default="Dravet syndrome",
        help="Disease name, slug, or NORD URL (default: 'Dravet syndrome')",
    )
    parser.add_argument(
        "--har",
        type=str,
        help="Path to rare_diseases_scraper.har file for offline mode",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip requesting individual organization profile pages (faster)",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Output in Atlas Graph nodes/edges schema format",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON format",
    )

    args = parser.parse_args()
    scraper = NORDScraper(har_path=args.har)

    orgs = scraper.get_organizations_for_disease(
        args.disease,
        enrich_profiles=not args.no_enrich,
    )

    if args.graph:
        graph = scraper.to_atlas_graph_patient_orgs("Disease:0010430", orgs)
        print(json.dumps(graph, indent=2))
        return

    if args.json:
        print(json.dumps(orgs, indent=2))
        return

    print(f"\n=======================================================")
    print(f"  Patient Organizations for: {args.disease}")
    print(f"  Total Organizations Found: {len(orgs)}")
    print(f"=======================================================\n")

    for i, org in enumerate(orgs, 1):
        print(f"[{i}] {org['name']}")
        print(f"    Adresse:     {org['adresse'] or 'N/A'}")
        print(f"    Website:     {org['website'] or 'N/A'}")
        print(f"    Nummer:      {org['nummer'] or 'N/A'}")
        print(f"    Email:       {org['email'] or 'N/A'}")
        print(f"    NORD Profil: {org['nord_url'] or 'N/A'}")
        desc_preview = (org['description'][:130] + "...") if len(org['description']) > 130 else org['description']
        print(f"    Description: {desc_preview or 'N/A'}\n")


if __name__ == "__main__":
    main()
