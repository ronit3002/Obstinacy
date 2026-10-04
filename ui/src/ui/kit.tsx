import { Check, ChevronDown, ChevronRight, Copy } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { ReactNode } from 'react'

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

/** Collapsible section; header doubles as the toggle. */
export function Section({ title, count, children, defaultOpen = true, action }: {
  title: string; count?: number; children: ReactNode; defaultOpen?: boolean; action?: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="border-t border-line first:border-t-0">
      <div className="flex items-center gap-2 py-3">
        <button onClick={() => setOpen(!open)} className="group flex flex-1 items-center gap-1.5 text-left">
          <ChevronDown size={15} strokeWidth={2.4}
            className={cx('text-ink-3 transition-transform duration-200', !open && '-rotate-90')} />
          <span className="text-[13px] font-semibold text-ink">{title}</span>
          {count !== undefined && <span className="text-[13px] font-medium text-ink-3">{count}</span>}
        </button>
        {action}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden">
            <div className="pb-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (t: T) => void
}) {
  return (
    <div className="relative flex rounded-[10px] bg-subtle p-[3px]">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={cx('relative z-10 flex-1 rounded-lg px-2 py-1.5 text-[12.5px] font-medium transition-colors',
            value === t.id ? 'text-ink' : 'text-ink-3 hover:text-ink-2')}>
          {value === t.id && (
            <motion.span layoutId="tab-pill" transition={{ type: 'spring', stiffness: 500, damping: 38 }}
              className="absolute inset-0 -z-10 rounded-lg bg-white shadow-[0_1px_2px_rgba(15,23,42,0.08),0_0_0_0.5px_rgba(15,23,42,0.06)]" />
          )}
          {t.label}{t.count !== undefined && <span className="ml-1 text-ink-3">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function Stat({ label, value, hint, color }: { label: string; value: ReactNode; hint?: ReactNode; color?: string }) {
  return (
    <div className="min-w-0 flex-1 rounded-xl bg-subtle px-3 py-2.5">
      <p className="text-[11px] font-medium text-ink-3">{label}</p>
      <p className="mt-0.5 truncate text-[17px] font-semibold tracking-tight" style={{ color: color ?? 'var(--color-ink)' }}>{value}</p>
      {hint && <p className="truncate text-[11px] text-ink-3">{hint}</p>}
    </div>
  )
}

export function Badge({ children, color = '#64748b', icon }: { children: ReactNode; color?: string; icon?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-[3px] text-[11.5px] font-medium"
      style={{ background: color + '14', color }}>
      {icon}{children}
    </span>
  )
}

export function Chip({ children, color, onClick }: { children: ReactNode; color?: string; onClick?: () => void }) {
  const C = onClick ? 'button' : 'span'
  return (
    <C onClick={onClick}
      className={cx('inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-1 text-[12.5px] text-ink-2',
        onClick && 'transition-colors hover:border-[#c9d3e3] hover:text-ink')}>
      {color && <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />}
      {children}
    </C>
  )
}

/** Three-bar strength indicator (weak / moderate / strong). */
export function Strength({ level, color = '#f43f6b' }: { level: 'weak' | 'moderate' | 'strong' | string; color?: string }) {
  const n = level === 'strong' ? 3 : level === 'moderate' ? 2 : 1
  return (
    <span className="inline-flex items-end gap-[2px]" title={`${level} overlap`}>
      {[1, 2, 3].map((i) => (
        <span key={i} className="w-[4px] rounded-sm" style={{ height: 4 + i * 3, background: i <= n ? color : '#e2e7ef' }} />
      ))}
    </span>
  )
}

export function Row({ leading, title, subtitle, trailing, onClick }: {
  leading?: ReactNode; title: ReactNode; subtitle?: ReactNode; trailing?: ReactNode; onClick?: () => void
}) {
  const inner = (
    <>
      {leading}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] font-medium text-ink">{title}</span>
        {subtitle && <span className="mt-0.5 block truncate text-[12px] text-ink-3">{subtitle}</span>}
      </span>
      {trailing}
      {onClick && <ChevronRight size={15} className="shrink-0 text-ink-3 transition-transform group-hover:translate-x-0.5" />}
    </>
  )
  const cls = 'group -mx-2 flex w-[calc(100%+16px)] items-center gap-3 rounded-xl px-2 py-2 text-left'
  return onClick
    ? <button onClick={onClick} className={cls + ' transition-colors hover:bg-subtle'}>{inner}</button>
    : <div className={cls}>{inner}</div>
}

/** Text clamped to a few lines with a "More" toggle. */
export function Clamp({ children, lines = 3 }: { children: string; lines?: number }) {
  const [open, setOpen] = useState(false)
  const long = children.length > lines * 70
  return (
    <div>
      <p className="text-[14px] leading-[1.6] text-ink-2"
        style={!open && long ? { display: '-webkit-box', WebkitLineClamp: lines, WebkitBoxOrient: 'vertical', overflow: 'hidden' } : undefined}>
        {children}
      </p>
      {long && (
        <button onClick={() => setOpen(!open)} className="mt-1 text-[13px] font-medium text-accent hover:underline">
          {open ? 'Less' : 'More'}
        </button>
      )}
    </div>
  )
}

export function CopyId({ id }: { id: string }) {
  const [done, setDone] = useState(false)
  return (
    <button title="Copy identifier"
      onClick={() => { navigator.clipboard?.writeText(id); setDone(true); setTimeout(() => setDone(false), 1200) }}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[11px] text-ink-3 hover:bg-subtle hover:text-ink-2">
      {id}{done ? <Check size={11} /> : <Copy size={11} />}
    </button>
  )
}

export function Callout({ icon, title, children, color = '#2f6bff' }: {
  icon: ReactNode; title: string; children: ReactNode; color?: string
}) {
  return (
    <div className="flex gap-3 rounded-xl p-3" style={{ background: color + '0d', boxShadow: `inset 0 0 0 1px ${color}1f` }}>
      <span className="mt-0.5 shrink-0" style={{ color }}>{icon}</span>
      <div>
        <p className="text-[13px] font-semibold text-ink">{title}</p>
        <div className="mt-0.5 text-[12.5px] leading-relaxed text-ink-2">{children}</div>
      </div>
    </div>
  )
}

/** "Show N more" wrapper for long chip/row lists. */
export function More<T>({ items, initial, render, wrap = 'flex flex-wrap gap-1.5' }: {
  items: T[]; initial: number; render: (t: T) => ReactNode; wrap?: string
}) {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, initial)
  return (
    <>
      <div className={wrap}>{shown.map(render)}</div>
      {items.length > initial && (
        <button onClick={() => setAll(!all)} className="mt-2 text-[13px] font-medium text-accent hover:underline">
          {all ? 'Show less' : `Show ${items.length - initial} more`}
        </button>
      )}
    </>
  )
}
