import { ArrowUp, Sparkles, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, useState } from 'react'
import { neighbours, nodeLabel } from '../graph/model'
import type { Model } from '../graph/model'
import { useStore } from '../store'
import type { GNode } from '../types'
import { cx } from '../ui/kit'

/**
 * "Ask AI" bar (design preview only, nothing is sent anywhere). It shows where the product is going:
 * questions about the selected node, answered by an OpenAI model using only the atlas's sourced edges.
 */
function suggestions(n: GNode | null, m: Model | null): string[] {
  if (!n || !m) {
    return ['Which diseases share a mechanism with Dravet syndrome?', 'Where could a GRIN family find an existing registry to join?']
  }
  const label = nodeLabel(n)
  if (n.type === 'Disease') {
    const match = neighbours(m, n.id).filter((x) => x.edge.rel === 'DISEASE_MATCH')
      .sort((a, b) => (b.edge.score as number) - (a.edge.score as number))[0]
    return [
      match ? `Why is ${label} linked to ${nodeLabel(match.node)}, and what could the two communities learn from each other?`
        : `What is known about the mechanism behind ${label}?`,
      `Which trials could a child with ${label} join today?`,
      `Explain ${label} in simple words for a newly diagnosed family.`,
    ]
  }
  if (n.type === 'Gene') return [`What do the top ${n.name} variants mean for how severe the disease is?`, `Which other genes act through the same mechanism as ${n.name}?`]
  if (n.type === 'Intervention') return [`Which diseases is ${n.name} being tested in, and what were the results so far?`]
  if (n.type === 'Paper') return ['Summarise this paper in plain language for a parent.', 'What are the limitations of this study?']
  if (n.type === 'Mechanism') return [`What does "${n.name}" mean, and could one treatment help all these diseases?`]
  return [`How does ${label} connect to the diseases in the atlas?`]
}

function OpenAIMark({ className }: { className?: string }) {
  return <img src={`${import.meta.env.BASE_URL}openai-mark.png`} alt="OpenAI" className={className} />
}

export default function AskBar() {
  const { model, selected } = useStore()
  const node = model && selected?.kind === 'node' ? model.nodes.get(selected.id) ?? null : null
  const ideas = useMemo(() => suggestions(node, model), [node, model])
  const [text, setText] = useState('')
  const [focused, setFocused] = useState(false)
  const [asked, setAsked] = useState<string | null>(null)
  const context = node ? nodeLabel(node) : 'the atlas'

  const send = (q: string) => {
    if (!q.trim()) return
    setAsked(q.trim())
    setText('')
  }

  return (
    // centred in the space left of the detail card when one is open
    <div className={cx('pointer-events-none absolute bottom-[104px] z-20 hidden -translate-x-1/2 transition-[left,width] duration-300 md:block xl:bottom-4',
      selected ? 'left-[calc((100vw-430px)/2)] w-[min(560px,calc(100vw-480px))]' : 'left-1/2 w-[min(560px,calc(100vw-40px))]')}>
      <AnimatePresence>
        {asked && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
            className="glass pointer-events-auto mb-2 rounded-2xl p-3">
            <div className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-md bg-[#0b1220] px-3 py-2 text-[13px] leading-snug text-white">{asked}</p>
            </div>
            <div className="mt-2.5 flex gap-2.5">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-black/10">
                <OpenAIMark className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1 py-1.5">
                  {[0, 1, 2].map((i) => (
                    <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-ink-3"
                      animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }} />
                  ))}
                </div>
                <p className="text-[12px] leading-snug text-ink-3">
                  Preview: in the full version an OpenAI model answers here using only the atlas’s sourced connections,
                  citing every edge it relies on, and saying clearly when the evidence is missing.
                </p>
              </div>
              <button onClick={() => setAsked(null)} aria-label="Close answer" className="h-6 w-6 shrink-0 rounded-full text-ink-3 hover:bg-black/5">
                <X size={13} className="mx-auto" />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {focused && !text && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }}
            className="pointer-events-auto mb-2 flex flex-wrap gap-1.5">
            {ideas.map((q) => (
              <button key={q} onMouseDown={(e) => { e.preventDefault(); setText(q) }}
                className="glass flex items-center gap-1.5 rounded-full px-3 py-1.5 text-left text-[12px] text-ink-2 hover:text-ink">
                <Sparkles size={12} className="shrink-0 text-accent" />{q}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      <form onSubmit={(e) => { e.preventDefault(); send(text || ideas[0]) }}
        className="glass pointer-events-auto flex items-center gap-2.5 rounded-2xl py-2 pl-2.5 pr-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-white ring-1 ring-black/10">
          <OpenAIMark className="h-[18px] w-[18px]" />
        </span>
        <input value={text} onChange={(e) => setText(e.target.value)} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          placeholder={`Ask about ${context}… e.g. “${ideas[0]}”`}
          className="min-w-0 flex-1 truncate bg-transparent text-[13.5px] text-ink placeholder:text-ink-3 outline-none" />
        <span className="hidden shrink-0 rounded-full bg-subtle px-2 py-0.5 text-[10.5px] font-medium text-ink-3 xl:inline">GPT · sourced answers</span>
        <button type="submit" aria-label="Ask"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-[#0b1220] text-white transition-opacity hover:opacity-85">
          <ArrowUp size={16} strokeWidth={2.4} />
        </button>
      </form>
    </div>
  )
}
