import cytoscape from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { TYPE_ICON } from '../ui/icons'
import { TYPE_COLOR, nodeLabel, nodeSubtitle } from './model'
import { drawBlueprint } from './blueprint'

cytoscape.use(fcose)

/** Diameter in graph units. Nodes are drawn as HTML on top of Cytoscape; Cytoscape only lays out and hit-tests. */
const SIZE: Record<string, number> = { Disease: 64, Gene: 38, Mechanism: 44, GeneGroup: 42, Paper: 34, Study: 30, PatientOrg: 32,
  Grant: 26, Intervention: 28, Phenotype: 16, Variant: 10, Claim: 14, Researcher: 14 }
const sizeOf = (t: string) => SIZE[t] ?? 30

const style: cytoscape.StylesheetJson = [
  { selector: 'node', style: {
      width: 'data(size)', height: 'data(size)', shape: 'ellipse',
      'background-opacity': 0, 'border-width': 0, label: '', 'overlay-opacity': 0 } as never },
  { selector: 'edge', style: {
      width: 1.25, 'line-color': '#c3cbdb', 'curve-style': 'straight', opacity: 0.9, 'overlay-opacity': 0 } as never },
  { selector: 'edge[status="inference"]', style: { 'line-style': 'dashed', 'line-dash-pattern': [5, 5] } as never },
  { selector: 'edge[status="hypothesis"]', style: { 'line-style': 'dotted' } },
  { selector: 'edge[rel="DISEASE_MATCH"]', style: {
      'curve-style': 'unbundled-bezier', 'control-point-distances': [28], 'control-point-weights': [0.5],
      'line-color': '#f43f6b', opacity: 0.28, width: 'mapData(score, 20, 40, 1.25, 5)' as never, 'line-style': 'solid' } as never },
  { selector: 'edge.hi', style: { opacity: 0.85 } },
  { selector: 'edge[rel="DISEASE_MATCH"].hi', style: { opacity: 0.7 } },
  { selector: 'edge[rel="DISEASE_BRIDGE"]', style: {
      'curve-style': 'unbundled-bezier', 'control-point-distances': [-34], 'control-point-weights': [0.5],
      'line-color': '#7c3aed', 'line-style': 'dashed', 'line-dash-pattern': [7, 5], width: 2, opacity: 0.35 } as never },
  { selector: 'edge[rel="DISEASE_BRIDGE"].hi', style: { opacity: 0.8 } },
  { selector: 'edge[rel="MEMBER_OF"]', style: { 'line-color': '#c4b5fd', width: 1.5 } },
  { selector: 'edge[rel="DISCUSSES"]', style: { 'line-color': '#94a3b8', 'line-style': 'dashed', 'line-dash-pattern': [3, 4] } as never },
  { selector: 'edge.faded', style: { opacity: 0.05 } },
  // weak links stay in the layout (so similar diseases still sit closer) but are invisible
  { selector: 'edge.below', style: { opacity: 0, events: 'no' } as never },
  { selector: 'edge.below.hi', style: { opacity: 0.7 } }, // an explicitly selected weak link still shows
]

type NodeEls = { root: HTMLDivElement; bubble: HTMLDivElement; label: HTMLDivElement | null }

