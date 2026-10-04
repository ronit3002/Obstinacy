#!/usr/bin/env python3
"""
Step 5: enrich the atlas with assets, communities, funding and gene families.

For every seed disease in data/processed/graph.json this collects, from structured sources only
(no LLM involved):
  * ClinicalTrials.gov API v2   -> Study nodes  (Study STUDIES Disease, Study TESTS Intervention)
  * NORD (nord_scraper.py)      -> PatientOrg nodes (Disease REPRESENTED_BY PatientOrg)
  * RareConnect (scraper)       -> PatientOrg nodes for online patient communities
  * RARe-SOURCE / GARD          -> GARD id + curated reading list on the disease node
  * NIH RePORTER API v2         -> Grant + Researcher nodes (Researcher LEADS Grant, Grant RESEARCHES Gene)
  * HGNC REST                   -> GeneGroup nodes (Gene MEMBER_OF GeneGroup)

Writes: data/processed/enrichment.json   ({"nodes", "edges", "meta"})
Cache : data/raw/enrichment_cache/        (raw API responses; delete to refetch)
Run   : python enrich.py            (add --refresh to ignore the cache)

Matching rules are deliberately conservative and recorded on every edge (match_reason):
a trial counts for a disease only if one of its listed conditions or its title contains the
disease name, a synonym, or the gene symbol; a community only if its name does.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "data" / "processed"
CACHE = ROOT / "data" / "raw" / "enrichment_cache"
OUT = PROC / "enrichment.json"
TODAY = date.today().isoformat()
UA = {"User-Agent": "rare-disease-atlas/0.1 (hackathon research prototype)"}

MAX_TRIALS = 60         # per disease, most relevant first (cards show 5, then "show more")
MAX_GRANTS = 15         # per gene
REPORTER_YEARS = [2022, 2023, 2024, 2025, 2026]

REFRESH = False


# ------------------------------------------------------------------ cache ----
def cached(kind, key, fetch):
    """Return the cached JSON for (kind, key) or call fetch() and store it."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{kind}_{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"
    if path.exists() and not REFRESH:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def disease_terms(d):
    """Name + synonyms long enough to be specific (short abbreviations like 'DS' are skipped)."""
    terms = [d["name"]] + [s for s in d.get("synonyms", []) if len(s) >= 6 and not s.isupper()]
    seen, out = set(), []
    for t in terms:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def match_reason(text_fields, terms, gene):
    """First disease term or gene symbol that appears in any of the given texts."""
    blob = " | ".join(text_fields).lower()
    for t in terms:
        if t.lower() in blob:
            return f"lists “{t}”"
    if gene and re.search(rf"\b{re.escape(gene.lower())}\b", blob):
        return f"mentions the gene {gene}"
    return None


# ------------------------------------------------------ ClinicalTrials.gov ----
def fetch_trials(query_cond=None, query_term=None, max_pages=8):
    """All matching studies, following nextPageToken (up to max_pages x 100)."""
    params = {"pageSize": 100, "format": "json"}
    if query_cond:
        params["query.cond"] = query_cond
    if query_term:
        params["query.term"] = query_term
    studies = []
    for _ in range(max_pages):
        r = requests.get("https://clinicaltrials.gov/api/v2/studies", params=params, headers=UA, timeout=60)
        r.raise_for_status()
        data = r.json()
        studies += data.get("studies", [])
        if not data.get("nextPageToken"):
            break
        params["pageToken"] = data["nextPageToken"]
    return studies


STATUS_RANK = {"RECRUITING": 0, "NOT_YET_RECRUITING": 1, "ACTIVE_NOT_RECRUITING": 2,
               "ENROLLING_BY_INVITATION": 2, "COMPLETED": 3}


