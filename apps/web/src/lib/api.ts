import type {
  DashboardMetrics,
  CostEstimate,
  EvaluationRun,
  AuditEvent,
  QualityGateRun,
  RepairProposal,
  TestRunSummary,
  ValidationRun,
  VersionComparison,
  WorkflowDetail,
  WorkflowSummary,
  WorkflowTest,
} from "@/types/workflow";

const API_BASE_URL =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api"
    : process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store"
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<DashboardMetrics>("/dashboard"),
  workflows: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params).toString()}` : "";
    return request<WorkflowSummary[]>(`/workflows${query}`);
  },
  workflow: (id: string) => request<WorkflowDetail>(`/workflows/${id}`),
  validation: (id: string) => request<ValidationRun | null>(`/workflows/${id}/validation`),
  evaluations: (id: string) => request<EvaluationRun[]>(`/workflows/${id}/evaluations`),
  evaluate: (id: string, useAI = true) =>
    request<EvaluationRun>(`/workflows/${id}/evaluate`, {
      method: "POST",
      body: JSON.stringify({ use_ai: useAI })
    }),
  tests: (id: string) => request<WorkflowTest[]>(`/workflows/${id}/tests`),
  generateTests: (id: string, useAI = true, replaceExisting = false) =>
    request<{ generated: number; tests: WorkflowTest[]; rationale: string; warnings: string[] }>(
      `/workflows/${id}/tests/generate`,
      {
        method: "POST",
        body: JSON.stringify({ use_ai: useAI, replace_existing: replaceExisting })
      }
    ),
  createTest: (id: string, payload: {
    name: string;
    description: string;
    generated_by: string;
    input_data: Record<string, unknown>;
    assertions: Array<{ type: string; target?: string; expected?: unknown }>;
    tags: string[];
    importance: string;
  }) =>
    request<WorkflowTest>(`/workflows/${id}/tests`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  runTests: (id: string) =>
    request<TestRunSummary>(`/workflows/${id}/tests/run`, {
      method: "POST",
      body: JSON.stringify({})
    }),
  testRuns: (id: string) => request<TestRunSummary>(`/workflows/${id}/test-runs`),
  cost: (id: string) => request<CostEstimate>(`/workflows/${id}/cost`),
  estimateCost: (id: string, payload: Record<string, unknown>) =>
    request<CostEstimate>(`/workflows/${id}/cost`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  compareVersions: (id: string) => request<VersionComparison>(`/workflows/${id}/versions/compare`),
  repairs: (id: string) => request<RepairProposal[]>(`/workflows/${id}/repairs`),
  versions: (id: string) => request<Array<{ id: string; workflow_id: string; version_number: number; created_at: string }>>(`/workflows/${id}/versions`),
  history: (id: string) => request<AuditEvent[]>(`/workflows/${id}/history`),
  qualityGate: (id: string) => request<QualityGateRun>(`/workflows/${id}/quality-gate`),
  checkQualityGate: (id: string) =>
    request<QualityGateRun>(`/workflows/${id}/quality-gate`, {
      method: "POST",
      body: JSON.stringify({})
    }),
  report: (id: string) => request<Record<string, unknown>>(`/workflows/${id}/report?format=json`),
  generateRepair: (id: string, finding?: Record<string, unknown>) =>
    request<RepairProposal>(`/workflows/${id}/repairs/generate`, {
      method: "POST",
      body: JSON.stringify({ finding, use_ai: true })
    }),
  acceptRepair: (id: string) =>
    request<RepairProposal>(`/repairs/${id}/accept`, {
      method: "POST",
      body: JSON.stringify({})
    }),
  rejectRepair: (id: string) =>
    request<RepairProposal>(`/repairs/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({})
    }),
  uploadWorkflow: (formData: FormData) =>
    request<WorkflowDetail>("/workflows/upload", {
      method: "POST",
      body: formData
    })
};
