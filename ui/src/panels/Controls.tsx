import { RotateCcw } from 'lucide-react'
import { motion } from 'motion/react'
import { STRENGTH_CUTOFFS, TYPE_COLOR } from '../graph/model'
import { useStore } from '../store'
import { cx } from '../ui/kit'

const LEVELS = [
  { id: 'all', label: 'All', min: 0 },
  { id: 'moderate', label: 'Moderate+', min: STRENGTH_CUTOFFS.moderate },
  { id: 'strong', label: 'Strong', min: STRENGTH_CUTOFFS.strong },
]
const LEGEND: [string, string][] = [['Disease', 'Disease'], ['Gene', 'Gene'], ['GeneGroup', 'Gene family'], ['Paper', 'Paper'], ['Mechanism', 'Mechanism']]

export default function Controls() {
  const { minSim, setMinSim, reset } = useStore()
  const level = minSim >= STRENGTH_CUTOFFS.strong ? 'strong' : minSim >= STRENGTH_CUTOFFS.moderate ? 'moderate' : 'all'
  return (
    <div className="absolute bottom-4 left-4 z-20 flex flex-col items-start gap-2">
      <div className="glass flex items-center gap-1 rounded-xl p-1">
        <span className="px-2 text-[11.5px] font-medium text-ink-3">Symptom matches</span>
        {LEVELS.map((l) => (
          <button key={l.id} onClick={() => setMinSim(l.min)}
            className={cx('relative rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors', level === l.id ? 'text-ink' : 'text-ink-3 hover:text-ink-2')}>
            {level === l.id && <motion.span layoutId="lvl" className="absolute inset-0 -z-0 rounded-lg bg-white shadow-[0_1px_2px_rgba(15,23,42,0.1)]" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
            <span className="relative">{l.label}</span>
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-line" />
        <button onClick={reset} title="Reset view" className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-2 hover:bg-black/[0.04]">
          <RotateCcw size={14} strokeWidth={2.2} />
        </button>
      </div>
      <div className="glass flex items-center gap-3.5 rounded-xl px-3 py-2 text-[11.5px] font-medium text-ink-2">
        {LEGEND.map(([t, label]) => (
          <span key={t} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: TYPE_COLOR[t] }} />{label}
          </span>
        ))}
      </div>
    </div>
  )
}
