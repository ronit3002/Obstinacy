import { Layers, Map as MapIcon } from 'lucide-react'
import { useMemo } from 'react'
import { LENSES, modeCounts, networkView } from '../graph/lens'
import type { LensId } from '../graph/lens'
import { TYPE_COLOR, nodeLabel } from '../graph/model'
import { useStore } from '../store'
import { TYPE_ICON } from '../ui/icons'
import { cx } from '../ui/kit'

const strengthWord = (w: number) => (w >= 0.8 ? 'Strong' : w >= 0.45 ? 'Normal' : 'Weak')

/**
 * "Explore connections": switch on one or more kinds of connection and set how much each one counts.
 * The map then shows only the diseases, linked by the blended strength of the selected kinds.
 */
export default function LensPanel() {
  const { model, modes, toggleMode, setModeWeight, clearModes, showHubs, setShowHubs, minSim } = useStore()
  const counts = useMemo(() => (model ? modeCounts(model) : null), [model])
  const active = Object.keys(modes) as LensId[]
  const view = useMemo(() => (model && active.length ? networkView(model, modes, false, minSim) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [model, modes, minSim])
  if (!model || !counts) return null

  return (
    <div className="glass scroll-thin absolute left-4 top-[84px] z-20 hidden max-h-[calc(100dvh-200px)] w-[252px] overflow-y-auto rounded-2xl p-2 lg:block">
      <p className="flex items-center gap-1.5 px-2 pb-1.5 pt-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
        <Layers size={12} /> Explore connections
      </p>
      <button onClick={clearModes}
        className={cx('flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13px] font-medium',
          !active.length ? 'bg-white text-ink shadow-[0_1px_2px_rgba(15,23,42,0.08)]' : 'text-ink-2 hover:bg-black/[0.03]')}>
        <MapIcon size={15} className="text-ink-3" /> Diseases only
      </button>
      <p className="px-2.5 pb-1 pt-2 text-[11.5px] leading-snug text-ink-3">Connect the diseases by (pick one or more):</p>
      {LENSES.map((l) => {
        const Icon = TYPE_ICON[l.hubType]
        const c = TYPE_COLOR[l.hubType]
        const w = modes[l.id]
        const on = w !== undefined
        const n = counts[l.id]
        return (
          <div key={l.id} className={cx('rounded-xl', on && 'bg-white shadow-[0_1px_2px_rgba(15,23,42,0.08)]')}>
            <button onClick={() => toggleMode(l.id)} title={l.hint} disabled={!n}
              className={cx('flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13px] font-medium',
                on ? 'text-ink' : 'text-ink-2 hover:bg-black/[0.03]', !n && 'cursor-not-allowed opacity-45')}>
              <span className={cx('flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px] font-bold',
                on ? 'border-transparent text-white' : 'border-[#c9d1de] text-transparent')}
                style={on ? { background: c } : undefined}>✓</span>
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md" style={{ background: c + '1a', color: c }}>
                {Icon && <Icon size={12} strokeWidth={2.4} />}
              </span>
              <span className="flex-1">{l.label}</span>
              <span className="text-[11.5px] tabular-nums text-ink-3" title="disease pairs connected this way">{n}</span>
            </button>
            {on && (
              <div className="flex items-center gap-2 px-2.5 pb-2.5 pl-[38px]">
                <input type="range" min={0.1} max={1} step={0.05} value={w} aria-label={`${l.label} weight`}
                  onChange={(e) => setModeWeight(l.id, parseFloat(e.target.value))} className="w-full" style={{ accentColor: c }} />
                <span className="w-12 text-right text-[11px] font-medium text-ink-3">{strengthWord(w!)}</span>
              </div>
            )}
          </div>
        )
      })}

      {view && (
        <div className="mt-1.5 border-t border-line px-2.5 pb-1 pt-2.5">
          <label className="flex cursor-pointer items-center gap-2 text-[12px] text-ink-2">
            <input type="checkbox" checked={showHubs} onChange={(e) => setShowHubs(e.target.checked)} />
            Show what connects them
          </label>
          <p className="mt-2 text-[11.5px] leading-snug text-ink-3">
            Thicker, closer lines = stronger combined connection. {view.netEdges.length} disease pairs linked.
            {view.unconnected.length > 0 && <> Not connected this way: {view.unconnected.map((d) => nodeLabel(d)).join(', ')}.</>}
          </p>
        </div>
      )}
    </div>
  )
}
