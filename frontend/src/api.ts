const API_BASE = '/api/v1';

export interface HealthResponse {
  status: string;
  service: string;
  checks: { database: string };
}

export interface Incident {
  id: string;
  title: string;
  description: string;
  status: string;
  severity: string;
  scenario_key: string | null;
}

export interface Approval {
  id: string;
  status: string;
  action_type: string;
  action_payload: Record<string, unknown> | null;
  risk: string;
  reasoning: string;
}

export interface RunDetail {
  id: string;
  status: string;
  incident_id: string;
  approval: Approval | null;
  is_awaiting_approval: boolean;
  trace_id?: string | null;
}

async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function fetchIncidents(): Promise<{ items: Incident[]; total: number }> {
  return apiRequest('/incidents');
}

export async function startInvestigation(incidentId: string): Promise<{ id: string }> {
  return apiRequest(`/incidents/${incidentId}/investigations`, { method: 'POST' });
}

export async function fetchRun(runId: string): Promise<RunDetail> {
  return apiRequest(`/runs/${runId}`);
}

export async function submitApproval(
  runId: string,
  decision: 'approved' | 'rejected' | 'request_more_evidence',
): Promise<Approval> {
  return apiRequest(`/runs/${runId}/approval`, {
    method: 'POST',
    body: JSON.stringify({
      decision,
      actor: 'dev-operator',
      idempotency_key: `${runId}-${decision}-${Date.now()}`,
    }),
  });
}
