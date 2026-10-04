import cytoscape from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { TYPE_ICON } from '../ui/icons'
import { TYPE_COLOR, nodeLabel, nodeSubtitle } from './model'
import { drawBlueprint } from './blueprint'
import { combined, describe, hubLinks, lensDef, pairLayers } from './lens'

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
  // disease-to-disease lines share one bezier bundle, so several connection types fan out side by side
  { selector: 'edge[rel="DISEASE_MATCH"]', style: {
      'curve-style': 'bezier', 'control-point-step-size': 16,
      'line-color': '#f43f6b', opacity: 0.4, width: 'mapData(score, 20, 40, 1.5, 5)' as never, 'line-style': 'solid' } as never },
  { selector: 'edge.hi', style: { opacity: 0.85 } },
  { selector: 'edge[rel="DISEASE_MATCH"].hi', style: { opacity: 0.7 } },
  // one typed line per connection layer and disease pair (colour + dash = what the link is based on)
  { selector: 'edge[rel="TYPED"]', style: {
      'curve-style': 'bezier', 'control-point-step-size': 16, 'line-color': 'data(color)',
      width: 'mapData(strength, 0, 1, 1.5, 5)', opacity: 0.6 } as never },
  { selector: 'edge[rel="TYPED"][dash="dashed"]', style: { 'line-style': 'dashed', 'line-dash-pattern': [7, 4] } as never },
  { selector: 'edge[rel="TYPED"][dash="dotted"]', style: { 'line-style': 'dashed', 'line-dash-pattern': [2, 4] } as never },
  { selector: 'edge[rel="TYPED"].hi, edge[rel="DISEASE_MATCH"].hover, edge[rel="TYPED"].hover', style: { opacity: 0.95 } },
  { selector: 'edge[rel="TYPED"].hi, edge[rel="TYPED"].hover', style: {
      label: 'data(label)', 'font-size': 10, 'font-weight': 600, color: 'data(color)', 'text-rotation': 'autorotate',
      'text-background-color': '#ffffff', 'text-background-opacity': 0.92, 'text-background-padding': '3px',
      'text-background-shape': 'roundrectangle', 'font-family': 'Inter, sans-serif' } as never },
  { selector: 'edge[rel="MEMBER_OF"]', style: { 'line-color': '#fdba74', width: 1.5 } },
  // connection lens: disease -- hub edges coloured like the hub type
  { selector: 'edge[rel="LENS"]', style: { 'line-color': 'data(color)', width: 2, opacity: 0.5 } },
  { selector: 'edge[rel="LENS"].hi', style: { opacity: 0.95 } },
  { selector: 'edge[rel="DISCUSSES"]', style: { 'line-color': '#94a3b8', 'line-style': 'dashed', 'line-dash-pattern': [3, 4] } as never },
  { selector: 'edge.faded', style: { opacity: 0.05 } },
  // weak links stay in the layout (so similar diseases still sit closer) but are invisible
  { selector: 'edge.below', style: { opacity: 0, events: 'no' } as never },
  { selector: 'edge.below.hi', style: { opacity: 0.7 } }, // an explicitly selected weak link still shows
  // invisible springs: the combined strength of all active layers sets how close two diseases sit
  { selector: 'edge[rel="SPRING"]', style: { opacity: 0, events: 'no', width: 1 } as never },
]

/** Best rotation (+ optional mirror) and translation that maps the new layout onto the previous one,
 * so recomputing the arrangement does not spin or flip the map. Returns a position transform. */
function alignTo(before: Map<string, { x: number; y: number }>, ids: string[], cy: cytoscape.Core) {
  const pts = ids.filter((id) => before.has(id)).map((id) => ({ a: cy.getElementById(id).position(), b: before.get(id)! }))
  if (pts.length < 2) return (p: { x: number; y: number }) => ({ ...p })
  const ca = { x: 0, y: 0 }, cb = { x: 0, y: 0 }
  pts.forEach(({ a, b }) => { ca.x += a.x / pts.length; ca.y += a.y / pts.length; cb.x += b.x / pts.length; cb.y += b.y / pts.length })
  const fit = (mirror: number) => {
    let sxx = 0, sxy = 0
    pts.forEach(({ a, b }) => {
      const ax = mirror * (a.x - ca.x), ay = a.y - ca.y, bx = b.x - cb.x, by = b.y - cb.y
      sxx += ax * bx + ay * by; sxy += ax * by - ay * bx
    })
    const t = Math.atan2(sxy, sxx), c = Math.cos(t), s = Math.sin(t)
    const tf = (p: { x: number; y: number }) => {
      const x = mirror * (p.x - ca.x), y = p.y - ca.y
      return { x: cb.x + c * x - s * y, y: cb.y + s * x + c * y }
    }
    const err = pts.reduce((e, { a, b }) => { const q = tf(a); return e + (q.x - b.x) ** 2 + (q.y - b.y) ** 2 }, 0)
    return { tf, err }
  }
  const plain = fit(1), mirrored = fit(-1)
  return (plain.err <= mirrored.err ? plain : mirrored).tf
}

