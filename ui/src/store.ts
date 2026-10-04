import { create } from 'zustand'
import type { Model } from './graph/model'
import { neighbours, other } from './graph/model'
import type { LensId } from './graph/lens'

export type Selection = { kind: 'node' | 'edge'; id: string } | null

export const DEFAULT_MIN_SIM = 24 // DISEASE_MATCH score (0-100)

/** One step of card navigation: what was selected and which nodes were on the map. */
type Snapshot = { selected: Selection; visible: Set<string> }
const MAX_HISTORY = 60

interface State {
  model: Model | null
  visible: Set<string>
  seeds: Set<string>
  selected: Selection
  history: Snapshot[]          // back stack; the bottom entry is the map before any card was opened
  minSim: number
  showBridges: boolean
  setShowBridges: (v: boolean) => void
  lens: LensId | null          // overview: diseases connected through one kind of link only
  lensSharedOnly: boolean
  setLens: (l: LensId | null) => void
  setLensSharedOnly: (v: boolean) => void
  focusTick: number
  layoutTick: number
  setModel: (m: Model) => void
  select: (s: Selection) => void
  openNode: (id: string) => void
  back: () => void
  close: () => void
  setMinSim: (v: number) => void
  addNodes: (ids: string[]) => void
  toggleNodes: (ids: string[]) => void
  expand: (id: string) => void
  collapse: (id: string) => void
  showVariants: (geneId: string) => void
  reveal: (id: string) => void
  reset: () => void
}

// Detail types never appear implicitly (there can be hundreds); they are added on request from a card.
const DETAIL = new Set(['Phenotype', 'Variant', 'Claim', 'Researcher', 'Intervention', 'Study', 'Grant', 'PatientOrg'])
const expandable = (m: Model, id: string) =>
  neighbours(m, id).filter((x) => !DETAIL.has(x.node.type)).map((x) => x.node.id)

/** Start view: every disease with its gene(s), pipeline papers, mechanisms and shared gene families. */
const seedSet = (m: Model) => {
  const s = new Set<string>()
  for (const n of m.nodes.values()) {
    if (n.type !== 'Disease' || n.paper_scoped) continue // paper-only names are not real diseases
    s.add(n.id)
    neighbours(m, n.id, ['Gene']).forEach((g) => s.add(g.node.id))
    // mechanisms shared by 2+ diseases are the cross-disease story; disease-specific ones appear on tap
    neighbours(m, n.id, ['Mechanism']).forEach((x) => {
      if (new Set(neighbours(m, x.node.id, ['Disease']).map((d) => d.node.id)).size > 1) s.add(x.node.id)
    })
    // papers that were read by the pipeline; papers only cited as mechanism evidence stay in the cards
    neighbours(m, n.id, ['Paper']).forEach((p) => { if (p.node.role !== 'mechanism evidence') s.add(p.node.id) })
    // gene families shared by 2+ mapped genes make 'different names, same receptor' visible from the start
    neighbours(m, n.id, ['Gene']).forEach((g) => neighbours(m, g.node.id, ['GeneGroup']).forEach((x) => {
      if (neighbours(m, x.node.id, ['Gene']).length > 1) s.add(x.node.id)
    }))
  }
  return s
}

