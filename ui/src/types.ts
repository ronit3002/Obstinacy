export type NodeType =
  | 'Disease' | 'Gene' | 'Variant' | 'Mechanism' | 'Phenotype'
  | 'Paper' | 'Claim' | 'Study' | 'PatientOrg' | 'Registry' | 'Researcher' | 'Intervention' | 'Grant' | 'GeneGroup'

export interface GNode {
  id: string
  type: NodeType
  name: string
  summary?: string
  summary_model?: string
  [key: string]: unknown
}

export interface GEdge {
  id: string
  source: string
  target: string
  rel: string
  source_tier: number
  status: 'observation' | 'inference' | 'hypothesis'
  method: string
  retrieved: string
  [key: string]: unknown
}

export interface GraphData {
  nodes: GNode[]
  edges: GEdge[]
  meta: { generated: string; nodes: number; edges: number }
}
