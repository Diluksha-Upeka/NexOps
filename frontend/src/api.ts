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
  service: string;
  source: string;
  scenario_key: string | null;
  started_at: string;
  created_at: string;
  resolved_at: string | null;
}

export interface EvidenceItem {
  id: string;
  run_id: string;
  source_type: string;
  observed_at: string;
  summary: string;
  payload_json: Record<string, unknown> | null;
  source_ref: string | null;
  confidence: number | null;
  simulated: boolean;
}

export interface Hypothesis {
  cause_key: string;
  title: string;
  description: string;
  confidence: number;
  supporting_evidence_ids: string[];
  contradictions: string[];
}

export interface Approval {
  id: string;
  status: string;
  action_type: string;
  action_payload: Record<string, unknown> | null;
  risk: string;
  reasoning: string;
  actor: string | null;
  decided_at: string | null;
}

export interface RunDetail {
  id: string;
  status: string;
  incident_id: string;
  thread_id: string;
  evidence: EvidenceItem[];
  hypotheses: Hypothesis[];
  proposed_action: Record<string, unknown> | null;
  approval: Approval | null;
  is_awaiting_approval: boolean;
  run: {
    id: string;
    status: string;
    started_at: string;
    finished_at: string | null;
    model_name: string | null;
    prompt_version: string | null;
    graph_version: string | null;
    error_code: string | null;
    error_message: string | null;
  };
}

export interface InvestigationRun {
  id: string;
  incident_id: string;
  thread_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  model_name: string | null;
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
  return apiRequest('/health');
}

export async function fetchIncidents(): Promise<{ items: Incident[]; total: number }> {
  return apiRequest('/incidents?limit=100');
}

export async function fetchIncident(id: string): Promise<Incident> {
  return apiRequest(`/incidents/${id}`);
}

export async function startInvestigation(incidentId: string): Promise<{ id: string }> {
  return apiRequest(`/incidents/${incidentId}/investigations`, { method: 'POST' });
}

export async function fetchRun(runId: string): Promise<RunDetail> {
  return apiRequest(`/runs/${runId}`);
}

export async function fetchRunsForIncident(incidentId: string): Promise<InvestigationRun[]> {
  return apiRequest(`/incidents/${incidentId}/runs`);
}

export async function fetchEvidence(runId: string): Promise<EvidenceItem[]> {
  return apiRequest(`/runs/${runId}/evidence`);
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

export async function resolveIncident(
  incidentId: string,
  reason: string = 'Resolved by operator',
): Promise<Incident> {
  return apiRequest(`/incidents/${incidentId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ reason, actor: 'dev-operator' }),
  });
}

export async function createIncident(data: {
  title: string;
  description: string;
  service?: string;
  severity?: 'critical' | 'high' | 'medium' | 'low';
  source?: 'manual' | 'simulator';
  scenario_key?: string | null;
}): Promise<Incident> {
  return apiRequest('/incidents', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function startScenario(scenarioKey: string): Promise<Record<string, unknown>> {
  return apiRequest(`/simulator/scenarios/${scenarioKey}/start`, {
    method: 'POST',
  });
}

