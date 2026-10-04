import type { Model } from './model'
import { neighbours } from './model'

/**
 * Connection layers. Each layer is one kind of connection between diseases (shared symptoms, a shared
 * drug, a shared patient group, ...). Active layers are added onto the current map:
 *  - every layer draws its own typed line between two diseases, so you always see what a link is based on
 *  - mechanism and gene-family layers also put their (few) hub bubbles on the map
 *  - all active layers together decide how close two diseases sit (combined strength)
 */
export type LensId = 'symptoms' | 'family' | 'mechanism' | 'treatments' | 'trials' | 'researchers' | 'groups' | 'papers'

export interface LensDef {
  id: LensId; label: string; hubType: string; hint: string
  color: string; dash: 'solid' | 'dashed' | 'dotted'; noun: [string, string]; hubs?: boolean
}

export const LENSES: LensDef[] = [
  { id: 'symptoms', label: 'Similar symptoms', hubType: 'Phenotype', color: '#f43f6b', dash: 'solid', noun: ['symptom', 'symptoms'],
    hint: 'Disease matches from shared HPO symptoms (match score).' },
  { id: 'mechanism', label: 'Mechanism', hubType: 'Mechanism', color: '#8b5cf6', dash: 'solid', noun: ['mechanism', 'mechanisms'], hubs: true,
    hint: 'Shared loss/gain of function or biological process, with quoted evidence.' },
  { id: 'family', label: 'Gene family', hubType: 'GeneGroup', color: '#ea580c', dash: 'solid', noun: ['gene family', 'gene families'], hubs: true,
    hint: 'Different gene names that build the same kind of protein (HGNC).' },
  { id: 'treatments', label: 'Treatments studied', hubType: 'Intervention', color: '#0d9488', dash: 'dashed', noun: ['drug', 'drugs'],
    hint: 'The same drug tested in trials or papers for both diseases.' },
  { id: 'trials', label: 'Trials & registries', hubType: 'Study', color: '#6366f1', dash: 'dashed', noun: ['study', 'studies'],
    hint: 'A study that already includes both diseases.' },
  { id: 'researchers', label: 'Funded researchers', hubType: 'Researcher', color: '#a16207', dash: 'dotted', noun: ['researcher', 'researchers'],
    hint: 'NIH-funded investigators working on both genes.' },
  { id: 'groups', label: 'Patient groups', hubType: 'PatientOrg', color: '#0891b2', dash: 'dotted', noun: ['group', 'groups'],
    hint: 'Organisations supporting both diseases (general rare-disease alliances excluded).' },
  { id: 'papers', label: 'Papers', hubType: 'Paper', color: '#64748b', dash: 'dotted', noun: ['paper', 'papers'],
    hint: 'Papers linked to both diseases.' },
]
export const lensDef = (id: LensId) => LENSES.find((l) => l.id === id)!

/** Patient-group sub-filters (organisation focus, see enrich.py). */
export const GROUP_FOCUS = ['Disease-specific', 'Epilepsy', 'Autism', 'Children & disability'] as const

export interface Contribution { mode: LensId; strength: number; items: { id: string; name: string }[] }

const diseasesOf = (m: Model) => [...m.nodes.values()].filter((n) => n.type === 'Disease' && !n.paper_scoped)
export const pairKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`)

/** hub id -> { disease id -> how they are connected } for one layer. */
export function hubLinks(m: Model, lens: LensId, groupFocus: readonly string[] = GROUP_FOCUS): Map<string, Map<string, string>> {
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
      // patient groups are bundled per focus ("Epilepsy groups") so dozens of organisations become one bubble;
      // a disease joins a bundle only through organisations it shares with another disease
      neighbours(m, d.id, ['PatientOrg']).forEach((x) => {
        if (x.node.scope === 'umbrella' || x.node.scope === 'specific') return
        const focus = String(x.node.focus ?? 'Disease-specific')
        if (!groupFocus.includes(focus)) return
        add(`ORGSET:${focus}`, d.id, x.node.name)
      })
    } else if (lens === 'papers') {
      neighbours(m, d.id, ['Paper']).forEach((x) => add(x.node.id, d.id, String(x.edge.link_reason ?? 'linked paper')))
    }
  }
  return links
}

/** Hubs of a layer that connect 2+ diseases (what a hub layer puts on the map). */
export const sharedHubs = (m: Model, lens: LensId, groupFocus?: readonly string[]) =>
  [...hubLinks(m, lens, groupFocus)].filter(([, ds]) => ds.size > 1).map(([hub]) => hub)

/** Per-layer strength (0..1) for every disease pair, with the items that create it. */
export function modePairs(m: Model, mode: LensId, groupFocus?: readonly string[]): Map<string, Contribution> {
  const out = new Map<string, Contribution>()
  if (mode === 'symptoms') {
    for (const e of m.edges.values()) {
      if (e.rel !== 'DISEASE_MATCH') continue
      const items = ((e.informative_phenotypes as string[]) ?? []).slice(0, 4).map((name) => ({ id: e.id, name }))
      out.set(pairKey(e.source, e.target), { mode, strength: Math.min(1, (e.score as number) / 40), items })
    }
    return out
  }
  const items = new Map<string, { id: string; name: string }[]>()
  for (const [hub, ds] of hubLinks(m, mode, groupFocus)) {
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

export function modeCounts(m: Model, groupFocus?: readonly string[]): Record<LensId, number> {
  const out = {} as Record<LensId, number>
  for (const l of LENSES) out[l.id] = modePairs(m, l.id, groupFocus).size
  return out
}

/** All contributions per disease pair for the active layers. */
export function pairLayers(m: Model, layers: readonly LensId[], minScore: number, groupFocus?: readonly string[]) {
  const pairs = new Map<string, Contribution[]>()
  for (const mode of layers) {
    for (const [k, c] of modePairs(m, mode, groupFocus)) {
      if (mode === 'symptoms' && c.strength * 40 < minScore) continue
      if (!pairs.has(k)) pairs.set(k, [])
      pairs.get(k)!.push(c)
    }
  }
  return pairs
}

/** Combined strength across layers: every additional shared layer brings the diseases closer. */
export const combined = (cs: Contribution[]) => 1 - cs.reduce((p, c) => p * (1 - 0.85 * c.strength), 1)

export const describe = (c: Contribution) => {
  const d = lensDef(c.mode)
  if (c.mode === 'symptoms') return `similar symptoms (${Math.round(c.strength * 40)})`
  const n = c.items.length
  return n === 1 ? `${d.noun[0]}: ${c.items[0].name}` : `${n} ${d.noun[1]}`
}

/** Synthetic bubbles for the patient-group bundles (one per focus), added to the model once. */
export function addOrgSets(m: Model) {
  const byFocus = new Map<string, string[]>()
  for (const n of m.nodes.values()) {
    if (n.type !== 'PatientOrg' || n.scope === 'umbrella' || n.scope === 'specific') continue
    const f = String(n.focus ?? 'Disease-specific')
    if (!byFocus.has(f)) byFocus.set(f, [])
    byFocus.get(f)!.push(n.id)
  }
  for (const [f, members] of byFocus) {
    const id = `ORGSET:${f}`
    const label = f === 'Disease-specific' ? 'Gene-specific groups' : f === 'Children & disability' ? 'Disability groups' : `${f} groups`
    m.nodes.set(id, { id, type: 'PatientOrg', name: `${label} · ${members.length}`, members, org_set: true, focus: f, source_local: true })
  }
}
