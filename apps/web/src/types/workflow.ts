export type WorkflowNode = {
  id: string;
  name: string;
  type: string;
  subtype?: string | null;
  provider?: string | null;
  operation?: string | null;
  configuration: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type WorkflowEdge = {
  id: string;
  source: string;
  target: string;
  condition?: string | null;
  label?: string | null;
  metadata: Record<string, unknown>;
};

export type WorkflowSummary = {
  id: string;
  name: string;
  source_format: string;
  source_type: string;
  structural_quality_score: number | null;
  critical_findings: number;
  created_at: string;
  updated_at: string;
};

export type WorkflowDetail = WorkflowSummary & {
  source_prompt?: string | null;
  metadata: Record<string, unknown>;
  current_version_id?: string | null;
  canonical: {
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
    [key: string]: unknown;
  };
};

export type ValidationFinding = {
  id?: string | null;
  rule_id: string;
  severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  title: string;
  message: string;
  node_id?: string | null;
  edge_id?: string | null;
  remediation?: string | null;
  metadata: Record<string, unknown>;
};

export type ValidationRun = {
  id: string;
  workflow_id: string;
  version_id: string;
  structural_quality_score: number;
  status: string;
  created_at: string;
  findings: ValidationFinding[];
};

export type DashboardMetrics = {
  total_workflows: number;
  total_validation_runs: number;
  average_structural_score: number;
  critical_issues: number;
  recent_workflows: WorkflowSummary[];
};
