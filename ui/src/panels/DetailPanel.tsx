import {
  AlertTriangle, ArrowLeft, ArrowRight, BadgeCheck, CircleSlash, ExternalLink, Info, Lightbulb, Quote, ShieldCheck, Sparkles, X,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import {
  STRENGTH_CUTOFFS, TYPE_COLOR, TYPE_LABEL, externalLinks, neighbours, nodeLabel, strengthOf, titleCase,
} from '../graph/model'
import type { Model } from '../graph/model'
import { useStore } from '../store'
import type { GEdge, GNode } from '../types'
import { TYPE_ICON, TypeTile } from '../ui/icons'
import { Badge, Callout, Chip, Clamp, CopyId, More, Row, Section, Stat, Strength, Tabs } from '../ui/kit'

const STATUS: Record<string, { label: string; color: string }> = {
  observation: { label: 'Observed', color: '#12b886' },
  inference: { label: 'Inferred', color: '#f59f00' },
  hypothesis: { label: 'Hypothesis', color: '#8a94a6' },
}

const PendingBadge = () => <Badge color="#d97706" icon={<AlertTriangle size={11} />}>AI-verified · no human review</Badge>
const reviewBadge = (n: GNode) =>
  n.review_status === 'ai_curated'
    ? <Badge color="#2f6bff" icon={<Quote size={11} />}>AI-curated · quote verified</Badge>
    : n.review_status === 'approved' || n.review_status === 'curated'
    ? <Badge color="#12b886" icon={<BadgeCheck size={11} />}>Expert reviewed</Badge>
    : <Badge color="#d97706" icon={<AlertTriangle size={11} />}>AI-verified · no human review</Badge>

/* ---------------------------------------------------------------- header -- */

function Header({ n, meta, title }: { n: GNode; meta?: ReactNode; title?: string }) {
  const Icon = TYPE_ICON[n.type]
  const c = TYPE_COLOR[n.type]
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold" style={{ color: c }}>
          {Icon && <Icon size={14} strokeWidth={2.4} />}{TYPE_LABEL[n.type] ?? n.type}
        </span>
        {!n.source_local && <CopyId id={String(n.source_id ?? n.id)} />}
      </div>
      <h2 className="mt-1.5 text-[21px] font-semibold leading-[1.2] tracking-[-0.02em] text-ink">{title ?? titleCase(n.name)}</h2>
      {meta && <div className="mt-2 flex flex-wrap items-center gap-1.5">{meta}</div>}
    </div>
  )
}

function SourcesList({ n }: { n: GNode }) {
  const links = externalLinks(n)
  if (!links.length) return <p className="text-[13px] text-ink-3">No external records linked.</p>
  return (
    <div>
      {links.map((l) => (
        <a key={l.url} href={l.url} target="_blank" rel="noreferrer"
          className="group -mx-2 flex items-center gap-3 rounded-xl px-2 py-2 transition-colors hover:bg-subtle">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-subtle text-[11px] font-semibold text-ink-2">
            {l.label.slice(0, 2).toUpperCase()}
          </span>
          <span className="flex-1 text-[13.5px] font-medium text-ink">{l.label}</span>
          <ExternalLink size={14} className="text-ink-3 group-hover:text-accent" />
        </a>
      ))}
    </div>
  )
}

function PaperRows({ papers }: { papers: { node: GNode; edge: GEdge }[] }) {
  const { reveal } = useStore()
  return (
    <>
      {papers.map(({ node, edge }) => (
        <Row key={node.id} leading={<TypeTile type="Paper" />} title={node.name}
          subtitle={<>{String(node.source_id ?? node.id)}{edge.link_reason ? ` · ${String(edge.link_reason)}` : ''}</>}
          trailing={node.review_status === 'approved' || node.review_status === 'curated' ? undefined : <AlertTriangle size={14} className="text-[#d97706]" />}
          onClick={() => reveal(node.id)} />
      ))}
    </>
  )
}