type NodeEls = { root: HTMLDivElement; bubble: HTMLDivElement; label: HTMLDivElement | null }

export default function GraphView() {
  const box = useRef<HTMLDivElement>(null)
  const grid = useRef<HTMLCanvasElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const els = useRef(new Map<string, NodeEls>())
  const [ids, setIds] = useState<string[]>([])
  const { model, visible, minSim, layoutTick, focusTick, selected, layers, groupFocus } = useStore()
  const layerKey = useRef('')

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
      useStore.getState().openNode(id)
    })
    cy.on('tap', 'edge', (ev) => {
      const rel = ev.target.data('rel')
      // derived edges: a hub line opens its hub, a typed line opens the disease pair's connection card
      if (rel === 'LENS') useStore.getState().select({ kind: 'node', id: ev.target.data('target') })
      else if (rel === 'TYPED') useStore.getState().select({ kind: 'edge', id: `PAIR:${ev.target.data('pair')}` })
      else useStore.getState().select({ kind: 'edge', id: ev.target.id() })
    })
    cy.on('tap', (ev) => { if (ev.target === cy) useStore.getState().select(null) })
    cy.on('mouseover', 'node', (ev) => { els.current.get(ev.target.id())?.root.classList.add('is-hover'); box.current!.style.cursor = 'pointer'; place() })
    cy.on('mouseout', 'node', (ev) => { els.current.get(ev.target.id())?.root.classList.remove('is-hover'); box.current!.style.cursor = ''; place() })
    cy.on('mouseover', 'edge', (ev) => { ev.target.addClass('hover'); box.current!.style.cursor = 'pointer' })
    cy.on('mouseout', 'edge', (ev) => { ev.target.removeClass('hover'); box.current!.style.cursor = '' })
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

  // sync visible set + connection layers -> cytoscape elements, then lay out
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !model) return
    const added: string[] = []
    const want = visible
    const key = `${[...layers].sort().join(',')}|${groupFocus.join(',')}|${minSim}`
    const layersChanged = key !== layerKey.current
    layerKey.current = key
    const symptomsOn = layers.includes('symptoms')
    const pairs = pairLayers(model, layers, minSim, groupFocus)
    const shownDisease = (id: string) => want.has(id) && model.nodes.get(id)?.type === 'Disease'

    cy.batch(() => {
      cy.nodes().forEach((n) => { if (!want.has(n.id())) n.remove() })
      for (const id of want) {
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
      // structural edges from the graph (symptom matches only while that layer is on)
      if (!symptomsOn) cy.edges('[rel="DISEASE_MATCH"]').remove()
      for (const id of want) {
        for (const e of model.adj.get(id) ?? []) {
          if (e.rel === 'DISEASE_BRIDGE' || (e.rel === 'DISEASE_MATCH' && !symptomsOn)) continue
          if (want.has(e.source) && want.has(e.target) && cy.getElementById(e.id).empty()) {
            cy.add({ group: 'edges', data: { id: e.id, source: e.source, target: e.target, rel: e.rel,
              status: e.status, score: (e.score as number) ?? 0 } })
          }
        }
      }
      // typed lines (one per layer and pair) and invisible springs (combined strength)
      const typed = new Set<string>(), springs = new Set<string>()
      for (const [k, cs] of pairs) {
        const [a, b] = k.split('|')
        if (!shownDisease(a) || !shownDisease(b)) continue
        for (const c of cs) {
          if (c.mode === 'symptoms') continue
          const id = `TYPED:${c.mode}:${k}`, def = lensDef(c.mode)
          typed.add(id)
          const data = { strength: c.strength, label: describe(c), color: def.color, dash: def.dash }
          const el = cy.getElementById(id)
          if (el.nonempty()) el.data(data)
          else cy.add({ group: 'edges', data: { id, source: a, target: b, rel: 'TYPED', mode: c.mode, pair: k, ...data } })
        }
        const sid = `SPRING:${k}`, st = combined(cs)
        springs.add(sid)
        const el = cy.getElementById(sid)
        if (el.nonempty()) el.data('strength', st)
        else cy.add({ group: 'edges', data: { id: sid, source: a, target: b, rel: 'SPRING', strength: st } })
      }
      cy.edges('[rel="TYPED"]').forEach((e) => { if (!typed.has(e.id())) e.remove() })
      cy.edges('[rel="SPRING"]').forEach((e) => { if (!springs.has(e.id())) e.remove() })
      // hub lines: any visible hub of an active layer connects to the visible diseases it serves
      const hubEdges = new Set<string>()
      for (const mode of layers) {
        if (mode === 'symptoms') continue
        const color = lensDef(mode).color
        for (const [hub, ds] of hubLinks(model, mode, groupFocus)) {
          if (!want.has(hub)) continue
          for (const [d, via] of ds) {
            if (!want.has(d)) continue
            const id = `LENS:${hub}:${d}`
            hubEdges.add(id)
            if (cy.getElementById(id).empty()) cy.add({ group: 'edges', data: { id, source: d, target: hub, rel: 'LENS', color, via } })
          }
        }
      }
      cy.edges('[rel="LENS"]').forEach((e) => { if (!hubEdges.has(e.id())) e.remove() })
    })
    setIds(cy.nodes().map((n) => n.id()))
    if (!added.length && !layersChanged) return

    const first = added.length === want.size
    const springsOn = cy.edges('[rel="SPRING"]').length > 0
    cy.nodes().stop(true, true)  // a running glide jumps to its end, so the next one starts from a settled map
    const before = new Map(cy.nodes().map((n) => [n.id(), { ...n.position() }]))
    // Changing the connection layers changes every disease distance, so the arrangement is recomputed from
    // scratch (an incremental run gets stuck near the old arrangement) and then aligned to the old map.
    const fresh = first || layersChanged
    const layout = cy.layout({ name: 'fcose', animate: false, randomize: fresh, fit: false, quality: 'proof',
      numIter: 4000, nodeSeparation: 120, gravity: springsOn ? 0.35 : 0.15,
      nodeRepulsion: (n: cytoscape.NodeSingular) => (n.data('type') === 'Disease' ? 9000 : 4500),
      // springs (combined strength of all active layers) decide disease distances; the visible
      // disease-to-disease lines just ride along
      idealEdgeLength: (e: cytoscape.EdgeSingular) => {
        const r = e.data('rel')
        if (r === 'SPRING') return 560 - 450 * e.data('strength')
        if (r === 'DISEASE_MATCH') return 540 - 11 * e.data('score')
        return r === 'MEMBER_OF' ? 110 : r === 'LENS' ? 150 : r === 'TYPED' ? 300 : 80
      },
      edgeElasticity: (e: cytoscape.EdgeSingular) => {
        const r = e.data('rel')
        if (r === 'SPRING') return 0.25 + 0.75 * e.data('strength')
        if (r === 'TYPED') return 0.0001
        if (r === 'DISEASE_MATCH') return springsOn ? 0.0001 : 0.2 + e.data('score') / 100
        return 0.6
      },
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
    })
    layout.run()  // synchronous (animate: false); the satellite snapping above has run too

    if (first) {
      cy.fit(cy.elements(), Math.min(110, cy.width() * 0.1))
      place()
      return
    }
    // glide every node from where it was to where it belongs now
    const map = fresh ? alignTo(before, cy.nodes('[type="Disease"]').map((n) => n.id()), cy) : null
    const targets: Record<string, { x: number; y: number }> = {}
    if (import.meta.env.DEV) (window as unknown as { glideTargets: typeof targets }).glideTargets = targets // console debugging
    cy.nodes().forEach((n) => {
      const target = map ? map(n.position()) : { ...n.position() }
      targets[n.id()] = target
      const start = before.get(n.id()) ?? target
      n.position(start)
      n.animate({ position: target }, { duration: 700, easing: 'ease-in-out-cubic' })
    })
    if (added.length > 20) setTimeout(() => cy.animate({ fit: { eles: cy.elements(), padding: Math.min(110, cy.width() * 0.1) } }, { duration: 400 }), 720)
    place()
  }, [model, visible, layoutTick, layers, groupFocus, minSim])

  useLayoutEffect(place, [ids])

  // the similarity threshold only changes visibility, never positions
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.edges('[rel="DISEASE_MATCH"]').forEach((e) => { e.toggleClass('below', e.data('score') < minSim) })
  }, [minSim, ids, layers])

  // selection -> highlight its visible neighbourhood, fade the rest
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('faded hi')
    els.current.forEach((e) => e.root.classList.remove('is-selected', 'is-faded'))
    if (selected) {
      const el = cy.getElementById(selected.id)
      if (el.nonempty()) {
        const shown = selected.kind === 'node' ? el.connectedEdges().filter((x) => !x.hasClass('below') && x.data('rel') !== 'SPRING') : el
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
  }, [selected, ids, minSim, layers, groupFocus])

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
            : type === 'GeneGroup' ? 'max-w-[150px] whitespace-normal text-[11px] font-semibold leading-tight text-[#ea580c]'
            : 'text-[11px] font-medium text-ink-2'}>
            {title}
          </div>
          {subtitle && type === 'Gene' && <div className="mt-0.5 text-[10.5px] font-medium text-ink-3">{subtitle}</div>}
        </div>
      ) : null}
    </div>
  )
}
