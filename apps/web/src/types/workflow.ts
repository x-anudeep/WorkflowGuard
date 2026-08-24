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

export type RequirementMatch = {
  requirement_id: string;
  requirement_text: string;
  status: string;
  matched_node_ids: string[];
  evidence: string;
  confidence: string;
};

export type DimensionScore = {
  dimension: string;
  score: number;
  explanation: string;
  calculation: Record<string, unknown>;
};

export type EvaluationFinding = {
  id?: string | null;
  rule_id: string;
  dimension: string;
  severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  title: string;
  message: string;
  expected: string;
  found: string;
  why_it_matters: string;
  node_id?: string | null;
  edge_id?: string | null;
  path: string[];
  remediation?: string | null;
  confidence: string;
  metadata: Record<string, unknown>;
};

export type RequirementSpec = {
  id?: string | null;
  source_prompt: string;
  extraction_method: string;
  confidence: string;
  spec: Record<string, unknown>;
  model_provider?: string | null;
  model_name?: string | null;
  created_at?: string | null;
};

export type EvaluationRun = {
  id: string;
  workflow_id: string;
  version_id: string;
  status: string;
  overall_score: number;
  structural_score: number;
  evaluator_version: string;
  ai_provider?: string | null;
  ai_model?: string | null;
  ai_metadata: Record<string, unknown>;
  limitations: string[];
  requirement_matches: RequirementMatch[];
  dimension_scores: DimensionScore[];
  findings: EvaluationFinding[];
  requirement_spec?: RequirementSpec | null;
  created_at: string;
};

export type DashboardMetrics = {
  total_workflows: number;
  total_validation_runs: number;
  average_structural_score: number;
  critical_issues: number;
  total_evaluation_runs: number;
  average_overall_score: number;
  recent_workflows: WorkflowSummary[];
};
