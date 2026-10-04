import type { Model } from './model'
import { neighbours } from './model'
import type { GNode } from '../types'

/**
 * Connection lenses: an overview with only the diseases plus the "hub" entities of one kind that
 * connect them (a gene family, a drug, a trial, a researcher, ...). Edges are derived:
 * disease -- hub, with `via` saying how (e.g. through which trial a drug is tested).
 */
export type LensId = 'symptoms' | 'family' | 'mechanism' | 'treatments' | 'trials' | 'researchers' | 'groups' | 'papers'

export interface LensDef { id: LensId; label: string; hubType: string; hint: string }

export const LENSES: LensDef[] = [
  { id: 'family', label: 'Gene family', hubType: 'GeneGroup', hint: 'Different gene names that build the same kind of protein (HGNC).' },
  { id: 'treatments', label: 'Treatments studied', hubType: 'Intervention', hint: 'The same drug tested in trials or papers for several diseases.' },
  { id: 'trials', label: 'Trials & registries', hubType: 'Study', hint: 'One study that already includes several diseases.' },
  { id: 'researchers', label: 'Funded researchers', hubType: 'Researcher', hint: 'NIH-funded investigators working on several of the genes.' },
  { id: 'groups', label: 'Patient groups', hubType: 'PatientOrg', hint: 'Organisations and communities that support several diseases.' },
  { id: 'papers', label: 'Papers', hubType: 'Paper', hint: 'Papers linked to the diseases.' },
  { id: 'mechanism', label: 'Mechanism', hubType: 'Mechanism', hint: 'Quoted loss- or gain-of-function evidence.' },
  { id: 'symptoms', label: 'Similar symptoms', hubType: 'Disease', hint: 'Disease matches from shared HPO symptoms (match score).' },
]

export interface LensEdge { id: string; source: string; target: string; via: string; real?: boolean; score?: number }
export interface LensView { nodes: Set<string>; edges: LensEdge[]; hubs: number; unconnected: GNode[] }

const diseasesOf = (m: Model) => [...m.nodes.values()].filter((n) => n.type === 'Disease' && !n.paper_scoped)

/** hub id -> { disease id -> how they are connected } */
function hubLinks(m: Model, lens: LensId): Map<string, Map<string, string>> {
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
      neighbours(m, d.id, ['PatientOrg']).forEach((x) => add(x.node.id, d.id, String(x.node.directory ?? 'directory')))
    } else if (lens === 'papers') {
      neighbours(m, d.id, ['Paper']).forEach((x) => add(x.node.id, d.id, String(x.edge.link_reason ?? 'linked paper')))
    }
  }
  return links
}

export function lensCounts(m: Model): Record<LensId, number> {
  const out = {} as Record<LensId, number>
  for (const l of LENSES) {
    if (l.id === 'symptoms') {
      out[l.id] = [...m.edges.values()].filter((e) => e.rel === 'DISEASE_MATCH').length
      continue
    }
    out[l.id] = [...hubLinks(m, l.id).values()].filter((ds) => ds.size > 1).length
  }
  return out
}

export function lensView(m: Model, lens: LensId, sharedOnly: boolean, minScore: number): LensView {
  const diseases = diseasesOf(m)
  const nodes = new Set(diseases.map((d) => d.id))
  const edges: LensEdge[] = []
  const connected = new Set<string>()
  let hubs = 0

  if (lens === 'symptoms') {
    for (const e of m.edges.values()) {
      if (e.rel !== 'DISEASE_MATCH' || (e.score as number) < minScore) continue
      edges.push({ id: e.id, source: e.source, target: e.target, via: String(e.connection_label), real: true, score: e.score as number })
      connected.add(e.source); connected.add(e.target)
      hubs++
    }
  } else {
    for (const [hub, ds] of hubLinks(m, lens)) {
      if (sharedOnly && ds.size < 2) continue
      nodes.add(hub)
      hubs++
      for (const [d, via] of ds) {
        edges.push({ id: `LENS:${hub}:${d}`, source: d, target: hub, via })
        if (ds.size > 1) connected.add(d)
      }
    }
  }
  return { nodes, edges, hubs, unconnected: diseases.filter((d) => !connected.has(d.id)) }
}