/** Neighbours of types we don't have data for yet get an honest empty state. */
function OtherConnections({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const groups: [string, string][] = [['Mechanism', 'Mechanisms']]
  const nb = neighbours(m, n.id)
  const present = groups.map(([t, title]) => ({ t, title, items: nb.filter((x) => x.node.type === t) })).filter((g) => g.items.length)
  const missing = groups.filter(([t]) => !nb.some((x) => x.node.type === t)).map(([, title]) => title.toLowerCase())
  return (
    <>
      {present.map((g) => (
        <Section key={g.t} title={g.title} count={g.items.length}>
          {g.items.map((x) => (
            <Row key={x.node.id} leading={<TypeTile type={x.node.type} />} title={nodeLabel(x.node)}
              trailing={<Badge color={STATUS[x.edge.status]?.color}>{STATUS[x.edge.status]?.label}</Badge>}
              onClick={() => reveal(x.node.id)} />
          ))}
        </Section>
      ))}
      {missing.length > 0 && (
        <div className="mt-3">
          <Callout icon={<Info size={16} />} title="Not in the atlas yet" color="#8a94a6">
            No {missing.join(', ')} are linked to this {TYPE_LABEL[n.type]?.toLowerCase()} yet. Absence here means
            “not collected”, not “does not exist”.
          </Callout>
        </div>
      )}
    </>
  )
}

/** "Show on map" that turns into "Hide from map" once the nodes are visible. */
function MapToggle({ ids, label = 'Show on map' }: { ids: string[]; label?: string }) {
  const { visible, toggleNodes } = useStore()
  if (!ids.length) return null
  const shown = ids.every((i) => visible.has(i))
  return (
    <button onClick={() => toggleNodes(ids)} className="text-[12.5px] font-medium text-accent hover:underline">
      {shown ? 'Hide from map' : label}
    </button>
  )
}

const MECH_KIND: Record<string, string> = { effect: 'Effect on the protein', process: 'Biological process' }

/** Disease -> mechanism rows with the quoted evidence, used on disease and mechanism cards. */
function MechanismRows({ links, show }: { links: { node: GNode; edge: GEdge }[]; show: 'mechanism' | 'disease' }) {
  const { reveal, select } = useStore()
  return (
    <>
      {links.map(({ node, edge }) => {
        const ev = (edge.evidence as { pmid: string; quote: string }[]) ?? []
        return (
          <div key={edge.id} className="border-b border-line py-2.5 last:border-b-0">
            <Row leading={<TypeTile type={show === 'mechanism' ? 'Mechanism' : 'Disease'} />}
              title={show === 'mechanism' ? node.name : nodeLabel(node)}
              subtitle={show === 'mechanism' ? MECH_KIND[String(node.kind)] ?? 'Mechanism' : titleCase(node.name)}
              trailing={edge.variant_dependent ? <Badge color="#f59f00">depends on variant</Badge> : undefined}
              onClick={() => reveal(node.id)} />
            {ev[0] && (
              <button onClick={() => select({ kind: 'edge', id: edge.id })}
                className="mt-1 block w-full rounded-lg bg-subtle px-3 py-2 text-left text-[12px] italic leading-snug text-ink-2 hover:bg-[#eef1f6]">
                “{ev[0].quote.length > 180 ? ev[0].quote.slice(0, 178) + '…' : ev[0].quote}”
                <span className="mt-1 block not-italic text-ink-3">{ev[0].pmid}{ev.length > 1 ? ` + ${ev.length - 1} more` : ''}</span>
              </button>
            )}
            {!ev[0] && edge.supported_by ? <p className="mt-1 text-[11.5px] text-ink-3">Curated by a team member from a paper quote.</p> : null}
          </div>
        )
      })}
    </>
  )
}

/* ------------------------------------------------------- assets helpers -- */

const TRIAL_STATUS: Record<string, { label: string; color: string }> = {
  RECRUITING: { label: 'Recruiting', color: '#12b886' },
  NOT_YET_RECRUITING: { label: 'Not yet recruiting', color: '#2f6bff' },
  ENROLLING_BY_INVITATION: { label: 'By invitation', color: '#2f6bff' },
  ACTIVE_NOT_RECRUITING: { label: 'Active', color: '#f59f00' },
  COMPLETED: { label: 'Completed', color: '#8a94a6' },
  TERMINATED: { label: 'Terminated', color: '#e03131' },
  WITHDRAWN: { label: 'Withdrawn', color: '#e03131' },
  SUSPENDED: { label: 'Suspended', color: '#e03131' },
}
const trialStatus = (s: unknown) =>
  TRIAL_STATUS[String(s)] ?? { label: titleCase(String(s || 'unknown').toLowerCase().replace(/_/g, ' ')), color: '#8a94a6' }
const phaseText = (p: unknown) => {
  const ph = (p as string[]) ?? []
  return ph.length && ph[0] !== 'NA'
    ? ph.map((x) => x.replace('EARLY_PHASE', 'Early phase ').replace('PHASE', 'Phase ')).join('/')
    : 'Observational / other'
}
const money = (v: unknown) => (typeof v === 'number' && v > 0 ? `$${v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : Math.round(v / 1e3) + 'k'}` : '')
const isActiveTrial = (n: GNode) =>
  ['RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION', 'ACTIVE_NOT_RECRUITING'].includes(String(n.status))

function TrialRows({ trials, limit = 5 }: { trials: GNode[]; limit?: number }) {
  const { reveal } = useStore()
  const sorted = [...trials].sort((a, b) => Number(isActiveTrial(b)) - Number(isActiveTrial(a)))
  return (
    <More items={sorted} initial={limit} wrap="" render={(t) => {
      const st = trialStatus(t.status)
      return (
        <Row key={t.id} leading={<TypeTile type="Study" />} title={t.name}
          subtitle={`${phaseText(t.phases)}${t.sponsor ? ' · ' + String(t.sponsor) : ''}`}
          trailing={<Badge color={st.color}>{st.label}</Badge>} onClick={() => reveal(t.id)} />
      )
    }} />
  )
}

function OrgRows({ orgs }: { orgs: GNode[] }) {
  const { reveal } = useStore()
  return (
    <>
      {orgs.map((o) => (
        <Row key={o.id} leading={<TypeTile type="PatientOrg" />} title={o.name}
          subtitle={`${String(o.org_kind ?? 'Patient group')} · ${String(o.directory ?? '')}${o.members ? ` · ${o.members} members` : ''}`}
          onClick={() => reveal(o.id)} />
      ))}
    </>
  )
}

function GrantRows({ grants, m }: { grants: GNode[]; m: Model }) {
  const { reveal } = useStore()
  return (
    <More items={grants} initial={4} wrap="" render={(g) => {
      const pis = neighbours(m, g.id, ['Researcher']).map((x) => x.node.name)
      return (
        <Row key={g.id} leading={<TypeTile type="Grant" />} title={g.name}
          subtitle={`${pis.slice(0, 2).join(', ') || 'PI not listed'} · ${String(g.organization ?? '')}`}
          trailing={<span className="text-[11.5px] tabular-nums text-ink-3">FY{String(g.fiscal_year ?? '')}</span>}
          onClick={() => reveal(g.id)} />
      )
    }} />
  )
}

const BRIDGE_KINDS: [string, string, string][] = [
  ['shared_gene_groups', 'Gene family', 'GeneGroup'],
  ['shared_studies', 'Same trial or registry', 'Study'],
  ['shared_interventions', 'Same drug tested', 'Intervention'],
  ['shared_researchers', 'Same NIH-funded researcher', 'Researcher'],
  ['shared_orgs', 'Same patient organisation', 'PatientOrg'],
]

function BridgeRows({ n, m }: { n: GNode; m: Model }) {
  const { select } = useStore()
  const bridges = neighbours(m, n.id).filter((x) => x.edge.rel === 'DISEASE_BRIDGE')
  if (!bridges.length) {
    return <p className="text-[13px] text-ink-3">No shared gene family, trial, drug, researcher or patient group with another mapped disease.</p>
  }
  return (
    <>
      {bridges.map(({ node, edge }) => (
        <Row key={edge.id} leading={<TypeTile type="Disease" />} title={nodeLabel(node)}
          subtitle={BRIDGE_KINDS.filter(([k]) => ((edge[k] as unknown[]) ?? []).length).map(([, l]) => l).join(' · ')}
          trailing={<Badge color="#7c3aed">{String(edge.connection_label)}</Badge>}
          onClick={() => select({ kind: 'edge', id: edge.id })} />
      ))}
    </>
  )
}

/** A disease's genes -> NIH grants that mention them. */
const grantsForDisease = (n: GNode, m: Model) =>
  neighbours(m, n.id, ['Gene']).flatMap((g) => neighbours(m, g.node.id, ['Grant']).map((x) => x.node))

/* --------------------------------------------------------------- disease -- */

function DiseaseCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal, select } = useStore()
  const [tab, setTab] = useState<'overview' | 'action' | 'connections' | 'sources'>('overview')
  const nb = neighbours(m, n.id)
  const genes = nb.filter((x) => x.node.type === 'Gene')
  const papers = nb.filter((x) => x.node.type === 'Paper')
  const trials = nb.filter((x) => x.node.type === 'Study').map((x) => x.node)
  const orgs = nb.filter((x) => x.node.type === 'PatientOrg').map((x) => x.node)
  const grants = grantsForDisease(n, m)
  const bridges = nb.filter((x) => x.edge.rel === 'DISEASE_BRIDGE')
  const reading = (n.reading as { pmid: string; title: string; year: string; journal: string }[]) ?? []
  // one row per mechanism (a team-curated and an AI-curated edge for the same pair are shown once)
  const mechanisms = nb.filter((x) => x.node.type === 'Mechanism')
    .sort((a, b) => Number(Boolean(b.edge.evidence)) - Number(Boolean(a.edge.evidence)))
    .filter((x, i, all) => all.findIndex((y) => y.node.id === x.node.id) === i)
  const similar = nb.filter((x) => x.edge.rel === 'DISEASE_MATCH').sort((a, b) => (b.edge.score as number) - (a.edge.score as number))
  // symptoms that also appear in other diseases are the interesting ones: rank them first
  const symptoms = nb.filter((x) => x.node.type === 'Phenotype').map((x) => ({
    node: x.node, shared: neighbours(m, x.node.id, ['Disease']).length - 1,
  })).sort((a, b) => b.shared - a.shared)
  const top = similar[0]
  const about = typeof n.definition === 'string' ? n.definition : ''

  return (
    <>
      <Header n={n} meta={genes.map((g) => (
        <Chip key={g.node.id} color={TYPE_COLOR.Gene} onClick={() => reveal(g.node.id)}>{g.node.name}</Chip>
      ))} />

      <div className="mt-4 flex gap-2">
        <Stat label="Closest match" value={top ? nodeLabel(top.node) : '—'}
          hint={top ? <span className="inline-flex items-center gap-1.5"><Strength level={strengthOf(top.edge.score as number)} />{String(top.edge.connection_label)}</span> : 'none above threshold'} />
        <Stat label="Trials" value={trials.length} hint={`${trials.filter(isActiveTrial).length} active`} />
        <Stat label="Groups" value={orgs.length} hint={orgs.length ? 'patient groups' : 'none found'} />
      </div>

      <div className="mt-4"><Tabs value={tab} onChange={setTab} tabs={[
        { id: 'overview', label: 'Overview' }, { id: 'action', label: 'Take action' },
        { id: 'connections', label: 'Links', count: similar.length + bridges.length },
        { id: 'sources', label: 'Sources' }]} /></div>

      <div className="mt-2">
        {tab === 'action' && (
          <>
            <Section title="Patient groups & communities" count={orgs.length}>
              {orgs.length ? <OrgRows orgs={orgs} /> : (
                <Callout icon={<Info size={16} />} title="No patient group found yet" color="#8a94a6">
                  None of the directories we searched (NORD, RareConnect) list a group for this disease. That does not
                  mean none exists: gene-specific foundations are often missing from directories.
                </Callout>
              )}
            </Section>
            <Section title="Clinical trials & registries" count={trials.length}>
              {trials.length ? <TrialRows trials={trials} /> : <p className="text-[13px] text-ink-3">No matching study on ClinicalTrials.gov.</p>}
              <p className="mt-2 text-[11.5px] text-ink-3">From ClinicalTrials.gov. A study counts if its conditions or title name this disease or its gene.</p>
            </Section>
            <Section title="Researchers & funding" count={grants.length}>
              {grants.length ? <GrantRows grants={grants} m={m} /> : <p className="text-[13px] text-ink-3">No recent NIH-funded project mentions this gene.</p>}
              <p className="mt-2 text-[11.5px] text-ink-3">NIH RePORTER projects (2022–2026) whose text mentions {genes.map((g) => g.node.name).join(', ')}.</p>
            </Section>
            <Section title="Shared with other diseases" count={bridges.length}>
              <BridgeRows n={n} m={m} />
            </Section>
          </>
        )}

        {tab === 'overview' && (
          <>
            {about && <Section title="About"><Clamp>{about}</Clamp><p className="mt-2 text-[11.5px] text-ink-3">Definition from MONDO</p></Section>}
            <Section title="Mechanism" count={mechanisms.length}>
              {mechanisms.length ? <MechanismRows links={mechanisms} show="mechanism" />
                : <p className="text-[13px] text-ink-3">No mechanism with a quoted source yet.</p>}
              {mechanisms.some((x) => x.edge.variant_dependent) && (
                <p className="mt-2 text-[11.5px] leading-snug text-ink-3">Different variants in this gene act differently (some gain, some lose function), so the right research path depends on the child’s specific variant.</p>
              )}
            </Section>
            {papers.length > 0 && (
              <Section title="Research" count={papers.length}>
                <PaperRows papers={papers} />
              </Section>
            )}
            <Section title="Symptoms" count={symptoms.length}
              action={<MapToggle ids={symptoms.map((s) => s.node.id)} />}>
              <More items={symptoms} initial={8} render={(s) => (
                <Chip key={s.node.id} color={TYPE_COLOR.Phenotype} onClick={() => reveal(s.node.id)}>
                  {s.node.name}{s.shared > 0 && <span className="text-ink-3">· {s.shared + 1}</span>}
                </Chip>
              )} />
              <p className="mt-2 text-[11.5px] text-ink-3">The number shows how many mapped diseases share the symptom (HPO annotations).</p>
            </Section>
            {Array.isArray(n.synonyms) && n.synonyms.length > 0 && (
              <Section title="Also known as" count={(n.synonyms as string[]).length} defaultOpen={false}>
                <div className="flex flex-wrap gap-1.5">{(n.synonyms as string[]).map((s) => <Chip key={s}>{s}</Chip>)}</div>
              </Section>
            )}
          </>
        )}

        {tab === 'connections' && (
          <>
            <Section title="Similar diseases" count={similar.length}>
              {similar.length ? similar.map(({ node, edge }) => (
                <Row key={edge.id} leading={<TypeTile type="Disease" />} title={nodeLabel(node)}
                  subtitle={((edge.informative_phenotypes as string[]) ?? []).slice(0, 3).join(' · ') || String(edge.connection_label)}
                  trailing={<span className="flex items-center gap-2 text-[12px] font-medium tabular-nums text-ink-2">{Math.round(edge.score as number)}<Strength level={strengthOf(edge.score as number)} /></span>}
                  onClick={() => select({ kind: 'edge', id: edge.id })} />
              )) : <p className="text-[13px] text-ink-3">No other mapped disease reaches the match threshold (score 20).</p>}
              <p className="mt-2 text-[11.5px] leading-snug text-ink-3">Match score 0–100. Tap a disease to see why they are connected.</p>
            </Section>
            <Section title="Gene" count={genes.length}>
              {genes.map((g) => (
                <Row key={g.node.id} leading={<TypeTile type="Gene" />} title={g.node.name} subtitle={String(g.node.full_name ?? '')}
                  trailing={<Badge color={STATUS[g.edge.status]?.color}>{STATUS[g.edge.status]?.label}</Badge>}
                  onClick={() => reveal(g.node.id)} />
              ))}
            </Section>
            <Section title="Shared assets" count={bridges.length}><BridgeRows n={n} m={m} /></Section>
            {papers.length > 0 && <Section title="Papers" count={papers.length}><PaperRows papers={papers} /></Section>}
            <OtherConnections n={n} m={m} />
          </>
        )}

        {tab === 'sources' && (
          <>
            <Section title="External records"><SourcesList n={n} /></Section>
            <Section title="Where this data comes from">
              <Row leading={<TypeTile type="Disease" />} title="MONDO" subtitle="Disease identity, synonyms, definition" />
              <Row leading={<TypeTile type="Phenotype" />} title="Human Phenotype Ontology" subtitle={`${symptoms.length} symptom annotations`} />
              <Row leading={<TypeTile type="Gene" />} title="HGNC" subtitle="Gene identity and aliases" />
              {papers.length > 0 && <Row leading={<TypeTile type="Paper" />} title="PubMed abstracts" subtitle="Claims extracted by an AI model with verbatim evidence" />}
              <Row leading={<TypeTile type="Study" />} title="ClinicalTrials.gov" subtitle={`${trials.length} studies`} />
              <Row leading={<TypeTile type="PatientOrg" />} title="NORD · RareConnect" subtitle={`${orgs.length} patient groups`} />
              <Row leading={<TypeTile type="Grant" />} title="NIH RePORTER" subtitle={`${grants.length} funded projects`} />
            </Section>
            {reading.length > 0 && (
              <Section title="Further reading" count={reading.length} defaultOpen={false}>
                {reading.map((r) => (
                  <a key={r.pmid} href={`https://pubmed.ncbi.nlm.nih.gov/${r.pmid}/`} target="_blank" rel="noreferrer"
                    className="group -mx-2 flex items-start gap-3 rounded-xl px-2 py-2 hover:bg-subtle">
                    <TypeTile type="Paper" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] leading-snug text-ink">{r.title}</span>
                      <span className="block text-[11.5px] text-ink-3">{r.journal} · {r.year}</span>
                    </span>
                    <ExternalLink size={14} className="mt-1 shrink-0 text-ink-3 group-hover:text-accent" />
                  </a>
                ))}
                <p className="mt-2 text-[11.5px] text-ink-3">Curated references from NIH RARe-SOURCE (GARD {String(n.gard_id ?? '')}).</p>
              </Section>
            )}
          </>
        )}
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ gene -- */

function GeneCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const [tab, setTab] = useState<'overview' | 'connections' | 'sources'>('overview')
  const nb = neighbours(m, n.id)
  const diseases = nb.filter((x) => x.node.type === 'Disease')
  const variants = nb.filter((x) => x.node.type === 'Variant')
  const claims = nb.filter((x) => x.node.type === 'Claim')
  const families = nb.filter((x) => x.node.type === 'GeneGroup').map((x) => x.node)
  const topVariants = (n.top_variants as { id: string; name: string; score: number; classification: string; consequence: string; reasons: string[] }[]) ?? []
  const grants = nb.filter((x) => x.node.type === 'Grant').map((x) => x.node)
  const counts = Object.entries((n.variant_counts as Record<string, number>) ?? {}).sort((a, b) => b[1] - a[1])
  const total = counts.reduce((s, [, v]) => s + v, 0) || 1
  const pathogenic = counts.filter(([k]) => /^pathogenic/i.test(k)).reduce((s, [, v]) => s + v, 0)
  const palette = ['#f43f6b', '#f59f00', '#8b5cf6', '#2f6bff', '#94a3b8']

  return (
    <>
      <Header n={n} meta={<span className="text-[13px] text-ink-2">{String(n.full_name ?? '')}</span>} />
      <div className="mt-4 flex gap-2">
        <Stat label="Diseases" value={diseases.length} />
        <Stat label="Variants" value={variants.length} hint="ClinVar" />
        <Stat label="Pathogenic" value={pathogenic} color="#f43f6b" />
      </div>
      <div className="mt-4"><Tabs value={tab} onChange={setTab} tabs={[
        { id: 'overview', label: 'Overview' }, { id: 'connections', label: 'Connections', count: diseases.length + claims.length },
        { id: 'sources', label: 'Sources' }]} /></div>

      <div className="mt-2">
        {tab === 'overview' && (
          <>
            {families.length > 0 && (
              <Section title="Gene family" count={families.length}>
                {families.map((f) => {
                  const others = neighbours(m, f.id, ['Gene']).filter((x) => x.node.id !== n.id)
                  return (
                    <Row key={f.id} leading={<TypeTile type="GeneGroup" />} title={f.name}
                      subtitle={others.length ? `Also in the atlas: ${others.map((x) => x.node.name).join(', ')}` : 'No other mapped gene in this family'}
                      onClick={() => reveal(f.id)} />
                  )
                })}
                <p className="mt-2 text-[11.5px] text-ink-3">Curated HGNC gene groups: different gene names that build the same kind of protein.</p>
              </Section>
            )}
            {claims.length > 0 && (
              <Section title="What papers say" count={claims.length}>
                {claims.map((c) => <ClaimRow key={c.node.id} c={c.node} />)}
              </Section>
            )}
            {topVariants.length > 0 && (
              <Section title="Top variants" count={topVariants.length}
                action={<MapToggle ids={topVariants.map((v) => v.id)} label="Show top 5 on map" />}>
                {topVariants.map((v, i) => {
                  const protein = /\((p\.[^)]+)\)/.exec(v.name)?.[1]
                  const cdna = /:(c\.[^ ]+)/.exec(v.name)?.[1]
                  return (
                    <button key={v.id} onClick={() => reveal(v.id)}
                      className="group -mx-2 flex w-[calc(100%+16px)] items-center gap-3 rounded-xl px-2 py-2 text-left hover:bg-subtle">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#f59f00]/12 text-[12px] font-semibold text-[#c77700]">{i + 1}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13.5px] font-medium text-ink">{protein ?? cdna ?? v.name}</span>
                        <span className="block truncate text-[11.5px] text-ink-3">{[cdna && protein ? cdna : null, v.classification, v.consequence].filter(Boolean).join(' · ')}</span>
                      </span>
                      <span className="flex w-16 shrink-0 flex-col items-end">
                        <span className="text-[12px] font-semibold tabular-nums text-ink">{v.score}</span>
                        <span className="mt-1 h-1 w-14 overflow-hidden rounded-full bg-subtle">
                          <span className="block h-full rounded-full bg-[#f59f00]" style={{ width: `${v.score}%` }} />
                        </span>
                      </span>
                    </button>
                  )
                })}
                <p className="mt-2 text-[11.5px] leading-snug text-ink-3">Display priority (0–100) from ClinVar classification, review strength, trait match and consequence. Not a clinical score.</p>
              </Section>
            )}
            <Section title="Variant classifications" count={variants.length}
              action={<MapToggle ids={variants.map((v) => v.node.id)} />}>
              <div className="flex h-2 overflow-hidden rounded-full bg-subtle">
                {counts.map(([k, v], i) => <span key={k} style={{ width: `${(v / total) * 100}%`, background: palette[i % 5] }} />)}
              </div>
              <div className="mt-3 space-y-1.5">
                {counts.map(([k, v], i) => (
                  <div key={k} className="flex items-center gap-2 text-[13px]">
                    <span className="h-2 w-2 rounded-full" style={{ background: palette[i % 5] }} />
                    <span className="flex-1 text-ink-2">{k}</span><span className="font-medium tabular-nums text-ink">{v}</span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[11.5px] leading-snug text-ink-3">ClinVar classifications describe pathogenicity, not whether a variant causes loss or gain of function.</p>
            </Section>
            {Array.isArray(n.aliases) && n.aliases.length > 0 && (
              <Section title="Also known as" count={(n.aliases as string[]).length} defaultOpen={false}>
                <div className="flex flex-wrap gap-1.5">{(n.aliases as string[]).map((s) => <Chip key={s}>{s}</Chip>)}</div>
              </Section>
            )}
          </>
        )}
        {tab === 'connections' && (
          <>
            <Section title="Diseases" count={diseases.length}>
              {diseases.map((d) => (
                <Row key={d.node.id} leading={<TypeTile type="Disease" />} title={nodeLabel(d.node)} subtitle={titleCase(d.node.name)}
                  trailing={<Badge color={STATUS[d.edge.status]?.color}>{STATUS[d.edge.status]?.label}</Badge>}
                  onClick={() => reveal(d.node.id)} />
              ))}
              {diseases.length < 2 && <p className="mt-2 text-[11.5px] text-ink-3">No other mapped disease shares this gene.</p>}
            </Section>
            <Section title="NIH-funded research" count={grants.length}>
              {grants.length ? <GrantRows grants={grants} m={m} /> : <p className="text-[13px] text-ink-3">No recent NIH project mentions this gene.</p>}
            </Section>
            <OtherConnections n={n} m={m} />
          </>
        )}
        {tab === 'sources' && <Section title="External records"><SourcesList n={n} /></Section>}
      </div>
    </>
  )
}

/* ------------------------------------------------------- papers & claims -- */

const CATEGORY_LABEL: Record<string, string> = {
  finding: 'Key findings', result: 'Results', study_design: 'Study design', background: 'Background', limitation: 'Limitations',
  mechanism: 'Mechanism',
}

function ClaimRow({ c }: { c: GNode }) {
  const { select } = useStore()
  const negated = c.polarity === 'negated'
  return (
    <button onClick={() => select({ kind: 'node', id: c.id })}
      className="group -mx-2 flex w-[calc(100%+16px)] gap-2.5 rounded-xl px-2 py-2 text-left transition-colors hover:bg-subtle">
      <span className="mt-0.5 shrink-0" style={{ color: negated ? '#8a94a6' : '#12b886' }}>
        {negated ? <CircleSlash size={15} /> : <BadgeCheck size={15} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] leading-snug text-ink">{String(c.statement)}</span>
        <span className="mt-0.5 block text-[11.5px] text-ink-3">{negated ? 'Not shown / negative result · ' : ''}{String(c.pmid ?? '')}</span>
      </span>
    </button>
  )
}

function PaperCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const [tab, setTab] = useState<'summary' | 'claims' | 'sources'>('summary')
  const nb = neighbours(m, n.id)
  const claims = nb.filter((x) => x.node.type === 'Claim').map((x) => x.node)
  const diseases = nb.filter((x) => x.node.type === 'Disease')
  const authors = (n.authors as string[]) ?? []
  const treatments = new Map<string, GNode>()
  claims.forEach((c) => neighbours(m, c.id, ['Intervention']).forEach((x) => treatments.set(x.node.id, x.node)))
  const byCat = Object.entries(CATEGORY_LABEL).map(([k, label]) => ({ k, label, items: claims.filter((c) => c.category === k) })).filter((g) => g.items.length)
  const summary = (n.summary_sentences as string[]) ?? []

  return (
    <>
      <Header n={n} title={n.name} meta={<>{reviewBadge(n)}<Badge color="#64748b">{String(n.source_kind ?? 'paper')}</Badge></>} />
      <div className="mt-4 flex gap-2">
        <Stat label="Claims" value={claims.length} hint="with verbatim evidence" />
        <Stat label="Authors" value={authors.length} />
      </div>
      <div className="mt-4"><Tabs value={tab} onChange={setTab} tabs={[
        { id: 'summary', label: 'Summary' }, { id: 'claims', label: 'Claims', count: claims.length }, { id: 'sources', label: 'Provenance' }]} /></div>

      <div className="mt-2">
        {tab === 'summary' && (
          <>
            {n.review_status !== 'approved' && n.review_status !== 'curated' && (
              <div className="mt-3">
                <Callout icon={<AlertTriangle size={16} />} title="AI-extracted, no human review" color="#d97706">
                  Each claim was checked by a second AI model, and its evidence passage was copied verbatim from the abstract,
                  but no human expert has reviewed it. Read the original before acting on it.
                </Callout>
              </div>
            )}
            <Section title="Plain-language summary">
              {summary.length ? <Clamp lines={6}>{summary.join(' ')}</Clamp> : <p className="text-[13px] text-ink-3">The summary was withheld because it did not pass the audit.</p>}
              <p className="mt-2 inline-flex items-center gap-1 text-[11.5px] text-ink-3"><Sparkles size={12} /> Generated from cited claims · {String(n.model ?? '')}</p>
            </Section>
            {treatments.size > 0 && (
              <Section title="Treatments studied" count={treatments.size}>
                <div className="flex flex-wrap gap-1.5">{[...treatments.values()].map((t) => <Chip key={t.id} color={TYPE_COLOR.Intervention} onClick={() => reveal(t.id)}>{t.name}</Chip>)}</div>
              </Section>
            )}
            <Section title="Linked diseases" count={diseases.length}>
              {diseases.map((d) => <Row key={d.node.id} leading={<TypeTile type="Disease" />} title={nodeLabel(d.node)} subtitle={String(d.edge.link_reason ?? '')} onClick={() => reveal(d.node.id)} />)}
            </Section>
            <Section title="Authors" count={authors.length} defaultOpen={false}>
              <More items={authors} initial={12} render={(a) => <Chip key={a}>{a}</Chip>} />
              <p className="mt-2 text-[11.5px] text-ink-3">Names are not matched across papers, so the same name may be different people.</p>
            </Section>
          </>
        )}
        {tab === 'claims' && (
          <>
            {byCat.map((g) => (
              <Section key={g.k} title={g.label} count={g.items.length}>
                {g.items.map((c) => <ClaimRow key={c.id} c={c} />)}
              </Section>
            ))}
            <div className="mt-2"><MapToggle ids={[...claims.map((c) => c.id), ...treatments.keys()]} label="Show claims on the map" /></div>
          </>
        )}
        {tab === 'sources' && (
          <>
            <Section title="Original paper">
              <a href={String(n.url)} target="_blank" rel="noreferrer"
                className="group -mx-2 flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-subtle">
                <TypeTile type="Paper" /><span className="flex-1 text-[13.5px] font-medium text-ink">PubMed {String(n.source_id ?? n.id).replace('PMID:', '')}</span>
                <ExternalLink size={14} className="text-ink-3 group-hover:text-accent" />
              </a>
            </Section>
            <Section title="How it was processed">
              {[
                ['Extraction model', n.model], ['Verifier model', n.verifier_model], ['Prompt version', n.prompt_version],
                ['Review status', n.review_status], ['Source quality', `Tier ${n.source_tier}`],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between gap-4 py-1 text-[13px]">
                  <span className="text-ink-3">{String(k)}</span><span className="text-right font-medium text-ink">{String(v ?? '–')}</span>
                </div>
              ))}
              {typeof n.scope_note === 'string' && <p className="mt-2 text-[11.5px] text-ink-3">{n.scope_note}</p>}
            </Section>
          </>
        )}
      </div>
    </>
  )
}

function ClaimCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const paper = m.nodes.get(String(n.pmid))
  const negated = n.polarity === 'negated'
  const mentions = (n.mentions as { kind: string; mention: string; canonical_id: string | null }[]) ?? []
  return (
    <>
      <Header n={n} title={String(n.statement)} meta={<>
        {negated ? <Badge color="#8a94a6" icon={<CircleSlash size={11} />}>Negative / not shown</Badge> : <Badge color="#12b886" icon={<BadgeCheck size={11} />}>Affirmed</Badge>}
        <Badge color="#64748b">{CATEGORY_LABEL[String(n.category)] ?? String(n.category)}</Badge>
        {reviewBadge(n)}
      </>} />
      <div className="mt-3">
        <Section title="Evidence from the abstract">
          <div className="relative rounded-xl bg-subtle p-3 pl-9">
            <Quote size={14} className="absolute left-3 top-3.5 text-ink-3" />
            <Clamp lines={5}>{String(n.quote ?? '')}</Clamp>
          </div>
          <p className="mt-2 text-[11.5px] text-ink-3">Passage copied verbatim from the source by code, not written by the model.</p>
        </Section>
        {typeof n.verification === 'string' && (
          <Section title="Verifier’s check" defaultOpen={false}>
            <p className="text-[13px] leading-relaxed text-ink-2">{n.verification}</p>
          </Section>
        )}
        {typeof n.study_context === 'string' && n.study_context && (
          <Section title="Study context"><p className="text-[13px] text-ink-2">{n.study_context}</p></Section>
        )}
        <Section title="Mentions" count={mentions.length}>
          {mentions.map((x, i) => (
            <Row key={i} leading={<TypeTile type={x.kind === 'Outcome' ? 'Claim' : x.kind} />} title={x.mention}
              subtitle={x.canonical_id ?? 'not matched to an ontology ID'}
              onClick={x.canonical_id && m.nodes.has(x.canonical_id) ? () => reveal(x.canonical_id!) : undefined} />
          ))}
        </Section>
        {paper && (
          <Section title="Paper">
            <Row leading={<TypeTile type="Paper" />} title={paper.name} subtitle={String(paper.source_id ?? paper.id)} onClick={() => reveal(paper.id)} />
          </Section>
        )}
      </div>
    </>
  )
}