def trials_for(d, gene):
    terms = disease_terms(d)
    raw = []
    raw += cached("ctgov_all", "cond:" + d["name"], lambda: fetch_trials(query_cond=d["name"]))
    if gene:
        raw += cached("ctgov_all", "term:" + gene, lambda: fetch_trials(query_term=gene))
    picked = {}
    for s in raw:
        p = s.get("protocolSection", {})
        ident = p.get("identificationModule", {})
        nct = ident.get("nctId")
        if not nct or nct in picked:
            continue
        conds = p.get("conditionsModule", {}).get("conditions", [])
        title = ident.get("briefTitle", "")
        why = match_reason(conds + [title, ident.get("officialTitle", "")], terms, gene)
        if not why:
            continue
        status = p.get("statusModule", {})
        design = p.get("designModule", {})
        arms = p.get("armsInterventionsModule", {})
        locs = p.get("contactsLocationsModule", {}).get("locations", [])
        picked[nct] = {
            "nct": nct, "title": title, "why": why,
            "status": status.get("overallStatus", ""),
            "start": (status.get("startDateStruct") or {}).get("date", ""),
            "phases": design.get("phases", []), "study_type": design.get("studyType", ""),
            "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
            "sponsor": (p.get("sponsorCollaboratorsModule", {}).get("leadSponsor") or {}).get("name", ""),
            "conditions": conds,
            "interventions": [{"name": i.get("name", ""), "type": i.get("type", "")}
                              for i in arms.get("interventions", []) if i.get("name")],
            "countries": sorted({l.get("country") for l in locs if l.get("country")}),
            "summary": (p.get("descriptionModule", {}).get("briefSummary") or "")[:600],
        }
    ranked = sorted(picked.values(), key=lambda t: (STATUS_RANK.get(t["status"], 9), t["start"] or ""), reverse=False)
    # most active first, then most recent
    ranked.sort(key=lambda t: (STATUS_RANK.get(t["status"], 9), -int((t["start"] or "0")[:4] or 0)))
    return ranked[:MAX_TRIALS]


DRUG_TYPES = {"DRUG", "BIOLOGICAL", "GENETIC", "COMBINATION_PRODUCT", "DIETARY_SUPPLEMENT"}
PLACEBO = re.compile(r"placebo|vehicle|sham|standard of care|usual care", re.I)


