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
  total_workflow_versions: number;
  total_validation_runs: number;
  average_structural_score: number;
  critical_issues: number;
  total_evaluation_runs: number;
  average_overall_score: number;
  average_quality_score: number;
  total_workflow_tests: number;
  test_pass_rate: number;
  average_coverage: number;
  latest_test_coverage: number;
  failing_test_runs: number;
  latest_monthly_cost: number;
  potential_cost_savings: number;
  open_repair_proposals: number;
  charts: {
    quality_over_time?: Array<{ date: string; score: number }>;
    cost_trend?: Array<{ date: string; monthly_cost: number }>;
    test_pass_rate?: Array<{ date: string; pass_rate: number }>;
    findings_by_severity?: Record<string, number>;
    workflows_by_source?: Record<string, number>;
    workflows_by_format?: Record<string, number>;
    most_expensive_workflows?: Array<{ workflow_id: string; name: string; monthly_cost: number }>;
  };
  recent_workflows: WorkflowSummary[];
};

export type AuditEvent = {
  id: string;
  workflow_id?: string | null;
  version_id?: string | null;
  event_type: string;
  actor: string;
  message: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type QualityGateRun = {
  id: string;
  workflow_id: string;
  version_id: string;
  status: "PASS" | "FAIL";
  score: number;
  config: Record<string, unknown>;
  dimensions: Record<string, number | null>;
  reasons: Array<{
    rule_id: string;
    passed: boolean;
    title: string;
    message: string;
    expected: string;
    actual: string;
    severity: string;
    metadata: Record<string, unknown>;
  }>;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type WorkflowAssertion = {
  type: string;
  target?: string | null;
  expected?: unknown;
  description?: string | null;
};

export type MockIntegration = {
  node_id: string;
  response?: unknown;
  status_code?: number | null;
  latency_ms: number;
  error?: string | null;
  metadata: Record<string, unknown>;
};

export type FailureInjection = {
  node_id: string;
  failure_type: string;
  occurrence: number;
  metadata: Record<string, unknown>;
};

export type WorkflowTest = {
  id: string;
  workflow_id: string;
  version_id?: string | null;
  name: string;
  description: string;
  generated_by: string;
  input_data: Record<string, unknown>;
  mocked_integrations: MockIntegration[];
  failure_injections: FailureInjection[];
  expected_path: string[];
  expected_outputs: Record<string, unknown>;
  expected_side_effects: string[];
  forbidden_side_effects: string[];
  assertions: WorkflowAssertion[];
  expected_error?: string | null;
  tags: string[];
  importance: string;
  enabled: boolean;
  rationale?: string | null;
  linked_requirement_id?: string | null;
  metadata: Record<string, unknown>;
  latest_status?: string | null;
  latest_run_id?: string | null;
  latest_run_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type AssertionResult = {
  assertion: WorkflowAssertion;
  passed: boolean;
  message: string;
};

export type Coverage = {
  node_coverage: number;
  edge_coverage: number;
  branch_coverage: number;
  requirement_coverage: number;
  overall_coverage: number;
  covered_nodes: string[];
  covered_edges: string[];
  covered_requirements: string[];
  calculation: Record<string, unknown>;
};

export type WorkflowTestRun = {
  id: string;
  workflow_id: string;
  version_id: string;
  test_id: string;
  status: string;
  execution_trace: {
    execution_order?: string[];
    executed_edges?: string[];
    node_executions?: Array<{
      node_id: string;
      node_name: string;
      node_type: string;
      status: string;
      branch_decision?: string | null;
      mocked: boolean;
      retries: number;
      latency_ms: number;
      error?: string | null;
    }>;
    failures?: string[];
    external_calls?: unknown[];
    approval_requests?: string[];
    token_estimate?: number;
  };
  assertion_results: AssertionResult[];
  failures: string[];
  duration_ms: number;
  coverage?: Coverage | null;
  created_at: string;
};

export type TestRunSummary = {
  total_tests: number;
  passed: number;
  failed: number;
  error: number;
  skipped: number;
  latest_coverage: number;
  last_run_at?: string | null;
  runs: WorkflowTestRun[];
};

export type CostLineItem = {
  node_id?: string | null;
  node_name?: string | null;
  category: string;
  provider?: string | null;
  model?: string | null;
  calls_per_execution: number;
  input_tokens: number;
  output_tokens: number;
  unit_cost: number;
  estimated_cost_per_run: number;
  pricing_assumption: Record<string, unknown>;
  explanation: string;
};

export type OptimizationFinding = {
  id: string;
  rule_id: string;
  title: string;
  message: string;
  category: string;
  node_id?: string | null;
  estimated_monthly_savings: number;
  confidence: string;
  deterministic: boolean;
  recommendation: string;
  metadata: Record<string, unknown>;
};

export type CostEstimate = {
  id: string;
  workflow_id: string;
  version_id?: string | null;
  scenario: Record<string, unknown>;
  line_items: CostLineItem[];
  cost_per_run: number;
  daily_cost: number;
  monthly_cost: number;
  annual_cost: number;
  assumptions: string[];
  optimization_findings: OptimizationFinding[];
  created_at: string;
};

export type VersionComparison = {
  workflow_a_id: string;
  workflow_b_id: string;
  nodes_added: string[];
  nodes_removed: string[];
  edges_added: string[];
  edges_removed: string[];
  configuration_changed: string[];
  validation_score_delta?: number | null;
  prompt_alignment_delta?: number | null;
  security_delta?: number | null;
  reliability_delta?: number | null;
  test_coverage_delta?: number | null;
  estimated_cost_delta?: number | null;
  metadata: Record<string, unknown>;
};

export type RepairProposal = {
  id: string;
  workflow_id: string;
  version_id: string;
  finding_id?: string | null;
  status: string;
  patch: Record<string, unknown>;
  preview: Record<string, unknown>;
  safety_flags: string[];
  accepted_version_id?: string | null;
  created_at: string;
  updated_at: string;
};
