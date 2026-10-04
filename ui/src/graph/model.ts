import Fuse from 'fuse.js'
import type { GEdge, GNode, GraphData, NodeType } from '../types'

export interface Model {
  nodes: Map<string, GNode>
  edges: Map<string, GEdge>
  adj: Map<string, GEdge[]>
  fuse: Fuse<GNode>
}

export function buildModel(data: GraphData): Model {
  const nodes = new Map(data.nodes.map((n) => [n.id, n]))
  const edges = new Map(data.edges.map((e) => [e.id, e]))
  const adj = new Map<string, GEdge[]>()
  for (const e of data.edges) {
    for (const end of [e.source, e.target]) {
      if (!adj.has(end)) adj.set(end, [])
      adj.get(end)!.push(e)
    }
  }
  // Index covers ALL nodes, not just the visible ones, so everything is searchable.
  const fuse = new Fuse(data.nodes, {
    keys: [
      { name: 'name', weight: 3 },
      { name: 'short', weight: 2 },
      { name: 'synonyms', weight: 2 },
      { name: 'aliases', weight: 2 },
      { name: 'full_name', weight: 1.5 },
      { name: 'protein_change', weight: 1.5 },
      { name: 'cdna_change', weight: 1 },
      { name: 'id', weight: 1 },
      { name: 'xrefs', weight: 1 },
      { name: 'statement', weight: 0.5 },
    ],
    threshold: 0.3,
    ignoreLocation: true,
  })
  return { nodes, edges, adj, fuse }
}

export const other = (e: GEdge, id: string) => (e.source === id ? e.target : e.source)

export function neighbours(m: Model, id: string, types?: NodeType[]) {
  return (m.adj.get(id) ?? [])
    .map((e) => ({ edge: e, node: m.nodes.get(other(e, id))! }))
    .filter((x) => x.node && (!types || types.includes(x.node.type)))
}

// iOS system colours: colour carries meaning alone (one hue per node type)
export const TYPE_COLOR: Record<string, string> = {
  Disease: '#f43f6b',
  Gene: '#2f6bff',
  Variant: '#f59f00',
  Phenotype: '#12b886',
  Mechanism: '#8b5cf6',
  Paper: '#64748b',
  Claim: '#94a3b8',
  PatientOrg: '#0ea5b7',
  Registry: '#06b6d4',
  Study: '#6366f1',
  Researcher: '#a16207',
  Intervention: '#0d9488',
  Grant: '#b45309',
  GeneGroup: '#ea580c',
}

export const TYPE_LABEL: Record<string, string> = {
  Disease: 'Disease', Gene: 'Gene', Variant: 'Variant', Phenotype: 'Symptom', Mechanism: 'Mechanism',
  Paper: 'Paper', Claim: 'Claim', PatientOrg: 'Patient group', Registry: 'Registry', Study: 'Study',
  Researcher: 'Researcher', Intervention: 'Treatment studied',
  Grant: 'NIH-funded project', GeneGroup: 'Gene family',
}

// soft background "clouds" per disease cluster
export const CLUSTER_COLOR = ['#ff2d55', '#007aff', '#34c759', '#ff9500', '#af52de', '#5ac8fa']

/** Match score buckets (score 0-100 from schema.all_connections; pairs below 20 are not exported). */
export const STRENGTH_CUTOFFS = { strong: 30, moderate: 24 }
export const strengthOf = (score: number) =>
  score >= STRENGTH_CUTOFFS.strong ? 'strong' : score >= STRENGTH_CUTOFFS.moderate ? 'moderate' : 'weak'

const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s)

export function nodeLabel(n: GNode): string {
  if (n.type === 'Variant') return (n.protein_change as string) || (n.cdna_change as string) || n.name
  if (n.type === 'Disease') {
    // Short, family-friendly bubble label; the gene symbol disambiguates the many
    // "developmental and epileptic encephalopathy, N" entries. Full name lives in the card.
    if (n.name.length <= 22) return n.name
    const abbr = ((n.synonyms as string[]) ?? []).find((s) => /^[A-Z0-9-]{3,10}$/.test(s))
    if (n.short) return abbr ? `${n.short} · ${abbr}` : `${n.short}-related`
    return n.name.slice(0, 22) + '…'
  }
  if (n.type === 'Paper' || n.type === 'Study' || n.type === 'Grant') return clip(n.name, 34)
  if (n.type === 'GeneGroup') return clip(n.name.replace(/^Glutamate ionotropic receptor /, ''), 30)
  if (n.type === 'Claim') return clip(n.name, 40)
  return n.name
}

export const titleCase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** Second line under a node / in lists. */
export function nodeSubtitle(n: GNode, m?: Model): string {
  if (n.type === 'Disease') return n.short ? `${n.short} gene` : ''
  if (n.type === 'Gene') {
    const v = m ? neighbours(m, n.id, ['Variant']).length : 0
    return v ? `${v} variants` : String(n.full_name ?? '')
  }
  if (n.type === 'Variant') return String(n.classification ?? '')
  if (n.type === 'Paper') return String(n.source_id ?? n.id)
  return ''
}

/** Outbound links to the authoritative source for a node, so the jury can verify. */
export function externalLinks(n: GNode): { label: string; url: string }[] {
  const out: { label: string; url: string }[] = []
  const add = (label: string, url: string) => out.push({ label, url })
  if (n.type === 'Disease') {
    add('MONDO', `https://monarchinitiative.org/${n.id}`)
    for (const x of (n.xrefs as string[]) ?? []) {
      const [db, id] = x.split(':')
      if (db === 'OMIM') add('OMIM', `https://omim.org/entry/${id}`)
      else if (db === 'MEDGEN') add('MedGen', `https://www.ncbi.nlm.nih.gov/medgen/${id}`)
      else if (db === 'DOID') add('Disease Ontology', `https://disease-ontology.org/?id=${x}`)
      else if (db === 'ORPHA' || db === 'Orphanet') add('Orphanet', `https://www.orpha.net/en/disease/detail/${id}`)
    }
  } else if (n.type === 'Gene') {
    if (n.hgnc_id) add('HGNC', `https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/${n.hgnc_id}`)
    if (n.entrez_id) add('NCBI Gene', `https://www.ncbi.nlm.nih.gov/gene/${n.entrez_id}`)
  } else if (n.type === 'Variant') {
    const acc = n.id.replace('CLINVAR:', '')
    if (acc.startsWith('VCV')) add('ClinVar', `https://www.ncbi.nlm.nih.gov/clinvar/variation/${parseInt(acc.slice(3), 10)}/`)
  } else if (n.type === 'Phenotype') {
    add('HPO', `https://hpo.jax.org/browse/term/${n.id}`)
  } else if (n.type === 'Paper' && n.id.startsWith('PMID:')) {
    add('PubMed', `https://pubmed.ncbi.nlm.nih.gov/${n.id.slice(5)}/`)
  } else if (n.type === 'PatientOrg' || n.type === 'Registry') {
    if (n.url) add('Website', n.url as string)
    if (n.nord_url && n.nord_url !== n.url) add('NORD profile', n.nord_url as string)
  } else if (n.type === 'Study' && n.url) {
    add('ClinicalTrials.gov', n.url as string)
  } else if (n.type === 'Grant' && n.url) {
    add('NIH RePORTER', n.url as string)
  } else if (n.type === 'GeneGroup' && n.url) {
    add('HGNC gene group', n.url as string)
  }
  return out
}
