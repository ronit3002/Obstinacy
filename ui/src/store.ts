import { create } from 'zustand'
import type { Model } from './graph/model'
import { neighbours, other } from './graph/model'

export type Selection = { kind: 'node' | 'edge'; id: string } | null

export const DEFAULT_MIN_SIM = 24 // DISEASE_MATCH score (0-100)

interface State {
  model: Model | null
  visible: Set<string>
  seeds: Set<string>
  selected: Selection
  minSim: number
  focusTick: number
  layoutTick: number
  setModel: (m: Model) => void
  select: (s: Selection) => void
  setMinSim: (v: number) => void
  addNodes: (ids: string[]) => void
  expand: (id: string) => void
  collapse: (id: string) => void
  showVariants: (geneId: string) => void
  reveal: (id: string) => void
  reset: () => void
}

// Phenotypes and variants are detail, not structure: they never appear implicitly
// (hundreds of them). They are added on request from a card, or to explain a similarity.
const DETAIL = new Set(['Phenotype', 'Variant', 'Claim', 'Researcher', 'Intervention'])
const expandable = (m: Model, id: string) =>
  neighbours(m, id).filter((x) => !DETAIL.has(x.node.type)).map((x) => x.node.id)

/** Start view: every disease with its gene(s) and linked papers. */
const seedSet = (m: Model) => {
  const s = new Set<string>()
  for (const n of m.nodes.values()) {
    if (n.type !== 'Disease') continue
    s.add(n.id)
    neighbours(m, n.id, ['Gene', 'Paper']).forEach((g) => s.add(g.node.id))
  }
  return s
}

export const useStore = create<State>((set, get) => ({
  model: null,
  visible: new Set(),
  seeds: new Set(),
  selected: null,
  minSim: DEFAULT_MIN_SIM,
  focusTick: 0,
  layoutTick: 0,

  setModel: (m) => {
    const seeds = seedSet(m)
    set({ model: m, seeds, visible: new Set(seeds) })
  },

  select: (selected) => set({ selected }),
  setMinSim: (minSim) => set({ minSim }),

  addNodes: (ids) => {
    const next = new Set(get().visible)
    ids.forEach((i) => next.add(i))
    set({ visible: next, layoutTick: get().layoutTick + 1 })
  },

  expand: (id) => {
    const { model } = get()
    if (model) get().addNodes(expandable(model, id))
  },

  collapse: (id) => {
    const { model, visible, seeds } = get()
    if (!model) return
    const next = new Set(visible)
    for (const n of neighbours(model, id)) {
      const nid = n.node.id
      if (seeds.has(nid)) continue
      // keep nodes that are still connected to something else that is visible
      const still = (model.adj.get(nid) ?? []).some((e) => {
        const o = other(e, nid)
        return o !== id && next.has(o)
      })
      if (!still) next.delete(nid)
    }
    set({ visible: next, layoutTick: get().layoutTick + 1 })
  },

  showVariants: (geneId) => {
    const { model } = get()
    if (model) get().addNodes(neighbours(model, geneId, ['Variant']).map((x) => x.node.id))
  },

  /** Make any node visible (e.g. from search) together with enough context to connect it. */
  reveal: (id) => {
    const { model, visible } = get()
    if (!model) return
    const n = model.nodes.get(id)!
    const next = new Set(visible)
    next.add(id)
    if (n.type === 'Variant') {
      for (const x of neighbours(model, id, ['Gene'])) next.add(x.node.id)
    } else {
      expandable(model, id).forEach((x) => next.add(x))
      if (n.type === 'Phenotype') neighbours(model, id, ['Disease']).forEach((d) => next.add(d.node.id))
    }
    set({
      visible: next,
      selected: { kind: 'node', id },
      focusTick: get().focusTick + 1,
      layoutTick: get().layoutTick + 1,
    })
  },

  reset: () => {
    const { model } = get()
    if (!model) return
    const seeds = seedSet(model)
    set({ visible: new Set(seeds), seeds, selected: null, minSim: DEFAULT_MIN_SIM,
          layoutTick: get().layoutTick + 1 })
  },
}))