export const useStore = create<State>((set, get) => {
  /** Remember the current step so `back` can return to it (and drop whatever the next step adds). */
  const push = () => {
    const { selected, visible, history } = get()
    set({ history: [...history, { selected, visible }].slice(-MAX_HISTORY) })
  }
  const bump = () => get().layoutTick + 1

  return {
    model: null,
    visible: new Set(),
    seeds: new Set(),
    selected: null,
    history: [],
    minSim: DEFAULT_MIN_SIM,
    showBridges: false,  // the shared-asset lines are one click away (toggle or lens)
    setShowBridges: (showBridges) => set({ showBridges }),
    lens: null,
    lensSharedOnly: true,
    setLens: (lens) => set({ lens, selected: null, history: [], layoutTick: bump() }),
    setLensSharedOnly: (lensSharedOnly) => set({ lensSharedOnly, layoutTick: bump() }),
    focusTick: 0,
    layoutTick: 0,

    setModel: (m) => {
      const seeds = seedSet(m)
      set({ model: m, seeds, visible: new Set(seeds) })
    },

    /** Navigate to another card (or close with null). */
    select: (selected) => {
      if (!selected) return get().close()
      const cur = get().selected
      if (cur && cur.kind === selected.kind && cur.id === selected.id) return
      push()
      set({ selected })
    },

    /** Tap on a map node: open its card and show its structural neighbours. */
    openNode: (id) => {
      const { model, visible, selected } = get()
      if (!model) return
      if (selected?.kind === 'node' && selected.id === id) return
      push()
      const next = new Set(visible)
      expandable(model, id).forEach((n) => next.add(n))
      set({ selected: { kind: 'node', id }, visible: next, layoutTick: bump() })
    },

    back: () => {
      const { history } = get()
      if (!history.length) return
      const prev = history[history.length - 1]
      set({ selected: prev.selected, visible: prev.visible, history: history.slice(0, -1), layoutTick: bump() })
      if (!prev.selected) set({ history: [] })
    },

    /** Close the card: the map returns to how it was before the first card was opened. */
    close: () => {
      const { history } = get()
      const base = history.length ? history[0].visible : get().visible
      set({ selected: null, visible: base, history: [], layoutTick: bump() })
    },

    setMinSim: (minSim) => set({ minSim }),

    addNodes: (ids) => {
      push()
      const next = new Set(get().visible)
      ids.forEach((i) => next.add(i))
      set({ visible: next, layoutTick: bump() })
    },

    /** "Show on map" / "Hide from map": the same button adds or removes a set of nodes. */
    toggleNodes: (ids) => {
      const { visible, seeds, selected } = get()
      const shown = ids.length > 0 && ids.every((i) => visible.has(i))
      push()
      const next = new Set(visible)
      if (shown) ids.forEach((i) => { if (!seeds.has(i) && i !== selected?.id) next.delete(i) })
      else ids.forEach((i) => next.add(i))
      set({ visible: next, layoutTick: bump() })
    },

    expand: (id) => {
      const { model } = get()
      if (model) get().addNodes(expandable(model, id))
    },

    collapse: (id) => {
      const { model, visible, seeds } = get()
      if (!model) return
      push()
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
      set({ visible: next, layoutTick: bump() })
    },

    showVariants: (geneId) => {
      const { model } = get()
      if (model) get().toggleNodes(neighbours(model, geneId, ['Variant']).map((x) => x.node.id))
    },

    /** Make any node visible (e.g. from search) together with enough context to connect it. */
    reveal: (id) => {
      const { model, visible, lens } = get()
      if (!model) return
      const n = model.nodes.get(id)!
      if (lens) set({ history: [] })  // leaving an overview starts a fresh trail on the full map
      push()
      const next = new Set(lens ? get().seeds : visible)
      next.add(id)
      if (n.type === 'Variant') {
        for (const x of neighbours(model, id, ['Gene'])) next.add(x.node.id)
      } else {
        expandable(model, id).forEach((x) => next.add(x))
        if (n.type === 'Phenotype') neighbours(model, id, ['Disease']).forEach((d) => next.add(d.node.id))
      }
      // never leave a revealed node floating alone: if nothing around it is visible, show its direct links
      if (!neighbours(model, id).some((x) => next.has(x.node.id))) {
        neighbours(model, id).slice(0, 12).forEach((x) => next.add(x.node.id))
      }
      set({ lens: null, visible: next, selected: { kind: 'node', id }, focusTick: get().focusTick + 1, layoutTick: bump() })
    },

    reset: () => {
      const { model } = get()
      if (!model) return
      const seeds = seedSet(model)
      set({ visible: new Set(seeds), seeds, selected: null, history: [], minSim: DEFAULT_MIN_SIM, lens: null, layoutTick: bump() })
    },
  }
})
