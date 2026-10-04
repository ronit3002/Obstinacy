import { create } from 'zustand'
import type { Model } from './graph/model'
import { neighbours, other } from './graph/model'
import type { LensId, ModeWeights } from './graph/lens'

export type Selection = { kind: 'node' | 'edge'; id: string } | null

export const DEFAULT_MIN_SIM = 24 // DISEASE_MATCH score (0-100)

/** One step of card navigation: what was selected and which nodes were on the map. */
type Snapshot = { selected: Selection; visible: Set<string>; modes: ModeWeights; showHubs: boolean }
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
  modes: ModeWeights           // active connection modes and their weights (empty = full map)
  showHubs: boolean            // in the connection view, also draw the connecting drugs, trials, ...
  toggleMode: (l: LensId) => void
  setModeWeight: (l: LensId, w: number) => void
  clearModes: () => void
  setShowHubs: (v: boolean) => void
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

/** Start view: only the diseases. Genes, mechanisms and the rest appear when a disease is opened. */
const seedSet = (m: Model) => {
  const s = new Set<string>()
  for (const n of m.nodes.values()) {
    if (n.type !== 'Disease' || n.paper_scoped) continue // paper-only names are not real diseases
    s.add(n.id)
  }
  return s
}

export const useStore = create<State>((set, get) => {
  /** Remember the current step so `back` can return to it (and drop whatever the next step adds). */
  const push = () => {
    const { selected, visible, history, modes, showHubs } = get()
    set({ history: [...history, { selected, visible, modes, showHubs }].slice(-MAX_HISTORY) })
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
    modes: {},
    showHubs: false,
    toggleMode: (l) => {
      const modes = { ...get().modes }
      if (modes[l]) delete modes[l]
      else modes[l] = 0.5
      set({ modes, selected: null, history: [], layoutTick: bump() })
    },
    setModeWeight: (l, w) => set({ modes: { ...get().modes, [l]: w }, layoutTick: bump() }),
    clearModes: () => set({ modes: {}, selected: null, history: [], layoutTick: bump() }),
    setShowHubs: (showHubs) => set({ showHubs, layoutTick: bump() }),
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
      const { model } = get()
      let visible = prev.visible
      // the card we return to must be on the map, whatever view it was opened from
      const sel = prev.selected
      if (model && sel?.kind === 'node' && !Object.keys(prev.modes).length && !visible.has(sel.id)) {
        visible = new Set(visible)
        visible.add(sel.id)
        neighbours(model, sel.id).slice(0, 12).forEach((x) => visible.add(x.node.id))
      }
      set({ selected: sel, visible, modes: prev.modes, showHubs: prev.showHubs, history: history.slice(0, -1),
            focusTick: get().focusTick + 1, layoutTick: bump() })
      if (!sel) set({ history: [] })
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
      const { model, visible, modes } = get()
      if (!model) return
      const n = model.nodes.get(id)!
      const fromOverview = Object.keys(modes).length > 0
      push()  // the snapshot keeps the overview, so Back returns to it
      const next = new Set(fromOverview ? get().seeds : visible)
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
      set({ modes: {}, visible: next, selected: { kind: 'node', id }, focusTick: get().focusTick + 1, layoutTick: bump() })
    },

    reset: () => {
      const { model } = get()
      if (!model) return
      const seeds = seedSet(model)
      set({ visible: new Set(seeds), seeds, selected: null, history: [], minSim: DEFAULT_MIN_SIM, modes: {}, layoutTick: bump() })
    },
  }
})
