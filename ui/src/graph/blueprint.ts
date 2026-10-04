import type cytoscape from 'cytoscape'

/**
 * Blueprint grid that bends like a rubber sheet: every disease (and, less, every gene)
 * is a "mass" that pulls nearby grid lines towards it. The grid lives in graph space,
 * so it pans and zooms with the map.
 */
const MINOR = 48 // graph units between minor lines
const MAJOR_EVERY = 5

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

  // masses in screen space
  const masses: { x: number; y: number; s: number; r: number }[] = []
  cy.nodes().forEach((n) => {
    const t = n.data('type')
    if (t !== 'Disease' && t !== 'Gene') return
    const p = n.renderedPosition()
    const sel = n.id() === selectedId
    masses.push({ x: p.x, y: p.y, s: (t === 'Disease' ? 0.34 : 0.16) * (sel ? 1.5 : 1), r: (t === 'Disease' ? 150 : 70) * z * (sel ? 1.25 : 1) })
  })

  const warp = (x: number, y: number): [number, number] => {
    let dx = 0, dy = 0
    for (const m of masses) {
      const vx = m.x - x, vy = m.y - y
      const d2 = vx * vx + vy * vy
      const f = m.s * Math.exp(-d2 / (2 * m.r * m.r))
      dx += vx * f; dy += vy * f
    }
    return [x + dx, y + dy]
  }

  const step = MINOR * z
  const showMinor = step >= 14
  const sample = 14 // px between samples along a line
  // first grid index visible on screen
  const i0 = Math.floor(-pan.x / step) - 2, i1 = Math.ceil((w - pan.x) / step) + 2
  const j0 = Math.floor(-pan.y / step) - 2, j1 = Math.ceil((h - pan.y) / step) + 2

  const stroke = (major: boolean) => {
    ctx.strokeStyle = major ? 'rgba(47, 107, 255, 0.13)' : 'rgba(47, 107, 255, 0.055)'
    ctx.lineWidth = major ? 1 : 1
  }

  for (const major of [false, true]) {
    if (!major && !showMinor) continue
    stroke(major)
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

  // soft vignette so the chrome floats
  const g = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.35, w / 2, h / 2, Math.max(w, h) * 0.75)
  g.addColorStop(0, 'rgba(246, 248, 252, 0)')
  g.addColorStop(1, 'rgba(246, 248, 252, 0.85)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)
}
