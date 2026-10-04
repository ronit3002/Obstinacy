import type { Model } from './model'
import { neighbours } from './model'
import type { GNode } from '../types'

/**
 * Connection modes: an overview with only the diseases, linked by the kinds of connection the user
 * switches on. Each mode gives every disease pair a strength in 0..1; the user's weights blend the
 * active modes into one link strength, which drives line width and how close diseases sit.
 * Optionally the connecting "hub" entities (the drug, trial, family, ...) are drawn too.
 */
export type LensId = 'symptoms' | 'family' | 'mechanism' | 'treatments' | 'trials' | 'researchers' | 'groups' | 'papers'

export interface LensDef { id: LensId; label: string; hubType: string; hint: string }

export const LENSES: LensDef[] = [
  { id: 'symptoms', label: 'Similar symptoms', hubType: 'Phenotype', hint: 'Disease matches from shared HPO symptoms (match score).' },
  { id: 'mechanism', label: 'Mechanism', hubType: 'Mechanism', hint: 'Shared loss/gain of function or biological process, with quoted evidence.' },
  { id: 'family', label: 'Gene family', hubType: 'GeneGroup', hint: 'Different gene names that build the same kind of protein (HGNC).' },
  { id: 'treatments', label: 'Treatments studied', hubType: 'Intervention', hint: 'The same drug tested in trials or papers for several diseases.' },
  { id: 'trials', label: 'Trials & registries', hubType: 'Study', hint: 'One study that already includes several diseases.' },
  { id: 'researchers', label: 'Funded researchers', hubType: 'Researcher', hint: 'NIH-funded investigators working on several of the genes.' },
  { id: 'groups', label: 'Patient groups', hubType: 'PatientOrg', hint: 'Organisations supporting several diseases (general rare-disease alliances excluded).' },
  { id: 'papers', label: 'Papers', hubType: 'Paper', hint: 'Papers linked to several of the diseases.' },
]

export type ModeWeights = Partial<Record<LensId, number>>  // active modes -> weight 0..1

export interface Contribution { mode: LensId; strength: number; items: { id: string; name: string }[] }
export interface NetEdge { id: string; source: string; target: string; strength: number; contributions: Contribution[] }
export interface LensEdge { id: string; source: string; target: string; via: string; color?: string }
export interface NetworkView {
  nodes: Set<string>; netEdges: NetEdge[]; hubEdges: (LensEdge & { mode: LensId })[]; unconnected: GNode[]
}

