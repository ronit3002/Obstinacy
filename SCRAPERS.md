# Rare Disease Scrapers & Knowledge Extraction Guide

This repository contains robust scrapers and API clients built from the network inspection of two major rare disease platforms:

1. **RARe-SOURCE (NIH NCATS / NLM)** – [raresource_scraper.py](file:///Users/samuelschreiner/Desktop/hacknation031026/raresource_scraper.py)
   * Extracted from `raresource_search_aliases.har`
   * Provides clinical identifiers (**GARD, OMIM, Orphanet, UMLS, MeSH, ICD-10-CM**), **associated causative genes** (HGNC, Ensembl, UniProt), **synonyms/aliases**, and **PubMed literature citations (TOTEM)** across **7,200 rare diseases**.
2. **RareConnect (EURORDIS)** – [rareconnect_scraper.py](file:///Users/samuelschreiner/Desktop/hacknation031026/rareconnect_scraper.py)
   * Extracted from `rareconnect_search.har`
   * Provides international **patient advocacy communities** across **13 languages**, membership counts, descriptions, and **real-world patient discussions/posts**.
3. **NORD (National Organization for Rare Disorders)** – [nord_scraper.py](file:///Users/samuelschreiner/Desktop/hacknation031026/nord_scraper.py)
   * Extracted from `rare_diseases_scraper.har`
   * Request-based scraper that extracts **all patient organizations listed at the bottom of a rare disease report**, including: **name, adresse, website, nummer, email, and description**.
4. **Unified Knowledge Pipeline** – [scrapers.py](file:///Users/samuelschreiner/Desktop/hacknation031026/scrapers.py)
   * Combines clinical data with patient community and organization contact profiles.
   * Directly exports **Atlas Graph nodes and edges** (`Disease`, `Gene`, `Paper`, `Claim`, `PatientOrg`) conforming to the schema in [test.py](file:///Users/samuelschreiner/Desktop/hacknation031026/test.py).


---

## 1. Quickstart & Installation

### Requirements
Python 3.9+ with standard libraries plus `requests` and `beautifulsoup4`:
```bash
pip install requests beautifulsoup4
```

### Fast Test via Command Line
```bash
# 1. Search RARe-SOURCE for diseases and aliases
python3 raresource_scraper.py search "dravet"

# 2. Get full clinical details (GARD, OMIM, genes, PubMed papers)
python3 raresource_scraper.py details "Severe myoclonic epilepsy in infancy"

# 3. Search RareConnect patient communities
python3 rareconnect_scraper.py search "epilepsy"

# 4. Fetch patient discussions from a community
python3 rareconnect_scraper.py posts "dravet-syndrome" --limit 3

# 5. Generate a combined knowledge bundle + Atlas Graph nodes/edges
python3 scrapers.py "Dravet syndrome" --graph
```

---

## 2. RARe-SOURCE Scraper (`raresource_scraper.py`)

### Overview
NIH NCATS RARe-SOURCE hosts a comprehensive index of rare diseases. 
* **Endpoints Used:**
  * `GET https://raresource.nih.gov/diseases/` (renders the 7,200-disease summary table and provides session CSRF tokens)
  * `POST https://raresource.nih.gov/diseases/disease_info/` (AJAX endpoint returning structured JSON for a given disease name)
* **Offline Support:** Automatically parses the full 7,200-disease catalog from `raresource_search_aliases.har` and saves a fast local cache (`raresource_catalog.json`), enabling instant sub-millisecond searches without internet access.

### Available Functions

#### A. `get_disease_details(disease_name: str) -> dict`
Fetches complete genomic and bibliographic metadata for a disease or alias.

* **What to put in:**
  * `disease_name` (`str`): Primary name or alias of the disease (e.g., `"Dravet syndrome"`, `"Severe myoclonic epilepsy in infancy"`, `"Fabry disease"`, `"GRACILE syndrome"`).
  * *Note:* The function automatically resolves aliases (like `"Dravet syndrome"`) to the canonical primary name in the catalog, ensuring full TOTEM literature references are returned.

* **What to expect as a response:**
```json
{
  "disease_name": "Dravet syndrome",
  "gard_id": "0010430",
  "is_found": true,
  "error": false,
  "database_ids": {
    "gard": "0010430",
    "omim": "",
    "orphanet": "33069",
    "umls": "C0751122"
  },
  "synonyms": [
    "drvt",
    "severe myoclonus epilepsy of infancy",
    "epileptic encephalopathy, early infantile, 6 (dravet syndrome)",
    "ds",
    "myoclonic epilepsy, severe, of infancy",
    "smeb",
    "sme",
    "smei",
    "dravet syndrome",
    "dravet",
    "severe myoclonic epilepsy of infancy",
    "Severe myoclonic epilepsy in infancy"
  ],
  "genes": [
    {
      "gene_symbol": "SCN1A",
      "gene_id": 6323,
      "ensembl_gene_id": "ENSG00000144285",
      "hgnc_gene_id": "10585",
      "uniprot_id": "P35498",
      "gene_description": "sodium voltage-gated channel alpha subunit 1"
    }
  ],
  "literature": [
    {
      "pmid": "24254932",
      "title": "Antiepileptic drugs for the treatment of severe myoclonic epilepsy in infancy.",
      "authors": "Brigo F, Storti M",
      "journal": "The Cochrane database of systematic reviews",
      "year": "2013",
      "volume": null,
      "source": "nlm"
    },
    {
      "pmid": "23622210",
      "title": "Dravet syndrome (severe myoclonic epilepsy in infancy).",
      "authors": "Dravet C, Oguni H",
      "journal": "Handbook of clinical neurology",
      "year": "2013",
      "volume": "111",
      "source": "nlm"
    }
  ]
}
```

#### B. `search(query: str, search_aliases: bool = True, limit: int = 20) -> list[dict]`
Searches the 7,200 diseases in the catalog.

* **What to put in:**
  * `query` (`str`): Partial disease name or alias keyword (e.g. `"dravet"`, `"epilepsy"`, `"chorea"`).
  * `search_aliases` (`bool`, default `True`): Search both primary disease names and the full alias list.
  * `limit` (`int`, default `20`): Maximum results to return.

* **What to expect as a response:**
```json
[
  {
    "name": "Severe myoclonic epilepsy in infancy",
    "gard_id": "0010430",
    "aliases": [
      "drvt",
      "severe myoclonus epilepsy of infancy",
      "epileptic encephalopathy, early infantile, 6 (dravet syndrome)",
      "ds",
      "myoclonic epilepsy, severe, of infancy",
      "smeb",
      "sme",
      "smei",
      "dravet syndrome",
      "dravet"
    ],
    "genes": ["SCN1A"],
    "gene_description": "sodium voltage-gated channel alpha subunit 1",
    "omim": "",
    "orphanet": "33069",
    "umls": "C0751122",
    "mesh": "C537934",
    "icd10cm": "",
    "annotation_url": "https://raresource.nih.gov/literature/disease/0010430",
    "pmid_count": 625
  }
]
```

#### C. `get_disease_by_gard_id(gard_id: str) -> dict | None`
Looks up a disease by its official NIH GARD ID (e.g. `"0010430"` or `"10430"`).

---

## 3. RareConnect Scraper (`rareconnect_scraper.py`)

### Overview
EURORDIS RareConnect provides global patient communities where rare disease patients, families, and patient organizations connect and share knowledge.
* **Endpoints Used:**
  * `GET https://www.rareconnect.org/api/v1/communities-list` (retrieves all 267 patient communities with translation metadata)
  * `GET https://www.rareconnect.org/api/v1/posts?stream_id={stream_id}&$limit={limit}&$skip={skip}` (retrieves patient discussions and stories)
* **Offline Support:** Automatically falls back to parsing `rareconnect_search.har` if network connectivity is unavailable.

### Available Functions

#### A. `search_communities(query: str, lang: str = "en", limit: int = 20) -> list[dict]`
Searches patient communities by keyword across name, slug, description, and localized titles.

* **What to put in:**
  * `query` (`str`): Disease or topic keyword (e.g. `"dravet"`, `"huntington"`, `"syndrome"`).
  * `lang` (`str`, default `"en"`): Preferred language code (`"en"`, `"de"`, `"fr"`, `"es"`, `"it"`, `"pt"`, etc.).
  * `limit` (`int`, default `20`): Maximum results to return.

* **What to expect as a response:**
```json
[
  {
    "id": "c1f728fa-0518-472d-bb4b-3d602db0ca30",
    "slug": "dravet-syndrome",
    "name": "Dravet Syndrome",
    "default_name": "Dravet Syndrome",
    "description": "Dravet syndrome is a rare and severe form of epilepsy...",
    "total_members": 335,
    "total_posts": 152,
    "stream_id": "4708fe63-dfb9-4ba8-9680-f8e28d4253f8",
    "url": "https://www.rareconnect.org/en/community/dravet-syndrome",
    "available_languages": ["cs", "de", "en", "es", "fr", "it", "ja", "pt", "ru", "tr", "uk"]
  }
]
```

#### B. `get_community_posts(stream_id: str, limit: int = 10, skip: int = 0) -> list[dict]`
Retrieves community discussion threads, questions, and patient-reported outcomes.

* **What to put in:**
  * `stream_id` (`str`): The stream UUID of the community (found in the community object, e.g. `"4708fe63-dfb9-4ba8-9680-f8e28d4253f8"`).
  * `limit` (`int`, default `10`): Number of posts to fetch (max 50).
  * `skip` (`int`, default `0`): Offset for pagination.

* **What to expect as a response:**
```json
[
  {
    "id": "e4b3e34b-b27b-41da-a75b-16629916ecb3",
    "title": "Does early diagnosis help?",
    "body": "Yes, it will help the parents to work with the doctors in creating a better plan of care for their child. As certain medicines can increase seizures, early diagnosis will help avoid those...",
    "lang": "en",
    "post_type": "discussion",
    "comment_count": 0,
    "reaction_score": 0,
    "created_at": "2012-01-10T22:07:39.000Z"
  }
]
```

---

## 4. NORD Scraper (`nord_scraper.py`)

### Overview
NORD (National Organization for Rare Disorders - `rarediseases.org`) publishes comprehensive reports on over **1,400 rare diseases**. At the bottom of each disease report (`<section data-id="orgs">`), NORD maintains a directory of **Patient Organizations** that support patients and families affected by the disease.

[nord_scraper.py](file:///Users/samuelschreiner/Desktop/hacknation031026/nord_scraper.py) is a **request-based** client (using standard Python `requests` with zero heavy browser automation) that parses:
1. All patient organizations listed at the bottom of the disease report.
2. For each organization, performs an HTTP request to its profile page (`/organizations/.../`) to extract:
   * **Name** (`name`): Full organization title
   * **Adresse** (`adresse`): Physical / mailing address (street, city, state, ZIP)
   * **Website** (`website`): Official external homepage URL
   * **Nummer** (`nummer`): Telephone number / toll-free helpline
   * **Email** (`email`): Decoded contact email (with Cloudflare `cfemail` deobfuscation)
   * **Description** (`description`): Complete "About [Organization]" mission statement and description
   * **NORD Profile** (`nord_url`): Canonical link on `rarediseases.org`
   * **Related Diseases** (`related_diseases`): Other conditions supported by the organization

* **Offline Support:** Automatically reads from `rare_diseases_scraper.har` when offline or when `--har` is specified.

### Available Functions

#### A. `get_organizations_for_disease(disease_query_or_url: str, enrich_profiles: bool = True) -> list[dict]`
Scrapes all patient organizations for a given rare disease.

* **What to put in:**
  * `disease_query_or_url` (`str`): Disease name (e.g. `"Dravet syndrome"`), slug (e.g. `"dravet-syndrome-spectrum"`), or full NORD URL.
  * `enrich_profiles` (`bool`, default `True`): Makes direct HTTP requests to individual organization profile pages to extract complete address, website, and description.

* **What to expect as a response:**
```json
[
  {
    "name": "Dravet Syndrome Foundation, Inc.",
    "adresse": "PO Box 3026 Cherry Hill, NJ",
    "website": "https://www.dravetfoundation.org/",
    "nummer": "203-392-1950",
    "email": "info@dravetfoundation.org",
    "description": "The Dravet Syndrome Foundation (DSF) is a volunteer-based, non-profit organization dedicated to raising research funds for Dravet syndrome and related conditions. Dravet syndrome is a rare and catastrophic form of epilepsy beginning in childhood.",
    "nord_url": "https://rarediseases.org/organizations/dravet-syndrome-foundation-inc/",
    "fax": "",
    "related_diseases": [
      "Dravet Syndrome"
    ]
  },
  {
    "name": "Epilepsy Foundation",
    "adresse": "8301 Professional Place Landover, MD",
    "website": "https://www.epilepsy.com/",
    "nummer": "866-330-2718",
    "email": "ContactUs@efa.org",
    "description": "The Epilepsy Foundation (formerly the Epilepsy Foundation of America) is a non-profit organization with the goal of ensuring that people with seizures are able to participate in all life experiences...",
    "nord_url": "https://rarediseases.org/organizations/epilepsy-foundation/",
    "fax": "877-687-4878",
    "related_diseases": [
      "MEF2C Deficiency",
      "KCNB1 Encephalopathy",
      "Arginine: Glycine Amidinotransferase Deficiency"
    ]
  }
]
```

#### B. `to_atlas_graph_patient_orgs(disease_node_id: str, organizations: list[dict]) -> dict`
Recycles the scraped organization data directly into **Atlas Graph nodes and edges** conforming to the schema in [test.py](file:///Users/samuelschreiner/Desktop/hacknation031026/test.py):
* Creates `PatientOrg` nodes with `address`, `phone`, `email`, `url`, and `description`.
* Creates `(Disease) -[:REPRESENTED_BY {source_tier: 3, method: "curated_import"}]-> (PatientOrg)` edges.

### CLI Usage
```bash
# Extract all patient organizations for Dravet Syndrome
python3 nord_scraper.py "Dravet syndrome"

# Output formatted JSON
python3 nord_scraper.py "Dravet syndrome" --json

# Output as Atlas Graph nodes & edges
python3 nord_scraper.py "Dravet syndrome" --graph
```

---

## 5. Unified Knowledge Pipeline (`scrapers.py`)

### Overview
`scrapers.py` connects clinical/genomic data from RARe-SOURCE, international patient community metrics from RareConnect, and detailed patient organization contact profiles from NORD into a single consolidated knowledge bundle.

### Python API Usage
```python
from scrapers import get_disease_knowledge_bundle, to_atlas_graph_nodes_and_edges

# 1. Fetch complete bundle (RARe-SOURCE + RareConnect + NORD)
bundle = get_disease_knowledge_bundle("Dravet syndrome", posts_limit=3, include_nord_orgs=True)

# 2. Inspect clinical, community, and organization data
print("Canonical Name:", bundle["disease"]["canonical_name"])
print("GARD ID:", bundle["disease"]["gard_id"])
print("Genes:", [g["gene_symbol"] for g in bundle["genes"]])
print("PubMed PMIDs:", [p["pmid"] for p in bundle["literature"]])
print("RareConnect Community:", bundle["patient_community"]["name"], f"({bundle['patient_community']['total_members']} members)")
print(f"NORD Organizations ({len(bundle['patient_organizations'])}):")
for org in bundle["patient_organizations"]:
    print(f"  - {org['name']} | Phone: {org['nummer']} | Email: {org['email']} | Web: {org['website']}")

# 3. Convert to Atlas Graph schema (verified with 0 schema violations)
graph = to_atlas_graph_nodes_and_edges(bundle)
print(f"Generated {len(graph['nodes'])} nodes and {len(graph['edges'])} edges.")
```


### Graph Mapping to `test.py`
The output of `to_atlas_graph_nodes_and_edges()` matches the exact schema defined in [test.py](file:///Users/samuelschreiner/Desktop/hacknation031026/test.py):

| Entity | Atlas Node Type | Source | Properties Included |
|---|---|---|---|
| **Rare Disease** | `Disease` | RARe-SOURCE | `id`, `name`, `gard_id`, `synonyms`, `omim`, `orphanet`, `umls` |
| **Causative Gene** | `Gene` | RARe-SOURCE | `id`, `symbol`, `hgnc_id`, `uniprot_id`, `description` |
| **Scientific Paper** | `Paper` | RARe-SOURCE (TOTEM) | `id`, `pmid`, `title`, `authors`, `journal`, `year` |
| **Evidence Claim** | `Claim` | TOTEM / Citation | `id`, `quote`, `pmid`, `status`, `confidence`, `model`, `prompt_version` |
| **Patient Community** | `PatientOrg` | RareConnect | `id`, `name`, `slug`, `url`, `total_members`, `total_posts` |

#### Edge Relations Generated:
* `(Disease) -[:ASSOCIATED_WITH {source_tier: 1, method: "curated_import"}]-> (Gene)`
* `(Paper) -[:CONTAINS {source_tier: 2, method: "curated_import"}]-> (Claim)`
* `(Claim) -[:ABOUT {source_tier: 2, method: "curated_import"}]-> (Disease)`
* `(Disease) -[:REPRESENTED_BY {source_tier: 3, method: "curated_import"}]-> (PatientOrg)`


---

## 5. Technical Implementation Details & Gotchas Handled

1. **Django CSRF Authentication (RARe-SOURCE):**
   * The `POST /diseases/disease_info/` endpoint requires a valid `X-CSRFToken` header matching the `csrftoken` cookie.
   * `RAReSourceScraper` manages this transparently: it initializes a session, fetches the cookie on initial `GET`, and attaches the token to subsequent POST requests.
2. **Case Sensitivity & Alias Normalization:**
   * In RARe-SOURCE, querying an alias directly can yield partial results because TOTEM literature links are indexed under the primary canonical name.
   * `RAReSourceScraper` automatically checks the catalog to resolve any alias to its canonical primary name before querying.
3. **Feathers.js Pagination (RareConnect):**
   * RareConnect uses Feathers.js where pagination parameters require a dollar sign (`$limit`, `$skip`). Standard query strings like `limit=5` cause a 500 server error.
   * `RareConnectScraper` explicitly formats requests with `$limit` and `$skip`.
4. **Resilient Data Normalization:**
   * RARe-SOURCE returns `totem: False` instead of `[]` when no literature articles are found.
   * `RAReSourceScraper` normalizes all empty or boolean responses to typed empty lists (`[]`).
