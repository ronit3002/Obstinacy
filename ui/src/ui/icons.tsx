import {
  Activity, BookOpen, CircleDot, Dna, FileText, FlaskConical, GraduationCap, Database, Pill, Stethoscope, Users, Workflow,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { TYPE_COLOR } from '../graph/model'

export const TYPE_ICON: Record<string, LucideIcon> = {
  Disease: Activity,
  Gene: Dna,
  Variant: CircleDot,
  Phenotype: Stethoscope,
  Mechanism: Workflow,
  Paper: FileText,
  Claim: BookOpen,
  PatientOrg: Users,
  Registry: Database,
  Study: FlaskConical,
  Researcher: GraduationCap,
  Intervention: Pill,
}

/** Small rounded tile with the type's icon, used in lists and search results. */
export function TypeTile({ type, size = 28 }: { type: string; size?: number }) {
  const Icon = TYPE_ICON[type] ?? CircleDot
  const c = TYPE_COLOR[type] ?? '#64748b'
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-lg"
      style={{ width: size, height: size, background: c + '14', color: c }}>
      <Icon size={size * 0.55} strokeWidth={2.2} />
    </span>
  )
}