export default function GraphView() {
  const box = useRef<HTMLDivElement>(null)
  const grid = useRef<HTMLCanvasElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const els = useRef(new Map<string, NodeEls>())
  const [ids, setIds] = useState<string[]>([])
  const { model, visible, minSim, showBridges, layoutTick, focusTick, selected } = useStore()

  /** Move every HTML node to its Cytoscape position; redraw the warped grid underneath. */
  const place = () => {
    const cy = cyRef.current
    if (!cy) return
    const z = cy.zoom()
    els.current.forEach((e, id) => {
      const n = cy.getElementById(id)
      if (n.empty()) return
      const p = n.renderedPosition()
      const d = sizeOf(n.data('type')) * z
      e.root.style.transform = `translate(${p.x}px, ${p.y}px)`
      e.bubble.style.width = e.bubble.style.height = `${d}px`
      e.bubble.style.marginLeft = e.bubble.style.marginTop = `${-d / 2}px`
      if (e.label) {
        if (n.data('type') === 'Gene') e.label.style.left = `${d / 2 + 7}px` // label to the right
        else e.label.style.top = `${d / 2 + 6}px`
        const t = n.data('type')
        // small or wordy nodes only show their label when zoomed in, hovered or selected
        const minZoom = t === 'Phenotype' || t === 'Variant' ? 0.7 : ['Paper', 'Claim', 'Researcher', 'Study', 'Grant', 'PatientOrg', 'Intervention'].includes(t) ? 1.15 : 0
        e.label.style.opacity = z < minZoom && !e.root.classList.contains('is-selected') && !e.root.classList.contains('is-hover') ? '0' : ''
      }
    })
    if (grid.current) drawBlueprint(grid.current, cy, useStore.getState().selected?.id)
  }

  // create once
  useEffect(() => {
    const cy = cytoscape({ container: box.current, style, minZoom: 0.15, maxZoom: 2.5 })
    cyRef.current = cy
    if (import.meta.env.DEV) (window as unknown as { cy: cytoscape.Core }).cy = cy // console debugging
    cy.on('tap', 'node', (ev) => {
      const id = ev.target.id()
      useStore.getState().select({ kind: 'node', id })
      useStore.getState().expand(id)
    })
    cy.on('tap', 'edge', (ev) => useStore.getState().select({ kind: 'edge', id: ev.target.id() }))
    cy.on('tap', (ev) => { if (ev.target === cy) useStore.getState().select(null) })
    cy.on('mouseover', 'node', (ev) => { els.current.get(ev.target.id())?.root.classList.add('is-hover'); box.current!.style.cursor = 'pointer'; place() })
    cy.on('mouseout', 'node', (ev) => { els.current.get(ev.target.id())?.root.classList.remove('is-hover'); box.current!.style.cursor = ''; place() })
    cy.on('mouseover', 'edge', () => { box.current!.style.cursor = 'pointer' })
    cy.on('mouseout', 'edge', () => { box.current!.style.cursor = '' })
    cy.on('render', place)

    // keep the map framed when the window changes size (until the user starts exploring)
    let userMoved = false
    cy.on('tapstart', () => { userMoved = true })
    box.current!.addEventListener('wheel', () => { userMoved = true }, { passive: true })
    const ro = new ResizeObserver(() => {
      cy.resize()
      if (!userMoved && !useStore.getState().selected && cy.width() > 0) cy.fit(cy.elements(), Math.min(110, cy.width() * 0.1))
      place()
    })
    ro.observe(box.current!)
    return () => { ro.disconnect(); cy.destroy() }
  }, [])

  // sync visible set -> cytoscape elements, then lay out
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !model) return
    const added: string[] = []
    cy.batch(() => {
      cy.nodes().forEach((n) => { if (!visible.has(n.id())) n.remove() })
      for (const id of visible) {
        const n = model.nodes.get(id)!
        if (cy.getElementById(id).nonempty()) continue
        const anchor = (model.adj.get(id) ?? [])
          .map((e) => cy.getElementById(e.source === id ? e.target : e.source))
          .find((x) => x.nonempty())
        const base = anchor?.position() ?? { x: 0, y: 0 }
        cy.add({ group: 'nodes', data: { id, type: n.type, size: sizeOf(n.type) },
          position: { x: base.x + (Math.random() - 0.5) * 80, y: base.y + (Math.random() - 0.5) * 80 } })
        added.push(id)
      }
      for (const id of visible) {
        for (const e of model.adj.get(id) ?? []) {
          if (visible.has(e.source) && visible.has(e.target) && cy.getElementById(e.id).empty()) {
            if (e.rel === 'DISEASE_BRIDGE' && ((e.shared_gene_groups as unknown[]) ?? []).length) continue
            cy.add({ group: 'edges', data: { id: e.id, source: e.source, target: e.target, rel: e.rel,
              status: e.status, score: (e.score as number) ?? 0 } })
          }
        }
      }
    })
    setIds(cy.nodes().map((n) => n.id()))
    if (!added.length) return

    const first = added.length === visible.size
    const layout = cy.layout({ name: 'fcose', animate: false, randomize: false, fit: false,
      nodeRepulsion: () => 32000, nodeSeparation: 150, quality: 'proof', gravity: 0.15,
      // similar diseases pull together (short ideal length), dissimilar ones drift apart
      idealEdgeLength: (e: cytoscape.EdgeSingular) => (e.data('rel') === 'DISEASE_MATCH' ? 540 - 11 * e.data('score') : e.data('rel') === 'DISEASE_BRIDGE' ? 420 : e.data('rel') === 'MEMBER_OF' ? 110 : 80),
      edgeElasticity: (e: cytoscape.EdgeSingular) => (e.data('rel') === 'DISEASE_MATCH' ? 0.2 + e.data('score') / 100 : e.data('rel') === 'DISEASE_BRIDGE' ? 0.12 : 0.6),
    } as never)
    layout.one('layoutstop', () => {
      // genes sit like a satellite at the disease's upper right (the label lives below the bubble)
      cy.nodes('[type="Gene"]').forEach((g) => {
        const parents = g.neighborhood('node[type="Disease"]')
        if (parents.length !== 1 || g.neighborhood('node[type="Variant"]').length) return
        if (g.neighborhood('node[type="GeneGroup"]').some((gg) => gg.neighborhood('node[type="Gene"]').length > 1)) return
        const d = parents[0].position()
        g.position({ x: d.x + 62, y: d.y - 54 })
      })
      // a gene family sits beyond the middle of its member genes, away from the diseases
      cy.nodes('[type="GeneGroup"]').forEach((gg) => {
        const members = gg.neighborhood('node[type="Gene"]')
        if (members.length !== 1) return  // shared families are placed by fcose as the hub of a star
        const m = { x: 0, y: 0 }
        members.forEach((g) => { m.x += g.position().x / members.length; m.y += g.position().y / members.length })
        const ds = members.neighborhood('node[type="Disease"]')
        const dc = { x: 0, y: 0 }
        ds.forEach((d) => { dc.x += d.position().x / ds.length; dc.y += d.position().y / ds.length })
        const vx = m.x - dc.x, vy = m.y - dc.y, len = Math.hypot(vx, vy) || 1
        gg.position(members.length > 1 ? { x: m.x + (vx / len) * 70, y: m.y + (vy / len) * 70 } : { x: m.x + 60, y: m.y - 40 })
      })
      // papers about a single disease sit at its upper left
      cy.nodes('[type="Paper"]').forEach((p) => {
        const parents = p.neighborhood('node[type="Disease"]')
        if (parents.length !== 1 || p.neighborhood('node[type="Claim"]').length) return
        const d = parents[0].position()
        p.position({ x: d.x - 62, y: d.y - 54 })
      })
      if (first || added.length > 20) cy.fit(cy.elements(), Math.min(110, cy.width() * 0.1))
      place()
    })
    layout.run()
  }, [model, visible, layoutTick])

  useLayoutEffect(place, [ids])

  // the similarity threshold only changes visibility, never positions
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.edges('[rel="DISEASE_MATCH"]').forEach((e) => { e.toggleClass('below', e.data('score') < minSim) })
    cy.edges('[rel="DISEASE_BRIDGE"]').toggleClass('below', !showBridges)
  }, [minSim, showBridges, ids])

  // selection -> highlight its visible neighbourhood, fade the rest
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('faded hi')
    els.current.forEach((e) => e.root.classList.remove('is-selected', 'is-faded'))
    if (selected) {
      const el = cy.getElementById(selected.id)
      if (el.nonempty()) {
        const shown = selected.kind === 'node' ? el.connectedEdges().filter((x) => !x.hasClass('below')) : el
        const keepNodes = selected.kind === 'node' ? shown.connectedNodes().union(el) : el.connectedNodes()
        shown.addClass('hi')
        cy.edges().not(shown).addClass('faded')
        cy.nodes().forEach((n) => { if (!keepNodes.has(n)) els.current.get(n.id())?.root.classList.add('is-faded') })
        if (selected.kind === 'node') els.current.get(selected.id)?.root.classList.add('is-selected')
        // keep the selection out from under the sheet (right side on desktop, bottom on phones)
        const desktop = window.innerWidth >= 768
        const free = { w: cy.width() - (desktop ? 430 : 0), h: desktop ? cy.height() : cy.height() * 0.36 }
        const target = selected.kind === 'node' ? el : el.connectedNodes()
        const bb = target.renderedBoundingBox()
        const cxr = (bb.x1 + bb.x2) / 2, cyr = (bb.y1 + bb.y2) / 2
        if (bb.x1 < 30 || bb.x2 > free.w - 30 || bb.y1 < 80 || bb.y2 > free.h - 20) {
          cy.animate({ panBy: { x: free.w / 2 - cxr, y: (free.h + 40) / 2 - cyr } }, { duration: 450, easing: 'ease-in-out-cubic' })
        }
      }
    }
    place()
  }, [selected, ids, minSim, showBridges])

  // search / card navigation: centre on the selected node, leaving room for the sheet
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !focusTick) return
    const sel = useStore.getState().selected
    const el = sel ? cy.getElementById(sel.id) : null
    if (!el || el.empty()) return
    cy.stop(true, false) // replace the selection's pan-into-view with a proper centre
    const z = Math.max(cy.zoom(), 0.9)
    const sheet = window.innerWidth >= 768 ? 430 : 0
    const p = el.position()
    cy.animate({ zoom: z, pan: { x: (cy.width() - sheet) / 2 - p.x * z, y: cy.height() / 2 - p.y * z } },
      { duration: 500, easing: 'ease-in-out-cubic' })
  }, [focusTick])

  const zoomBy = (f: number) => {
    const cy = cyRef.current
    if (!cy) return
    cy.animate({ zoom: { level: cy.zoom() * f, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } } }, { duration: 200 })
  }

  return (
    <div className="absolute inset-0">
      <canvas ref={grid} className="pointer-events-none absolute inset-0 h-full w-full" />
      {/* Cytoscape forces position:relative on its container, so it needs a sized wrapper */}
      <div ref={box} className="h-full w-full" />
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        {model && ids.map((id) => {
          const n = model.nodes.get(id)
          if (!n) return null
          return <NodeView key={id} id={id} type={n.type} title={nodeLabel(n)} subtitle={nodeSubtitle(n, model)}
            register={(e) => { if (e) els.current.set(id, e); else els.current.delete(id) }} />
        })}
      </div>

      <div className="glass absolute bottom-4 right-4 z-20 flex flex-col overflow-hidden rounded-xl">
        {[
          { icon: Plus, label: 'Zoom in', fn: () => zoomBy(1.3) },
          { icon: Minus, label: 'Zoom out', fn: () => zoomBy(1 / 1.3) },
          { icon: Maximize2, label: 'Fit', fn: () => cyRef.current?.animate({ fit: { eles: cyRef.current.elements(), padding: 110 } }, { duration: 350 }) },
        ].map(({ icon: Icon, label, fn }) => (
          <button key={label} onClick={fn} aria-label={label} title={label}
            className="flex h-9 w-9 items-center justify-center border-b border-line text-ink-2 last:border-b-0 hover:bg-subtle">
            <Icon size={16} strokeWidth={2} />
          </button>
        ))}
      </div>
    </div>
  )
}

