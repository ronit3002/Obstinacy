import { MousePointerClick } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import GraphView from './graph/GraphView'
import { buildModel } from './graph/model'
import Controls from './panels/Controls'
import DetailPanel from './panels/DetailPanel'
import LensPanel from './panels/LensPanel'
import AskBar from './panels/AskBar'
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
      <div className="pointer-events-none absolute left-4 top-3 z-20 hidden items-center gap-2 lg:flex">
        <img src={`${import.meta.env.BASE_URL}logo-mark.png`} alt="" className="h-12 w-12 object-contain" />
        <div>
          <p className="font-brand text-[22px] font-medium leading-none tracking-[-0.01em] text-ink">obstinacy</p>
          <p className="mt-1 text-[11px] leading-none text-ink-3">Rare disease connections</p>
        </div>
      </div>

      <div className="absolute inset-x-0 top-4 z-30 flex justify-center px-4 lg:top-5">
        <SearchBar />
      </div>

      <LensPanel />
      <Controls />
      <AskBar />
      <DetailPanel />

      <AnimatePresence>
        {model && !touched && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
            transition={{ delay: 0.6 }}
            className="glass pointer-events-none absolute bottom-[84px] left-1/2 z-10 hidden -translate-x-1/2 items-center gap-2 rounded-full px-4 py-2 text-[12.5px] text-ink-2 2xl:flex">
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
