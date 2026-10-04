import { MousePointerClick } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import GraphView from './graph/GraphView'
import { buildModel } from './graph/model'
import Controls from './panels/Controls'
import DetailPanel from './panels/DetailPanel'
import SearchBar from './panels/SearchBar'
import { useStore } from './store'
import type { GraphData } from './types'

export default function App() {
  const setModel = useStore((s) => s.setModel)
  const model = useStore((s) => s.model)
  const selected = useStore((s) => s.selected)
  const [error, setError] = useState('')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}graph.json`)
      .then((r) => r.json() as Promise<GraphData>)
      .then((d) => setModel(buildModel(d)))
      .catch((e) => setError(String(e)))
  }, [setModel])
  useEffect(() => { if (selected) setTouched(true) }, [selected])

  const diseases = model ? [...model.nodes.values()].filter((n) => n.type === 'Disease').length : 0

  return (
    <div className="relative h-dvh w-screen overflow-hidden bg-canvas">
      <GraphView />

      {/* brand */}
      <div className="pointer-events-none absolute left-5 top-5 z-20 hidden items-center gap-2.5 lg:flex">
        <div className="relative h-8 w-8 rounded-[10px] bg-gradient-to-br from-[#2f6bff] to-[#f43f6b] shadow-[0_6px_16px_-6px_rgba(47,107,255,0.6)]">
          <span className="absolute left-[7px] top-[7px] h-2 w-2 rounded-full bg-white" />
          <span className="absolute bottom-[7px] right-[7px] h-2.5 w-2.5 rounded-full bg-white/90" />
          <span className="absolute left-[11px] top-[11px] h-[1.5px] w-[11px] origin-left rotate-45 bg-white/80" />
        </div>
        <div>
          <p className="text-[15px] font-semibold leading-none tracking-tight text-ink">Atlas</p>
          <p className="mt-1 text-[11.5px] leading-none text-ink-3">Rare disease connections</p>
        </div>
      </div>

      <div className="absolute inset-x-0 top-4 z-30 flex justify-center px-4 lg:top-5">
        <SearchBar />
      </div>

      <Controls />
      <DetailPanel />

      <AnimatePresence>
        {model && !touched && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
            transition={{ delay: 0.6 }}
            className="glass pointer-events-none absolute bottom-5 left-1/2 z-10 hidden -translate-x-1/2 items-center gap-2 rounded-full px-4 py-2 text-[12.5px] text-ink-2 2xl:flex">
            <MousePointerClick size={14} className="text-accent" />
            {diseases} diseases mapped · tap one to explore its connections
          </motion.div>
        )}
      </AnimatePresence>

      {error && <p className="absolute inset-x-0 top-24 text-center text-sm text-disease">Couldn’t load the graph: {error}</p>}
      {!model && !error && <p className="absolute inset-x-0 top-1/2 text-center text-sm text-ink-3">Loading atlas…</p>}
    </div>
  )
}