function NodeView({ id, type, title, subtitle, register }: {
  id: string; type: string; title: string; subtitle: string; register: (e: NodeEls | null) => void
}) {
  const root = useRef<HTMLDivElement>(null)
  const bubble = useRef<HTMLDivElement>(null)
  const label = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    register({ root: root.current!, bubble: bubble.current!, label: label.current })
    return () => register(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const c = TYPE_COLOR[type] ?? '#64748b'
  const Icon = TYPE_ICON[type]
  const big = type === 'Disease'
  const withIcon = ['Gene', 'Mechanism', 'PatientOrg', 'Study', 'Paper', 'Intervention', 'Grant', 'GeneGroup'].includes(type)

  return (
    <div ref={root} className="node">
      <div ref={bubble} className="node-bubble absolute flex items-center justify-center rounded-full"
        style={{
          background: big
            ? `radial-gradient(circle at 32% 28%, #ff8aa6 0%, ${c} 55%, #c81e4c 100%)`
            : withIcon ? `radial-gradient(circle at 32% 28%, ${c}cc 0%, ${c} 60%)` : c,
          boxShadow: big
            ? `0 12px 28px -10px ${c}aa, 0 2px 6px -2px ${c}66, inset 0 1px 1px rgba(255,255,255,.45)`
            : `0 6px 14px -6px ${c}99, 0 0 0 2px #fff`,
        }}>
        <span className="node-ring absolute inset-0 rounded-full" style={{ boxShadow: `0 0 0 3px ${c}` }} />
        {withIcon && Icon && <Icon className="h-[46%] w-[46%] text-white" strokeWidth={2.2} />}
      </div>
      {type !== 'Variant' || title ? (
        <div ref={label} className={type === 'Gene'
          ? 'absolute -translate-y-1/2 whitespace-nowrap text-left transition-opacity'
          : 'absolute -translate-x-1/2 whitespace-nowrap text-center transition-opacity'}>
          <div className={big
            ? 'rounded-full bg-white/90 px-2.5 py-0.5 text-[12.5px] font-semibold tracking-tight text-ink shadow-[0_1px_2px_rgba(15,23,42,0.08)] ring-1 ring-black/5'
            : type === 'Gene' ? 'text-[11.5px] font-semibold text-[#2f6bff]'
            : type === 'GeneGroup' ? 'max-w-[150px] whitespace-normal text-[11px] font-semibold leading-tight text-[#7c3aed]'
            : 'text-[11px] font-medium text-ink-2'}>
            {title}
          </div>
          {subtitle && type === 'Gene' && <div className="mt-0.5 text-[10.5px] font-medium text-ink-3">{subtitle}</div>}
        </div>
      ) : null}
    </div>
  )
}
