const API_BASE = '/api/v1';

export interface HealthResponse {
  status: string;
  service: string;
  checks: {
    database: string;
  };
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) {
    throw new Error(`Health check failed: ${res.status}`);
  }
  return res.json();
}
