# Rare Disease Scrapers & Knowledge Extraction Guide

This repository contains robust scrapers and API clients built from the network inspection of two major rare disease platforms:

1. **RARe-SOURCE (NIH NCATS / NLM)** – [raresource_scraper.py](file:///Users/samuelschreiner/Desktop/hacknation031026/raresource_scraper.py)
   * Extracted from `raresource_search_aliases.har`
   * Provides clinical identifiers (**GARD, OMIM, Orphanet, UMLS, MeSH, ICD-10-CM**), **associated causative genes** (HGNC, Ensembl, UniProt), **synonyms/aliases**, and **PubMed literature citations (TOTEM)** across **7,200 rare diseases**.
2. **RareConnect (EURORDIS)** – [rareconnect_scraper.py](file:///Users/samuelschreiner/Desktop/hacknation031026/rareconnect_scraper.py)
   * Extracted from `rareconnect_search.har`
   * Provides international **patient advocacy communities** across **13 languages**, membership counts, descriptions, and **real-world patient discussions/posts**.
3. **Unified Knowledge Pipeline** – [scrapers.py](file:///Users/samuelschreiner/Desktop/hacknation031026/scrapers.py)
   * Combines clinical data with patient community data.
   * Directly exports **Atlas Graph nodes and edges** (`Disease`, `Gene`, `Paper`, `PatientOrg`) conforming to the schema in [test.py](file:///Users/samuelschreiner/Desktop/hacknation031026/test.py).

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

## 4. Unified Knowledge Pipeline (`scrapers.py`)

### Overview
`scrapers.py` connects clinical/genomic data from RARe-SOURCE with patient community data from RareConnect, producing a single consolidated knowledge bundle.

### Python API Usage
```python
from scrapers import get_disease_knowledge_bundle, to_atlas_graph_nodes_and_edges

# 1. Fetch complete bundle
bundle = get_disease_knowledge_bundle("Dravet syndrome", posts_limit=3)

# 2. Inspect clinical & patient data
print("Canonical Name:", bundle["disease"]["canonical_name"])
print("GARD ID:", bundle["disease"]["gard_id"])
print("Genes:", [g["gene_symbol"] for g in bundle["genes"]])
print("PubMed PMIDs:", [p["pmid"] for p in bundle["literature"]])
print("Community URL:", bundle["patient_community"]["url"])
print("Community Members:", bundle["patient_community"]["total_members"])

# 3. Convert to Atlas Graph schema
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