def norm_intervention(name):
    """Display name for a tested drug: no dose, formulation, arm or cohort wording."""
    n = re.split("\\s*[-\u2010-\u2014]\\s*(?=[A-Z])|\\s+[-\u2013]\\s+|:|,", name)[0]  # "RC001 injection-Fixed Dose" -> "RC001 injection"
    n = re.sub(r"\(.*?\)|\b\d+(\.\d+)?\s*(mg|ml|mg/kg|%)\b.*", "", n, flags=re.I)
    n = re.sub(r"\b(oral solution|tablets?|capsules?|injection|syrup|suspension|treatment|therapy arm|"
               r"cohort|dose escalation|low dose|high dose|adjunctive)\b", "", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip(" -,")


# ---------------------------------------------------------- patient groups ----
def nord_orgs(d):
    try:
        from nord_scraper import NORDScraper
    except ImportError:
        return [], "nord_scraper unavailable"
    s = NORDScraper()
    for term in disease_terms(d)[:4]:
        url = s.resolve_disease_url(term)
        # only trust URLs that came from the sitemap/cache, not blind slug guesses
        if url not in set(s.load_disease_sitemap().values()):
            continue
        try:
            orgs = cached("nord", url, lambda: s.get_organizations_for_disease(url, enrich_profiles=True))
            return orgs, url
        except Exception as e:  # NORD blocks many automated requests
            return [], f"NORD error: {type(e).__name__}"
    return [], "no NORD report found"


def rareconnect_communities(d, gene):
    try:
        from rareconnect_scraper import RareConnectScraper
    except ImportError:
        return []
    rc = RareConnectScraper()
    allc = cached("rareconnect", "all:en", lambda: rc.get_all_communities(lang="en"))
    terms = [t.lower() for t in disease_terms(d)] + ([gene.lower()] if gene else [])
    hits = []
    for c in allc:
        name = (c.get("name") or c.get("default_name") or "").lower()
        if any(t == name or (len(t) > 5 and t in name) or (t == (gene or "").lower() and re.search(rf"\b{t}\b", name)) for t in terms):
            hits.append(c)
    return hits


def gard_info(d):
    try:
        from raresource_scraper import RAReSourceScraper
    except ImportError:
        return None
    rs = RAReSourceScraper()
    for term in disease_terms(d)[:3]:
        try:
            info = cached("raresource", term, lambda: rs.get_disease_details(term))
        except Exception:
            continue
        if info and info.get("is_found"):
            return info
    return None


# ------------------------------------------------------------ NIH RePORTER ----
def fetch_grants(gene):
    body = {"criteria": {"advanced_text_search": {"operator": "and", "search_field": "projecttitle,terms,abstracttext",
                                                   "search_text": gene},
                         "fiscal_years": REPORTER_YEARS},
            "include_fields": ["ApplId", "ProjectNum", "CoreProjectNum", "ProjectTitle", "FiscalYear", "AwardAmount",
                               "Organization", "PrincipalInvestigators", "AgencyIcAdmin", "ProjectStartDate",
                               "ProjectEndDate", "AbstractText"],
            "offset": 0, "limit": 100, "sort_field": "fiscal_year", "sort_order": "desc"}
    r = requests.post("https://api.reporter.nih.gov/v2/projects/search", json=body, headers=UA, timeout=60)
    r.raise_for_status()
    return r.json().get("results", [])


def grants_for(gene):
    rows = cached("reporter", gene, lambda: fetch_grants(gene))
    best = {}  # one record per core project (latest fiscal year)
    for p in rows:
        title = p.get("project_title") or ""
        text = f"{title} {p.get('abstract_text') or ''}"
        if not re.search(rf"\b{re.escape(gene)}\b", text, re.I):
            continue
        core = p.get("core_project_num") or p.get("project_num")
        if core not in best or (p.get("fiscal_year") or 0) > (best[core].get("fiscal_year") or 0):
            best[core] = p
    ranked = sorted(best.values(), key=lambda p: (gene.lower() in (p.get("project_title") or "").lower(),
                                                 p.get("fiscal_year") or 0, p.get("award_amount") or 0), reverse=True)
    return ranked[:MAX_GRANTS]


# -------------------------------------------------------------------- HGNC ----
def gene_groups(symbol):
    def fetch():
        r = requests.get(f"https://rest.genenames.org/fetch/symbol/{symbol}",
                         headers={"Accept": "application/json", **UA}, timeout=30)
        r.raise_for_status()
        docs = r.json()["response"]["docs"]
        return docs[0] if docs else {}
    doc = cached("hgnc", symbol, fetch)
    return list(zip(doc.get("gene_group_id", []), doc.get("gene_group", [])))


# -------------------------------------------------------------------- main ----
def main():
    global REFRESH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="ignore cached API responses")
    REFRESH = ap.parse_args().refresh

    g = json.loads((PROC / "graph.json").read_text(encoding="utf-8"))
    nodes_in = {n["id"]: n for n in g["nodes"]}
    diseases = [n for n in g["nodes"] if n["type"] == "Disease" and not n.get("paper_scoped")]
    disease_gene = {}
    for e in g["edges"]:
        if e["rel"] == "ASSOCIATED_WITH" and e["target"] in nodes_in:
            disease_gene[e["source"]] = nodes_in[e["target"]]

    nodes, edges, disease_props, log = {}, [], {}, []

    def node(nid, ntype, **props):
        # cached HAR pages can carry U+FFFD for an en dash; show a dash instead of a broken glyph
        props = {k: v.replace("�", "–") if isinstance(v, str) else v for k, v in props.items()}
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, **props}
        return nid

    def edge(src, dst, rel, source, tier, **props):
        edges.append({"id": f"{rel}:{src}->{dst}", "rel": rel, "source": src, "target": dst,
                      "source_name": source, "source_tier": tier, "retrieved": TODAY,
                      "status": "observation", "method": "curated_import", **props})

    for d in diseases:
        gene = disease_gene.get(d["id"])
        sym = gene["name"] if gene else None
        label = d.get("short") or d["name"]
        print(f"\n== {label}: {d['name']}")

        # Clinical trials
        try:
            trials = trials_for(d, sym)
        except Exception as e:
            trials = []
            log.append(f"{label}: ClinicalTrials.gov failed ({type(e).__name__})")
        for t in trials:
            sid = node(f"NCT:{t['nct']}", "Study", name=t["title"], nct=t["nct"], status=t["status"],
                       phases=t["phases"], study_type=t["study_type"], start=t["start"], sponsor=t["sponsor"],
                       enrollment=t["enrollment"], conditions=t["conditions"], countries=t["countries"],
                       summary=t["summary"], url=f"https://clinicaltrials.gov/study/{t['nct']}")
            edge(sid, d["id"], "STUDIES", "ClinicalTrials.gov", 1, match_reason=t["why"])
            for i in t["interventions"]:
                if i["type"] not in DRUG_TYPES or PLACEBO.search(i["name"]):
                    continue
                display = norm_intervention(i["name"])
                if len(display) < 3:
                    continue
                if display.islower():
                    display = display.capitalize()
                iid = node(f"INT:{slug(display)}", "Intervention", name=display,
                           intervention_type=i["type"].lower())
                if not any(x["id"] == f"TESTS:{sid}->{iid}" for x in edges):
                    edge(sid, iid, "TESTS", "ClinicalTrials.gov", 1)
        print(f"  trials: {len(trials)}")

        # Patient organisations (NORD) and communities (RareConnect)
        orgs, nord_note = nord_orgs(d)
        for o in orgs:
            oid = node(f"ORG:nord:{slug(o['name'])}", "PatientOrg", name=o["name"], url=o.get("website") or o.get("nord_url"),
                       nord_url=o.get("nord_url"), description=(o.get("description") or "")[:700],
                       org_kind="Patient organisation", directory="NORD")
            edge(d["id"], oid, "REPRESENTED_BY", "NORD", 3, match_reason="listed on the NORD disease report")
        comms = rareconnect_communities(d, sym)
        for c in comms:
            name = c.get("name") or c.get("default_name")
            oid = node(f"ORG:rareconnect:{c['slug']}", "PatientOrg", name=name,
                       url=f"https://www.rareconnect.org/en/community/{c['slug']}",
                       description=(c.get("description") or "")[:700], members=c.get("total_members"),
                       org_kind="Online patient community", directory="RareConnect (EURORDIS)")
            edge(d["id"], oid, "REPRESENTED_BY", "RareConnect", 3, match_reason="community name matches the disease")
        print(f"  patient groups: NORD {len(orgs)} ({nord_note}), RareConnect {len(comms)}")
        if not orgs:
            log.append(f"{label}: no NORD organisations ({nord_note})")

        # GARD id + reading list
        info = gard_info(d)
        if info:
            disease_props[d["id"]] = {
                "gard_id": info.get("gard_id"),
                "reading": [{"pmid": l.get("pmid"), "title": l.get("title"), "year": l.get("year"),
                             "journal": l.get("journal")} for l in (info.get("literature") or [])[:6]],
            }

        if not gene:
            continue

        # NIH funding: grants mentioning the gene; PIs keep their RePORTER profile id
        try:
            grants = grants_for(sym)
        except Exception as e:
            grants = []
            log.append(f"{sym}: NIH RePORTER failed ({type(e).__name__})")
        for p in grants:
            org = p.get("organization") or {}
            gid = node(f"NIH:{p.get('core_project_num') or p.get('project_num')}", "Grant", name=p.get("project_title"),
                       project_num=p.get("project_num"), fiscal_year=p.get("fiscal_year"),
                       award_amount=p.get("award_amount"), institute=(p.get("agency_ic_admin") or {}).get("abbreviation"),
                       organization=org.get("org_name"), city=org.get("org_city"), country=org.get("org_country"),
                       start=(p.get("project_start_date") or "")[:10], end=(p.get("project_end_date") or "")[:10],
                       url=f"https://reporter.nih.gov/project-details/{p.get('appl_id')}")
            edge(gid, gene["id"], "RESEARCHES", "NIH RePORTER", 1, match_reason=f"project text mentions {sym}")
            for pi in p.get("principal_investigators") or []:
                if not pi.get("profile_id"):
                    continue
                rid = node(f"RES:nih:{pi['profile_id']}", "Researcher", name=(pi.get("full_name") or "").title().strip(),
                           identity="NIH RePORTER profile", profile_id=pi["profile_id"], organization=org.get("org_name"))
                if not any(x["id"] == f"LEADS:{rid}->{gid}" for x in edges):
                    edge(rid, gid, "LEADS", "NIH RePORTER", 1)
        print(f"  NIH grants: {len(grants)}")

        # Gene families (HGNC gene groups)
        try:
            groups = gene_groups(sym)
        except Exception as e:
            groups = []
            log.append(f"{sym}: HGNC failed ({type(e).__name__})")
        for gid_num, gname in groups:
            ggid = node(f"HGNC_GROUP:{gid_num}", "GeneGroup", name=gname,
                        url=f"https://www.genenames.org/data/genegroup/#!/group/{gid_num}")
            edge(gene["id"], ggid, "MEMBER_OF", "HGNC", 1, match_reason="HGNC gene group membership")
        print(f"  gene groups: {[n for _, n in groups]}")

    out = {"nodes": list(nodes.values()), "edges": edges, "disease_props": disease_props,
           "meta": {"retrieved": TODAY, "notes": log,
                    "sources": ["ClinicalTrials.gov API v2", "NORD (scraper)", "RareConnect (scraper)",
                                "RARe-SOURCE / GARD (scraper)", "NIH RePORTER API v2", "HGNC REST"]}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {}
    for n in out["nodes"]:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    print(f"\nwrote {OUT}: {counts}, {len(edges)} edges")
    for line in log:
        print("  note:", line)


if __name__ == "__main__":
    sys.exit(main())
