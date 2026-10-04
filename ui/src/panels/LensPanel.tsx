import { Layers, Map as MapIcon } from 'lucide-react'
import { motion } from 'motion/react'
import { useMemo } from 'react'
import { LENSES, lensCounts, lensView } from '../graph/lens'
import { TYPE_COLOR, nodeLabel } from '../graph/model'
import { useStore } from '../store'
import { TYPE_ICON } from '../ui/icons'
import { cx } from '../ui/kit'

/** Left-hand "Explore connections" panel: pick one kind of link and see only how diseases connect through it. */
export default function LensPanel() {
  const { model, lens, setLens, lensSharedOnly, setLensSharedOnly, minSim } = useStore()
  const counts = useMemo(() => (model ? lensCounts(model) : null), [model])
  const view = useMemo(() => (model && lens ? lensView(model, lens, lensSharedOnly, minSim) : null), [model, lens, lensSharedOnly, minSim])
  if (!model || !counts) return null
  const active = LENSES.find((l) => l.id === lens)

  return (
    <div className="glass absolute left-4 top-[84px] z-20 hidden w-[232px] rounded-2xl p-2 lg:block">
      <p className="flex items-center gap-1.5 px-2 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
        <Layers size={12} /> Explore connections
      </p>
      <button onClick={() => setLens(null)}
        className={cx('relative flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13px] font-medium',
          !lens ? 'text-ink' : 'text-ink-2 hover:bg-black/[0.03]')}>
        {!lens && <motion.span layoutId="lens-pill" className="absolute inset-0 rounded-xl bg-white shadow-[0_1px_2px_rgba(15,23,42,0.08)]" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
        <MapIcon size={15} className="relative text-ink-3" /><span className="relative">Full map</span>
      </button>
      {LENSES.map((l) => {
        const Icon = TYPE_ICON[l.hubType]
        const c = TYPE_COLOR[l.hubType]
        const on = lens === l.id
        const n = counts[l.id]
        return (
          <button key={l.id} onClick={() => setLens(l.id)} title={l.hint}
            className={cx('relative flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13px] font-medium',
              on ? 'text-ink' : 'text-ink-2 hover:bg-black/[0.03]', !n && 'opacity-50')}>
            {on && <motion.span layoutId="lens-pill" className="absolute inset-0 rounded-xl bg-white shadow-[0_1px_2px_rgba(15,23,42,0.08)]" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
            <span className="relative flex h-5 w-5 items-center justify-center rounded-md" style={{ background: c + '1a', color: c }}>
              {Icon && <Icon size={12} strokeWidth={2.4} />}
            </span>
            <span className="relative flex-1">{l.label}</span>
            <span className="relative text-[11.5px] tabular-nums text-ink-3">{n}</span>
          </button>
        )
      })}

      {active && view && (
        <div className="mt-1.5 border-t border-line px-2.5 pb-1 pt-2.5">
          <p className="text-[12px] leading-snug text-ink-2">{active.hint}</p>
          {active.id !== 'symptoms' && (
            <label className="mt-2 flex cursor-pointer items-center gap-2 text-[12px] text-ink-2">
              <input type="checkbox" checked={lensSharedOnly} onChange={(e) => setLensSharedOnly(e.target.checked)} />
              Only links shared by 2+ diseases
            </label>
          )}
          <p className="mt-2 text-[11.5px] leading-snug text-ink-3">
            {view.hubs} {active.id === 'symptoms' ? 'matches' : 'connecting ' + active.label.toLowerCase()}
            {view.unconnected.length > 0 && <> · not connected this way: {view.unconnected.map((d) => nodeLabel(d)).join(', ')}</>}
          </p>
        </div>
      )}
    </div>
  )
}