/* ------------------------------------------------- assets & communities -- */

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <>
      {rows.filter(([, v]) => v !== '' && v !== undefined && v !== null).map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4 py-1 text-[13px]">
          <span className="shrink-0 text-ink-3">{k}</span><span className="text-right font-medium text-ink">{v}</span>
        </div>
      ))}
    </>
  )
}

function LinkedDiseases({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const ds = neighbours(m, n.id, ['Disease'])
  return <>{ds.map((d) => (
    <Row key={d.node.id} leading={<TypeTile type="Disease" />} title={nodeLabel(d.node)}
      subtitle={String(d.edge.match_reason ?? titleCase(d.node.name))} onClick={() => reveal(d.node.id)} />
  ))}</>
}

function StudyCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const st = trialStatus(n.status)
  const drugs = neighbours(m, n.id, ['Intervention']).map((x) => x.node)
  const diseases = neighbours(m, n.id, ['Disease'])
  return (
    <>
      <Header n={n} title={n.name} meta={<><Badge color={st.color}>{st.label}</Badge><Badge color="#4f46e5">{phaseText(n.phases)}</Badge></>} />
      <div className="mt-4 flex gap-2">
        <Stat label="Diseases in atlas" value={diseases.length} />
        <Stat label="Enrolment" value={n.enrollment ? String(n.enrollment) : '–'} hint="participants" />
      </div>
      <div className="mt-3">
        {typeof n.summary === 'string' && n.summary && <Section title="What this study does"><Clamp>{n.summary}</Clamp></Section>}
        <Section title="Details">
          <Facts rows={[
            ['Sponsor', String(n.sponsor ?? '')], ['Started', String(n.start ?? '')],
            ['Type', titleCase(String(n.study_type ?? '').toLowerCase())],
            ['Countries', ((n.countries as string[]) ?? []).slice(0, 6).join(', ')],
          ]} />
        </Section>
        {drugs.length > 0 && (
          <Section title="Treatment tested" count={drugs.length}>
            <div className="flex flex-wrap gap-1.5">{drugs.map((d) => <Chip key={d.id} color={TYPE_COLOR.Intervention} onClick={() => reveal(d.id)}>{d.name}</Chip>)}</div>
          </Section>
        )}
        <Section title="Conditions listed" count={((n.conditions as string[]) ?? []).length} defaultOpen={false}>
          <div className="flex flex-wrap gap-1.5">{((n.conditions as string[]) ?? []).map((c) => <Chip key={c}>{c}</Chip>)}</div>
        </Section>
        <Section title="Linked diseases" count={diseases.length}><LinkedDiseases n={n} m={m} /></Section>
        {diseases.length > 1 && (
          <Callout icon={<Lightbulb size={16} />} title="A shared asset">
            This study already includes several of the mapped diseases. Communities can ask the sponsor how its
            data, protocol or registry could be reused.
          </Callout>
        )}
        <Section title="Source"><SourcesList n={n} /></Section>
      </div>
    </>
  )
}

function OrgCard({ n, m }: { n: GNode; m: Model }) {
  return (
    <>
      <Header n={n} meta={<><Badge color={TYPE_COLOR.PatientOrg}>{String(n.org_kind ?? 'Patient group')}</Badge><Badge color="#64748b">{String(n.directory ?? '')}</Badge></>} />
      {n.members ? <div className="mt-4 flex gap-2"><Stat label="Members" value={String(n.members)} hint="on RareConnect" /></div> : null}
      <div className="mt-3">
        {typeof n.description === 'string' && n.description && <Section title="About"><Clamp>{n.description}</Clamp></Section>}
        <Section title="Supports"><LinkedDiseases n={n} m={m} /></Section>
        <Section title="Contact"><SourcesList n={n} /></Section>
        <p className="mt-2 text-[11.5px] text-ink-3">Listed in the {String(n.directory ?? '')} directory. Check the organisation’s own site for current details.</p>
      </div>
    </>
  )
}

function GrantCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const pis = neighbours(m, n.id, ['Researcher'])
  const genes = neighbours(m, n.id, ['Gene'])
  return (
    <>
      <Header n={n} title={n.name} meta={<><Badge color={TYPE_COLOR.Grant}>{String(n.institute ?? 'NIH')}</Badge><Badge color="#64748b">FY{String(n.fiscal_year ?? '')}</Badge></>} />
      <div className="mt-4 flex gap-2">
        <Stat label="Latest award" value={money(n.award_amount) || '–'} hint="per year" />
        <Stat label="Principal investigators" value={pis.length} />
      </div>
      <div className="mt-3">
        <Section title="Who leads it" count={pis.length}>
          {pis.map((p) => {
            const otherGrants = neighbours(m, p.node.id, ['Grant']).length - 1
            return (
              <Row key={p.node.id} leading={<TypeTile type="Researcher" />} title={p.node.name}
                subtitle={`${String(p.node.organization ?? n.organization ?? '')}${otherGrants > 0 ? ` · ${otherGrants} more project${otherGrants > 1 ? 's' : ''} in the atlas` : ''}`}
                onClick={() => reveal(p.node.id)} />
            )
          })}
        </Section>
        <Section title="Details">
          <Facts rows={[['Organisation', String(n.organization ?? '')], ['Location', [n.city, n.country].filter(Boolean).join(', ')],
            ['Project number', String(n.project_num ?? '')], ['Period', [n.start, n.end].filter(Boolean).join(' – ')]]} />
        </Section>
        <Section title="Related genes" count={genes.length}>
          {genes.map((g) => <Row key={g.node.id} leading={<TypeTile type="Gene" />} title={g.node.name} subtitle={String(g.edge.match_reason ?? '')} onClick={() => reveal(g.node.id)} />)}
        </Section>
        <Section title="Source"><SourcesList n={n} /></Section>
      </div>
    </>
  )
}

function GeneGroupCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const genes = neighbours(m, n.id, ['Gene'])
  const diseases = genes.flatMap((g) => neighbours(m, g.node.id, ['Disease']).map((d) => ({ gene: g.node, d: d.node })))
  return (
    <>
      <Header n={n} />
      <div className="mt-4 flex gap-2">
        <Stat label="Genes in atlas" value={genes.length} />
        <Stat label="Diseases" value={diseases.length} />
      </div>
      <div className="mt-3">
        {genes.length > 1 && (
          <Callout icon={<Lightbulb size={16} />} title="Different names, same building block" color="#ea580c">
            These genes all encode parts of the same protein family, so their diseases may share biology and research,
            even though their names differ.
          </Callout>
        )}
        <Section title="Genes" count={genes.length}>
          {genes.map((g) => <Row key={g.node.id} leading={<TypeTile type="Gene" />} title={g.node.name} subtitle={String(g.node.full_name ?? '')} onClick={() => reveal(g.node.id)} />)}
        </Section>
        <Section title="Diseases" count={diseases.length}>
          {diseases.map(({ gene, d }) => <Row key={d.id} leading={<TypeTile type="Disease" />} title={nodeLabel(d)} subtitle={`via ${gene.name}`} onClick={() => reveal(d.id)} />)}
        </Section>
        <Section title="Source"><SourcesList n={n} /></Section>
      </div>
    </>
  )
}

function InterventionCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const trials = neighbours(m, n.id, ['Study']).map((x) => x.node)
  const claims = neighbours(m, n.id, ['Claim']).map((x) => x.node)
  const diseases = new Map<string, GNode>()
  trials.forEach((t) => neighbours(m, t.id, ['Disease']).forEach((d) => diseases.set(d.node.id, d.node)))
  return (
    <>
      <Header n={n} meta={n.intervention_type ? <Badge color={TYPE_COLOR.Intervention}>{titleCase(String(n.intervention_type))}</Badge> : undefined} />
      <div className="mt-4 flex gap-2">
        <Stat label="Trials" value={trials.length} hint={`${trials.filter(isActiveTrial).length} active`} />
        <Stat label="Diseases" value={diseases.size} hint="in the atlas" />
      </div>
      <div className="mt-3">
        {diseases.size > 1 && (
          <Callout icon={<Lightbulb size={16} />} title="Tested across communities">
            This treatment is being studied in several mapped diseases. Results, dosing and safety data from one
            community’s trial can inform the others.
          </Callout>
        )}
        <Section title="Tested for" count={diseases.size}>
          {[...diseases.values()].map((d) => <Row key={d.id} leading={<TypeTile type="Disease" />} title={nodeLabel(d)} subtitle={titleCase(d.name)} onClick={() => reveal(d.id)} />)}
          {!diseases.size && <p className="text-[13px] text-ink-3">Not linked to a trial in the atlas.</p>}
        </Section>
        {trials.length > 0 && <Section title="Trials" count={trials.length}><TrialRows trials={trials} /></Section>}
        {claims.length > 0 && <Section title="What papers say" count={claims.length}>{claims.map((c) => <ClaimRow key={c.id} c={c} />)}</Section>}
      </div>
    </>
  )
}

function MechanismCard({ n, m }: { n: GNode; m: Model }) {
  const links = neighbours(m, n.id, ['Disease'])
    .sort((a, b) => Number(Boolean(b.edge.evidence)) - Number(Boolean(a.edge.evidence)))
    .filter((x, i, all) => all.findIndex((y) => y.node.id === x.node.id) === i)
  const mixed = links.filter((x) => x.edge.variant_dependent)
  return (
    <>
      <Header n={n} meta={<Badge color={TYPE_COLOR.Mechanism}>{MECH_KIND[String(n.kind)] ?? 'Mechanism'}</Badge>} />
      {typeof n.description === 'string' && <p className="mt-3 text-[14px] leading-relaxed text-ink-2">{n.description}</p>}
      <div className="mt-4 flex gap-2">
        <Stat label="Diseases" value={links.length} hint="with quoted evidence" />
        <Stat label="Variant-dependent" value={mixed.length} hint="gain and loss reported" />
      </div>
      <div className="mt-3">
        {links.length > 1 && (
          <Callout icon={<Lightbulb size={16} />} title="A shared mechanism" color={TYPE_COLOR.Mechanism}>
            These diseases have different gene names but act through this same mechanism, so treatments aimed at the
            mechanism (not the gene) could matter to all of them. It is a lead to check with experts.
          </Callout>
        )}
        <Section title="Diseases" count={links.length}><MechanismRows links={links} show="disease" /></Section>
        <p className="mt-2 text-[11.5px] leading-snug text-ink-3">Each link quotes a sentence copied verbatim from a PubMed abstract and was checked automatically against that abstract. Curation was AI-assisted and still needs expert review.</p>
      </div>
    </>
  )
}

function MechanismEdgeCard({ e, m }: { e: GEdge; m: Model }) {
  const { reveal } = useStore()
  const d = m.nodes.get(e.source)!, mech = m.nodes.get(e.target)!
  const ev = (e.evidence as { pmid: string; quote: string; title: string; year: string }[]) ?? []
  return (
    <>
      <p className="text-[12px] font-semibold" style={{ color: TYPE_COLOR.Mechanism }}>Why this mechanism?</p>
      <h2 className="mt-1 text-[21px] font-semibold leading-tight tracking-[-0.02em] text-ink">{nodeLabel(d)} → {mech.name}</h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {reviewBadge({ ...d, review_status: e.review_status } as GNode)}
        {e.variant_dependent ? <Badge color="#f59f00">depends on the variant</Badge> : null}
      </div>
      <div className="mt-3">
        <Section title="Evidence" count={ev.length}>
          {ev.map((x) => (
            <div key={x.pmid + x.quote.slice(0, 20)} className="mb-3 last:mb-0">
              <div className="relative rounded-xl bg-subtle p-3 pl-9">
                <Quote size={14} className="absolute left-3 top-3.5 text-ink-3" />
                <p className="text-[13.5px] italic leading-relaxed text-ink-2">{x.quote}</p>
              </div>
              <a href={`https://pubmed.ncbi.nlm.nih.gov/${x.pmid.replace('PMID:', '')}/`} target="_blank" rel="noreferrer"
                className="mt-1.5 flex items-start gap-1.5 text-[12px] text-accent hover:underline">
                <ExternalLink size={12} className="mt-0.5 shrink-0" />{x.title} ({x.year}) · {x.pmid}
              </a>
            </div>
          ))}
          {!ev.length && <p className="text-[13px] text-ink-3">Curated by a team member from a quoted paper sentence.</p>}
        </Section>
        <Section title="Between">
          {[d, mech].map((x) => <Row key={x.id} leading={<TypeTile type={x.type} />} title={nodeLabel(x)} onClick={() => reveal(x.id)} />)}
        </Section>
      </div>
    </>
  )
}

/* --------------------------------------------------------------- generic -- */

