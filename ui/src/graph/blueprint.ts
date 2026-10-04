import type cytoscape from 'cytoscape'

/**
 * Blueprint grid that behaves like a soft mat: every node presses into it and the grid lines sag
 * towards it. Diseases are the heaviest; hubs (gene families, drugs, trials) weigh a bit, small
 * detail nodes barely at all. The grid lives in graph space, so it pans and zooms with the map.
 */
const MINOR = 48 // graph units between minor lines
const MAJOR_EVERY = 5

// how hard each node type presses into the mat (1 = a disease)
const WEIGHT: Record<string, number> = {
  Disease: 1, GeneGroup: 0.45, Mechanism: 0.4, Gene: 0.32, Intervention: 0.3, Study: 0.28, Paper: 0.26,
  PatientOrg: 0.26, Grant: 0.22, Researcher: 0.16, Phenotype: 0.1, Claim: 0.08, Variant: 0.05,
}
const PULL = 0.22       // share of the distance a grid point is pulled towards a disease
const MAX_MASSES = 140  // performance cap: only the heaviest visible nodes press

type Mass = { x: number; y: number; s: number; r2: number; r: number; w: number }

export function drawBlueprint(canvas: HTMLCanvasElement, cy: cytoscape.Core, selectedId?: string) {
  const dpr = window.devicePixelRatio || 1
  const w = canvas.clientWidth, h = canvas.clientHeight
  if (!w || !h) return
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr)
  }
  const ctx = canvas.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)

  const z = cy.zoom()
  const pan = cy.pan()

  // masses in screen space; nodes far outside the viewport cannot bend visible lines
  let masses: Mass[] = []
  cy.nodes().forEach((n) => {
    const wt = (WEIGHT[n.data('type')] ?? 0.1) * (n.id() === selectedId ? 1.35 : 1)
    const p = n.renderedPosition()
    const r = (55 + 135 * wt) * z
    if (p.x < -r * 2 || p.y < -r * 2 || p.x > w + r * 2 || p.y > h + r * 2) return
    masses.push({ x: p.x, y: p.y, s: PULL * wt, r, r2: 2 * r * r, w: wt })
  })
  if (masses.length > MAX_MASSES) masses = masses.sort((a, b) => b.w - a.w).slice(0, MAX_MASSES)

  // soft depth: a faint shadow where the mat is pressed down
  for (const m of masses) {
    if (m.w < 0.25) continue
    const g = ctx.createRadialGradient(m.x, m.y, 0, m.x, m.y, m.r * 1.15)
    g.addColorStop(0, `rgba(47, 107, 255, ${0.06 * m.w})`)
    g.addColorStop(1, 'rgba(47, 107, 255, 0)')
    ctx.fillStyle = g
    ctx.beginPath(); ctx.arc(m.x, m.y, m.r * 1.15, 0, Math.PI * 2); ctx.fill()
  }

  const warp = (x: number, y: number): [number, number] => {
    let dx = 0, dy = 0
    for (const m of masses) {
      const vx = m.x - x, vy = m.y - y
      const d2 = vx * vx + vy * vy
      if (d2 > m.r2 * 4.5) continue  // beyond ~3 sigma the pull is negligible
      const f = m.s * Math.exp(-d2 / m.r2)
      dx += vx * f; dy += vy * f
    }
    // smooth saturation (tanh) instead of a hard cap: overlapping weights deepen the dip gradually
    // and never fold the mat or leave a corner where the cap would kick in
    const len = Math.hypot(dx, dy)
    if (len > 1e-6) {
      const cap = 34 * Math.max(z, 0.4)
      const k = (cap * Math.tanh(len / cap)) / len
      dx *= k; dy *= k
    }
    return [x + dx, y + dy]
  }

  const step = MINOR * z
  const showMinor = step >= 14
  const sample = 7 // px between samples along a line (small = smooth curves)
  const i0 = Math.floor(-pan.x / step) - 2, i1 = Math.ceil((w - pan.x) / step) + 2
  const j0 = Math.floor(-pan.y / step) - 2, j1 = Math.ceil((h - pan.y) / step) + 2

  for (const major of [false, true]) {
    if (!major && !showMinor) continue
    ctx.strokeStyle = major ? 'rgba(47, 107, 255, 0.13)' : 'rgba(47, 107, 255, 0.055)'
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let i = i0; i <= i1; i++) {
      if ((i % MAJOR_EVERY === 0) !== major) continue
      const x = pan.x + i * step
      for (let y = -sample, k = 0; y <= h + sample; y += sample, k++) {
        const [wx, wy] = warp(x, y)
        if (k === 0) ctx.moveTo(wx, wy); else ctx.lineTo(wx, wy)
      }
    }
    for (let j = j0; j <= j1; j++) {
      if ((j % MAJOR_EVERY === 0) !== major) continue
      const y = pan.y + j * step
      for (let x = -sample, k = 0; x <= w + sample; x += sample, k++) {
        const [wx, wy] = warp(x, y)
        if (k === 0) ctx.moveTo(wx, wy); else ctx.lineTo(wx, wy)
      }
    }
    ctx.stroke()
  }

  // soft vignette so the floating chrome reads well
  const g = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.35, w / 2, h / 2, Math.max(w, h) * 0.75)
  g.addColorStop(0, 'rgba(246, 248, 252, 0)')
  g.addColorStop(1, 'rgba(246, 248, 252, 0.85)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)
}