const diseasesOf = (m: Model) => [...m.nodes.values()].filter((n) => n.type === 'Disease' && !n.paper_scoped)
const pairKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`)

/** hub id -> { disease id -> how they are connected } for one mode. */
export function hubLinks(m: Model, lens: LensId): Map<string, Map<string, string>> {
  const links = new Map<string, Map<string, string>>()
  const add = (hub: string, disease: string, via: string) => {
    if (!links.has(hub)) links.set(hub, new Map())
    if (!links.get(hub)!.has(disease)) links.get(hub)!.set(disease, via)
  }
  for (const d of diseasesOf(m)) {
    const genes = neighbours(m, d.id, ['Gene']).map((x) => x.node)
    if (lens === 'family') {
      genes.forEach((g) => neighbours(m, g.id, ['GeneGroup']).forEach((f) => add(f.node.id, d.id, `via ${g.name}`)))
    } else if (lens === 'mechanism') {
      neighbours(m, d.id, ['Mechanism']).forEach((x) => add(x.node.id, d.id, 'quoted paper evidence'))
    } else if (lens === 'trials') {
      neighbours(m, d.id, ['Study']).forEach((x) => add(x.node.id, d.id, String(x.edge.match_reason ?? 'listed condition')))
    } else if (lens === 'treatments') {
      neighbours(m, d.id, ['Study']).forEach((s) =>
        neighbours(m, s.node.id, ['Intervention']).forEach((i) => add(i.node.id, d.id, `trial ${String(s.node.nct ?? '')}`)))
      neighbours(m, d.id, ['Paper']).forEach((p) =>
        neighbours(m, p.node.id, ['Claim']).forEach((c) =>
          neighbours(m, c.node.id, ['Intervention']).forEach((i) => add(i.node.id, d.id, `paper ${String(p.node.source_id ?? '')}`))))
    } else if (lens === 'researchers') {
      genes.forEach((g) => neighbours(m, g.id, ['Grant']).forEach((gr) =>
        neighbours(m, gr.node.id, ['Researcher']).forEach((r) => add(r.node.id, d.id, `NIH project on ${g.name}`))))
    } else if (lens === 'groups') {
      neighbours(m, d.id, ['PatientOrg']).forEach((x) => {
        if (x.node.scope !== 'umbrella') add(x.node.id, d.id, String(x.node.directory ?? 'directory'))
      })
    } else if (lens === 'papers') {
      neighbours(m, d.id, ['Paper']).forEach((x) => add(x.node.id, d.id, String(x.edge.link_reason ?? 'linked paper')))
    }
  }
  return links
}

/** Per-mode strength for every disease pair, with the items that create it. */
function modePairs(m: Model, mode: LensId): Map<string, Contribution> {
  const out = new Map<string, Contribution>()
  if (mode === 'symptoms') {
    for (const e of m.edges.values()) {
      if (e.rel !== 'DISEASE_MATCH') continue
      const s = Math.min(1, (e.score as number) / 40)
      const items = ((e.informative_phenotypes as string[]) ?? []).slice(0, 4).map((name) => ({ id: e.id, name }))
      out.set(pairKey(e.source, e.target), { mode, strength: s, items })
    }
    return out
  }
  const items = new Map<string, { id: string; name: string }[]>()
  for (const [hub, ds] of hubLinks(m, mode)) {
    const list = [...ds.keys()]
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const k = pairKey(list[i], list[j])
        if (!items.has(k)) items.set(k, [])
        items.get(k)!.push({ id: hub, name: m.nodes.get(hub)?.name ?? hub })
      }
    }
  }
  // diminishing returns: one shared item = 0.5, two = 0.75, three = 0.875 ...
  for (const [k, its] of items) out.set(k, { mode, strength: 1 - 0.5 ** its.length, items: its })
  return out
}

export function modeCounts(m: Model): Record<LensId, number> {
  const out = {} as Record<LensId, number>
  for (const l of LENSES) out[l.id] = modePairs(m, l.id).size
  return out
}

export function networkView(m: Model, weights: ModeWeights, showHubs: boolean, minScore: number): NetworkView {
  const diseases = diseasesOf(m)
  const nodes = new Set(diseases.map((d) => d.id))
  const active = (Object.entries(weights) as [LensId, number][]).filter(([, w]) => w > 0)
  const totalW = active.reduce((s, [, w]) => s + w, 0) || 1
  const pairs = new Map<string, Contribution[]>()
  for (const [mode] of active) {
    for (const [k, c] of modePairs(m, mode)) {
      if (mode === 'symptoms' && c.strength * 40 < minScore) continue
      if (!pairs.has(k)) pairs.set(k, [])
      pairs.get(k)!.push(c)
    }
  }
  const netEdges: NetEdge[] = []
  for (const [k, cs] of pairs) {
    const [a, b] = k.split('|')
    const strength = cs.reduce((s, c) => s + (weights[c.mode] ?? 0) * c.strength, 0) / totalW
    if (strength <= 0) continue
    netEdges.push({ id: `NET:${k}`, source: a, target: b, strength, contributions: cs.sort((x, y) => (weights[y.mode] ?? 0) * y.strength - (weights[x.mode] ?? 0) * x.strength) })
  }
  const hubEdges: (LensEdge & { mode: LensId })[] = []
  if (showHubs) {
    for (const [mode] of active) {
      if (mode === 'symptoms') continue
      for (const [hub, ds] of hubLinks(m, mode)) {
        if (ds.size < 2) continue
        nodes.add(hub)
        for (const [d, via] of ds) hubEdges.push({ id: `LENS:${hub}:${d}`, source: d, target: hub, via, mode })
      }
    }
  }
  const connected = new Set(netEdges.flatMap((e) => [e.source, e.target]))
  return { nodes, netEdges, hubEdges, unconnected: diseases.filter((d) => !connected.has(d.id)) }
}

/** Find one combined edge by id (for the detail card). */
export function findNetEdge(m: Model, weights: ModeWeights, minScore: number, id: string): NetEdge | undefined {
  return networkView(m, weights, false, minScore).netEdges.find((e) => e.id === id)
}
