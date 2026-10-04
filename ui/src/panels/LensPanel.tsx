import { Layers } from 'lucide-react'
import { useMemo } from 'react'
import { GROUP_FOCUS, LENSES, modeCounts } from '../graph/lens'
import { useStore } from '../store'
import { TYPE_ICON } from '../ui/icons'
import { cx } from '../ui/kit'

/** A short sample of the line style each connection type draws on the map. */
function LineSwatch({ color, dash }: { color: string; dash: string }) {
  return (
    <svg width="22" height="8" className="shrink-0" aria-hidden>
      <line x1="1" y1="4" x2="21" y2="4" stroke={color} strokeWidth="2.5" strokeLinecap="round"
        strokeDasharray={dash === 'dashed' ? '6 3' : dash === 'dotted' ? '1.5 3.5' : undefined} />
    </svg>
  )
}

/**
 * "Connections": switch connection types on and off. Each active type draws its own coloured line
 * between diseases on the current map; together they decide how close the diseases sit.
 */
export default function LensPanel() {
  const { model, layers, toggleLayer, clearLayers, groupFocus, toggleGroupFocus } = useStore()
  const counts = useMemo(() => (model ? modeCounts(model, groupFocus) : null), [model, groupFocus])
  if (!model || !counts) return null

  return (
    <div className="glass scroll-thin absolute left-4 top-[84px] z-20 hidden max-h-[calc(100dvh-200px)] w-[252px] overflow-y-auto rounded-2xl p-2 lg:block">
      <div className="flex items-center justify-between px-2 pb-1 pt-1">
        <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3"><Layers size={12} /> Connections</p>
        {layers.length > 0 && <button onClick={clearLayers} className="text-[11.5px] font-medium text-accent hover:underline">Clear</button>}
      </div>
      <p className="px-2 pb-1.5 text-[11.5px] leading-snug text-ink-3">Add connection types to the map. Diseases that share more sit closer together.</p>
      {LENSES.map((l) => {
        const Icon = TYPE_ICON[l.hubType]
        const on = layers.includes(l.id)
        const n = counts[l.id]
        return (
          <div key={l.id} className={cx('rounded-xl', on && 'bg-white shadow-[0_1px_2px_rgba(15,23,42,0.08)]')}>
            <button onClick={() => toggleLayer(l.id)} title={l.hint} disabled={!n}
              className={cx('flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13px] font-medium',
                on ? 'text-ink' : 'text-ink-2 hover:bg-black/[0.03]', !n && 'cursor-not-allowed opacity-45')}>
              <span className={cx('flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px] font-bold',
                on ? 'border-transparent text-white' : 'border-[#c9d1de] text-transparent')}
                style={on ? { background: l.color } : undefined}>✓</span>
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md" style={{ background: l.color + '1a', color: l.color }}>
                {Icon && <Icon size={12} strokeWidth={2.4} />}
              </span>
              <span className="flex-1">{l.label}</span>
              <LineSwatch color={l.color} dash={l.dash} />
            </button>
            {on && l.id === 'groups' && (
              <div className="flex flex-wrap gap-1 px-2.5 pb-2.5 pl-[38px]">
                {GROUP_FOCUS.map((f) => {
                  const active = groupFocus.includes(f)
                  return (
                    <button key={f} onClick={() => toggleGroupFocus(f)}
                      className={cx('rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors',
                        active ? 'border-transparent text-white' : 'border-line text-ink-3 hover:text-ink-2')}
                      style={active ? { background: l.color } : undefined}>
                      {f === 'Disease-specific' ? 'Gene-specific' : f === 'Children & disability' ? 'Disability' : f}
                    </button>
                  )
                })}
              </div>
            )}
            {on && n > 0 && <p className="px-2.5 pb-2 pl-[38px] text-[11px] text-ink-3">{n} disease pair{n === 1 ? '' : 's'} connected</p>}
          </div>
        )
      })}
      <p className="mt-1.5 border-t border-line px-2.5 pb-1 pt-2 text-[11px] leading-snug text-ink-3">
        Hover a line to see what it is based on; click it for the full list.
      </p>
    </div>
  )
}