function GenericCard({ n, m }: { n: GNode; m: Model }) {
  const { reveal } = useStore()
  const nb = neighbours(m, n.id)
  const diseases = nb.filter((x) => x.node.type === 'Disease')
  const claims = nb.filter((x) => x.node.type === 'Claim')
  const rest = nb.filter((x) => x.node.type !== 'Disease' && x.node.type !== 'Claim')
  const fields = (['protein_change', 'cdna_change', 'consequence', 'classification', 'variant_type'] as const).filter((k) => n[k])
  const total = [...m.nodes.values()].filter((x) => x.type === 'Disease').length
  return (
    <>
      <Header n={n} />
      {n.type === 'Phenotype' && (
        <div className="mt-4 flex gap-2"><Stat label="Seen in" value={`${diseases.length} of ${total}`} hint="mapped diseases" /></div>
      )}
      <div className="mt-3">
        {fields.length > 0 && (
          <Section title="Details">
            {fields.map((k) => (
              <div key={k} className="flex justify-between gap-4 py-1 text-[13px]">
                <span className="text-ink-3">{titleCase(k.replace('_', ' '))}</span><span className="text-right font-medium text-ink">{String(n[k])}</span>
              </div>
            ))}
          </Section>
        )}
        {claims.length > 0 && <Section title="What papers say" count={claims.length}>{claims.map((c) => <ClaimRow key={c.node.id} c={c.node} />)}</Section>}
        {diseases.length > 0 && (
          <Section title="Diseases" count={diseases.length}>
            {diseases.map((d) => <Row key={d.node.id} leading={<TypeTile type="Disease" />} title={nodeLabel(d.node)} subtitle={titleCase(d.node.name)} onClick={() => reveal(d.node.id)} />)}
          </Section>
        )}
        {rest.length > 0 && (
          <Section title="Connected" count={rest.length}>
            <More items={rest} initial={6} wrap="" render={(x) => (
              <Row key={x.edge.id} leading={<TypeTile type={x.node.type} />} title={nodeLabel(x.node)} onClick={() => reveal(x.node.id)} />
            )} />
          </Section>
        )}
        {n.name_source === 'paper mention' && <p className="mt-2 text-[11.5px] text-ink-3">Name taken from the paper; ID resolved by exact HPO match.</p>}
        {externalLinks(n).length > 0 && <Section title="External records"><SourcesList n={n} /></Section>}
      </div>
    </>
  )
}

/* ------------------------------------------------------ why connected -- */

