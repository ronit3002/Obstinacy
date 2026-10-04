import { CornerDownLeft, Search, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { nodeLabel, titleCase } from '../graph/model'
import { useStore } from '../store'
import type { GNode } from '../types'
import { TypeTile } from '../ui/icons'
import { cx } from '../ui/kit'

const GROUPS: { type: string; title: string; max: number }[] = [
  { type: 'Disease', title: 'Diseases', max: 5 },
  { type: 'Gene', title: 'Genes', max: 4 },
  { type: 'Phenotype', title: 'Symptoms', max: 5 },
  { type: 'Mechanism', title: 'Mechanisms', max: 3 },
  { type: 'Paper', title: 'Papers', max: 3 },
  { type: 'Intervention', title: 'Treatments studied', max: 3 },
  { type: 'Researcher', title: 'Researchers', max: 3 },
  { type: 'PatientOrg', title: 'Patient groups', max: 3 },
  { type: 'Variant', title: 'Variants', max: 3 },
]

/** Which synonym/alias matched, so "DEE27" or "NR2B" visibly resolves to the right node. */
function matchedAlias(n: GNode, q: string): string | null {
  const ql = q.toLowerCase()
  if (n.name.toLowerCase().includes(ql)) return null
  const pool = [...((n.synonyms as string[]) ?? []), ...((n.aliases as string[]) ?? []), String(n.short ?? '')]
  return pool.find((s) => s.toLowerCase().includes(ql)) ?? null
}

export default function SearchBar() {
  const model = useStore((s) => s.model)
  const reveal = useStore((s) => s.reveal)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const wrap = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const close = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false) }
    const key = (e: KeyboardEvent) => {
      if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && document.activeElement?.tagName !== 'INPUT')) {
        e.preventDefault(); input.current?.focus(); setOpen(true)
      }
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', key) }
  }, [])

  const groups = useMemo(() => {
    if (!model || q.trim().length < 2) return []
    const hits = model.fuse.search(q.trim(), { limit: 80 }).map((r) => r.item)
    return GROUPS.map((g) => ({ ...g, items: hits.filter((h) => h.type === g.type).slice(0, g.max) })).filter((g) => g.items.length)
  }, [model, q])
  const flat = groups.flatMap((g) => g.items)
  useEffect(() => setActive(0), [q])

  const pick = (n?: GNode) => { if (!n) return; reveal(n.id); setOpen(false); setQ(''); input.current?.blur() }
  const show = open && q.trim().length >= 2

  return (
    <div ref={wrap} className="relative w-full max-w-[560px]">
      <div className={cx('glass flex items-center gap-3 rounded-2xl px-4 transition-shadow', show && 'rounded-b-2xl')}>
        <Search size={17} strokeWidth={2.2} className="shrink-0 text-ink-3" />
        <input
          ref={input} value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, flat.length - 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
            if (e.key === 'Enter') pick(flat[active])
            if (e.key === 'Escape') { setOpen(false); input.current?.blur() }
          }}
          placeholder="Search a disease, gene or symptom…"
          className="h-12 w-full bg-transparent text-[15px] text-ink placeholder:text-ink-3 outline-none"
        />
        {q
          ? <button onClick={() => setQ('')} aria-label="Clear" className="flex h-6 w-6 items-center justify-center rounded-full bg-black/[0.05] text-ink-2 hover:bg-black/[0.09]"><X size={13} strokeWidth={2.5} /></button>
          : <kbd className="hidden whitespace-nowrap sm:inline">Ctrl K</kbd>}
      </div>

      <AnimatePresence>
        {show && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15 }}
            className="glass scroll-thin absolute mt-2 max-h-[min(70vh,520px)] w-full overflow-auto rounded-2xl p-2">
            {!groups.length && <p className="px-3 py-6 text-center text-[13px] text-ink-3">No matches for “{q}”. Try a gene symbol or a symptom.</p>}
            {groups.map((g) => (
              <div key={g.type} className="pb-1">
                <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">{g.title}</p>
                {g.items.map((n) => {
                  const i = flat.indexOf(n)
                  const alias = matchedAlias(n, q.trim())
                  return (
                    <button key={n.id} onMouseEnter={() => setActive(i)} onClick={() => pick(n)}
                      className={cx('flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left', i === active && 'bg-black/[0.04]')}>
                      <TypeTile type={n.type} size={30} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-medium text-ink">
                          {n.type === 'Disease' ? titleCase(n.name) : nodeLabel(n)}
                        </span>
                        <span className="block truncate text-[12px] text-ink-3">
                          {alias ? <>Matches <span className="font-medium text-ink-2">{alias}</span></> : n.type === 'Disease' && n.short ? `${n.short} gene` : n.id}
                        </span>
                      </span>
                      {i === active && <CornerDownLeft size={14} className="shrink-0 text-ink-3" />}
                    </button>
                  )
                })}
              </div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
