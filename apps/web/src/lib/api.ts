import type { DashboardMetrics, EvaluationRun, ValidationRun, WorkflowDetail, WorkflowSummary } from "@/types/workflow";

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
  workflows: () => request<WorkflowSummary[]>("/workflows"),
  workflow: (id: string) => request<WorkflowDetail>(`/workflows/${id}`),
  validation: (id: string) => request<ValidationRun | null>(`/workflows/${id}/validation`),
  evaluations: (id: string) => request<EvaluationRun[]>(`/workflows/${id}/evaluations`),
  evaluate: (id: string, useAI = true) =>
    request<EvaluationRun>(`/workflows/${id}/evaluate`, {
      method: "POST",
      body: JSON.stringify({ use_ai: useAI })
    }),
  uploadWorkflow: (formData: FormData) =>
    request<WorkflowDetail>("/workflows/upload", {
      method: "POST",
      body: formData
    })
};