function MatchCard({ e, m }: { e: GEdge; m: Model }) {
  const { reveal } = useStore()
  const a = m.nodes.get(e.source)!, b = m.nodes.get(e.target)!
  const shared = (e.shared_phenotypes as { id: string; name: string }[]) ?? []
  const informative = new Set((e.informative_phenotypes as string[]) ?? [])
  const ordered = [...shared].sort((x, y) => Number(informative.has(y.name)) - Number(informative.has(x.name)))
  const sameGene = ((e.shared_genes as string[]) ?? []).length > 0
  const score = e.score as number
  const comps = (e.components as Record<string, number>) ?? {}
  const why = (e.why_connected as string[]) ?? []

  return (
    <>
      <p className="text-[12px] font-semibold text-disease">Why are these connected?</p>
      <div className="mt-3 flex items-center gap-2">
        {[a, b].map((x, i) => (
          <div key={x.id} className="contents">
            {i === 1 && (
              <div className="flex flex-col items-center px-1">
                <span className="text-[17px] font-semibold tabular-nums text-ink">{Math.round(score)}</span>
                <Strength level={strengthOf(score)} />
              </div>
            )}
            <button onClick={() => reveal(x.id)}
              className="card-shadow min-w-0 flex-1 rounded-xl bg-white p-3 text-left transition-shadow hover:shadow-md">
              <span className="block h-2.5 w-2.5 rounded-full bg-disease" />
              <span className="mt-2 block truncate text-[13.5px] font-semibold text-ink">{nodeLabel(x)}</span>
              <span className="block truncate text-[11.5px] text-ink-3">{String(x.short ?? '')} gene</span>
            </button>
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        <Badge color="#f43f6b">{String(e.connection_label)}</Badge>
        <Badge color={STATUS[e.status].color} icon={<ShieldCheck size={12} />}>Computed link, not proven</Badge>
      </div>

      {why.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {why.map((w, i) => <p key={i} className="text-[13.5px] leading-relaxed text-ink-2">{w}</p>)}
        </div>
      )}

      <div className="mt-3">
        <Section title="What they share" count={shared.length}
          action={<MapToggle ids={shared.map((p) => p.id)} />}>
          {ordered.length
            ? <More items={ordered} initial={8} render={(p) => (
                <Chip key={p.id} color={informative.has(p.name) ? '#f43f6b' : TYPE_COLOR.Phenotype} onClick={() => reveal(p.id)}>{p.name}</Chip>
              )} />
            : <p className="text-[13px] text-ink-3">No identical symptom terms; the link comes from related terms.</p>}
          {informative.size > 0 && <p className="mt-2 text-[11.5px] text-ink-3"><span className="text-disease">●</span> Most informative shared features, as chosen by the matching algorithm.</p>}
        </Section>
        <Section title="What differs">
          <Row leading={<TypeTile type="Gene" />} title={sameGene ? 'Same gene' : 'Different genes'}
            subtitle={`${a.short ?? '?'} vs ${b.short ?? '?'}`}
            trailing={!sameGene && !((e.shared_mechanisms as string[]) ?? []).length ? <Badge color="#8a94a6">no shared mechanism in atlas yet</Badge> : undefined} />
        </Section>
        <Section title="Score breakdown">
          {([['phenotype', 'Symptoms', 30], ['mechanism', 'Mechanism', 50], ['genetic', 'Genes', 20]] as const).map(([k, label, w]) => (
            <div key={k} className="flex items-center gap-3 py-1 text-[13px]">
              <span className="w-24 text-ink-2">{label}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-subtle">
                <span className="block h-full rounded-full bg-disease" style={{ width: `${Math.min(100, (comps[k] ?? 0) * 100)}%` }} />
              </span>
              <span className="w-10 text-right font-mono text-[12px] text-ink-3">{(comps[k] ?? 0).toFixed(2)}</span>
              <span className="w-9 text-right text-[11px] text-ink-3">×{w}%</span>
            </div>
          ))}
          <p className="mt-2 text-[11.5px] leading-snug text-ink-3">
            Weights apply only to dimensions with shared evidence.
            {!comps.mechanism && !comps.genetic ? ' No shared mechanism or gene is in the atlas, so this score comes from symptoms alone.' : ''}
          </p>
        </Section>
        <Section title="How this was measured" defaultOpen={false}>
          <p className="text-[13px] leading-relaxed text-ink-2">
            Symptom similarity is an information-weighted overlap of both diseases’ HPO symptom profiles, including broader
            parent terms. Rare symptoms weigh more than common ones. Mechanism and gene overlap are added when both
            diseases have them. The result is scaled by the quality of the sources behind the shared features and reported
            as 0–100. Pairs below 20 are not shown, and overlaps made only of broad symptoms are down-weighted.
          </p>
          {[
            ['Match score', score.toFixed(1)],
            ['Source quality of shared features', `${String(e.confidence)} (${Number(e.evidence_quality ?? 0).toFixed(2)})`],
            ['Strength buckets (UI only)', `strong ≥ ${STRENGTH_CUTOFFS.strong}, moderate ≥ ${STRENGTH_CUTOFFS.moderate}`],
          ].map(([k, v]) => (
            <div key={k} className="mt-1.5 flex items-center justify-between gap-3 rounded-lg bg-subtle px-3 py-2 text-[12.5px]">
              <span className="text-ink-3">{k}</span><span className="text-right font-mono font-medium text-ink">{v}</span>
            </div>
          ))}
          <p className="mt-2 text-[11.5px] text-ink-3">“Source quality” rates the curated sources (HPO), not whether the diseases share a cause.</p>
        </Section>
      </div>

      <div className="mt-2">
        <Callout icon={<Lightbulb size={16} />} title="What would make this stronger">
          Symptom overlap shows where to look; it does not show a shared cause. Evidence that {String(a.short)} and {String(b.short)} act
          through the same mechanism would turn this into a mechanistic link.
        </Callout>
      </div>
    </>
  )
}

function BridgeCard({ e, m }: { e: GEdge; m: Model }) {
  const { reveal } = useStore()
  const a = m.nodes.get(e.source)!, b = m.nodes.get(e.target)!
  const kinds = BRIDGE_KINDS.filter(([k]) => ((e[k] as unknown[]) ?? []).length)
  return (
    <>
      <p className="text-[12px] font-semibold text-[#7c3aed]">What these communities share</p>
      <div className="mt-3 flex items-center gap-2">
        {[a, b].map((x, i) => (
          <div key={x.id} className="contents">
            {i === 1 && <span className="px-1 text-[18px] text-[#7c3aed]">⇄</span>}
            <button onClick={() => reveal(x.id)} className="card-shadow min-w-0 flex-1 rounded-xl bg-white p-3 text-left hover:shadow-md">
              <span className="block h-2.5 w-2.5 rounded-full bg-disease" />
              <span className="mt-2 block truncate text-[13.5px] font-semibold text-ink">{nodeLabel(x)}</span>
              <span className="block truncate text-[11.5px] text-ink-3">{String(x.short ?? '')} gene</span>
            </button>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        <Badge color="#7c3aed">{String(e.connection_label)}</Badge>
        <Badge color="#12b886" icon={<ShieldCheck size={12} />}>Facts from curated sources</Badge>
      </div>
      <div className="mt-3">
        {kinds.map(([k, label, type]) => (
          <Section key={k} title={label} count={(e[k] as unknown[]).length}>
            {(e[k] as { id: string; name: string }[]).map((x) => {
              const node = m.nodes.get(x.id)
              return <Row key={x.id} leading={<TypeTile type={type} />} title={x.name}
                subtitle={node?.type === 'Study' ? trialStatus(node.status).label : node?.type === 'Researcher' ? String(node.organization ?? '') : undefined}
                onClick={() => reveal(x.id)} />
            })}
          </Section>
        ))}
      </div>
      <Callout icon={<Lightbulb size={16} />} title="Why this matters">
        {kinds[0]?.[0] === 'shared_gene_groups'
          ? 'Different gene names, same protein family: findings, models and drug candidates for one may inform the other.'
          : kinds.some(([k]) => k === 'shared_studies')
            ? 'Both communities are already part of the same study, a ready-made place to compare data and recruit together.'
            : kinds.some(([k]) => k === 'shared_interventions')
              ? 'The same drug is being tested in both. Results and safety data from one trial are directly relevant to the other.'
              : 'A shared researcher or organisation is a natural first contact for joint work.'}
        {' '}It is a lead to check, not proof of a shared cause.
      </Callout>
      <p className="mt-3 text-[11.5px] text-ink-3">Sources: HGNC gene groups, ClinicalTrials.gov, NIH RePORTER (PI profile IDs), NORD and RareConnect · retrieved {e.retrieved}</p>
    </>
  )
}

function EdgeCard({ e, m }: { e: GEdge; m: Model }) {
  const { reveal } = useStore()
  if (e.rel === 'DISEASE_MATCH') return <MatchCard e={e} m={m} />
  if (e.rel === 'DISEASE_BRIDGE') return <BridgeCard e={e} m={m} />
  if (e.rel === 'INVOLVES') return <MechanismEdgeCard e={e} m={m} />
  const a = m.nodes.get(e.source)!, b = m.nodes.get(e.target)!
  const st = STATUS[e.status]
  const ev = e.evidence as { via: string; reference: string; code: string }[] | undefined
  const facts: [string, ReactNode][] = [
    ['Source', String(e.source_name ?? '–')],
    ['Method', e.method.replace('_', ' ')],
    ['Source quality', `Tier ${e.source_tier}`],
    ['Retrieved', e.retrieved],
  ]
  if (e.link_reason) facts.push(['Why linked', String(e.link_reason)])
  if (e.classification) facts.push(['ClinVar', `${e.classification} · ${e.review_status}`])
  return (
    <>
      <p className="text-[12px] font-semibold text-ink-3">Connection</p>
      <h2 className="mt-1 text-[21px] font-semibold tracking-[-0.02em] text-ink">{titleCase(e.rel.replace(/_/g, ' ').toLowerCase())}</h2>
      <div className="mt-2 flex gap-1.5">
        <Badge color={st?.color} icon={<ShieldCheck size={12} />}>{st?.label}</Badge>
        {(e.review_status === 'pending' || e.review_status === 'auto_verified') && <PendingBadge />}
      </div>
      <div className="mt-3">
        <Section title="Between">
          {[a, b].map((x) => <Row key={x.id} leading={<TypeTile type={x.type} />} title={nodeLabel(x)} onClick={() => reveal(x.id)} />)}
          <div className="flex justify-center text-ink-3"><ArrowRight size={14} className="rotate-90" /></div>
        </Section>
        <Section title="Evidence">
          {facts.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4 py-1 text-[13px]">
              <span className="text-ink-3">{k}</span><span className="text-right font-medium text-ink">{v}</span>
            </div>
          ))}
        </Section>
        {ev && ev.length > 0 && (
          <Section title="References" count={ev.length} defaultOpen={false}>
            {ev.map((x, i) => <Row key={i} leading={<TypeTile type="Paper" />} title={x.reference} subtitle={`via ${x.via} · code ${x.code}`} />)}
          </Section>
        )}
      </div>
    </>
  )
}

/* ----------------------------------------------------------------- sheet -- */

const SPECIAL = ['Disease', 'Gene', 'Paper', 'Claim', 'Study', 'PatientOrg', 'Grant', 'GeneGroup', 'Intervention', 'Mechanism']

export default function DetailPanel() {
  const { model, selected, history, back, close } = useStore()
  const prev = history.length ? history[history.length - 1].selected : null
  const prevNode = prev && model ? (prev.kind === 'node' ? model.nodes.get(prev.id) : model.edges.get(prev.id)) : null
  const sameCard = prev && selected && prev.kind === selected.kind && prev.id === selected.id
  const prevLabel = sameCard ? 'Undo map change' : !prevNode ? '' : prev?.kind === 'node'
    ? nodeLabel(prevNode as GNode) : 'Connection'
  const node = model && selected?.kind === 'node' ? model.nodes.get(selected.id) : null
  const edge = model && selected?.kind === 'edge' ? model.edges.get(selected.id) : null
  const open = !!(node || edge)

  return (
    <AnimatePresence>
      {open && model && (
        <motion.aside
          initial={{ opacity: 0, x: 24, scale: 0.98 }} animate={{ opacity: 1, x: 0, scale: 1 }}
          exit={{ opacity: 0, x: 24, scale: 0.98 }} transition={{ type: 'spring', stiffness: 380, damping: 34 }}
          className="glass absolute inset-x-2 bottom-2 z-20 flex max-h-[64vh] flex-col overflow-hidden rounded-[22px]
                     md:inset-x-auto md:bottom-4 md:right-4 md:top-[84px] md:max-h-none md:w-[400px]">
          <div className="flex items-center gap-2 px-4 pb-1 pt-3">
            {prev ? (
              <button onClick={back} title="Back to the previous card"
                className="flex min-w-0 max-w-[75%] items-center gap-1.5 rounded-full bg-black/[0.04] py-1.5 pl-2 pr-3 text-[12.5px] font-medium text-ink-2 transition-colors hover:bg-black/[0.08]">
                <ArrowLeft size={14} strokeWidth={2.4} className="shrink-0" />
                <span className="truncate">{prevLabel}</span>
              </button>
            ) : <span className="mx-auto h-1 w-9 rounded-full bg-black/10 md:hidden" />}
            <button onClick={close} aria-label="Close" title="Close and tidy the map"
              className="ml-auto flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-black/[0.04] text-ink-2 transition-colors hover:bg-black/[0.08]">
              <X size={14} strokeWidth={2.4} />
            </button>
          </div>
          <div className="scroll-thin flex-1 overflow-y-auto px-5 pb-6 pt-1">
            <AnimatePresence mode="wait">
              <motion.div key={selected!.kind + selected!.id}
                initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.16 }}>
                {node?.type === 'Disease' && <DiseaseCard n={node} m={model} />}
                {node?.type === 'Gene' && <GeneCard n={node} m={model} />}
                {node?.type === 'Paper' && <PaperCard n={node} m={model} />}
                {node?.type === 'Claim' && <ClaimCard n={node} m={model} />}
                {node?.type === 'Study' && <StudyCard n={node} m={model} />}
                {node?.type === 'PatientOrg' && <OrgCard n={node} m={model} />}
                {node?.type === 'Grant' && <GrantCard n={node} m={model} />}
                {node?.type === 'GeneGroup' && <GeneGroupCard n={node} m={model} />}
                {node?.type === 'Intervention' && <InterventionCard n={node} m={model} />}
                {node?.type === 'Mechanism' && <MechanismCard n={node} m={model} />}
                {node && !SPECIAL.includes(node.type) && <GenericCard n={node} m={model} />}
                {edge && <EdgeCard e={edge} m={model} />}
              </motion.div>
            </AnimatePresence>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  )
}
