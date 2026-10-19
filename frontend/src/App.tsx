import { useEffect, useState } from 'react';
import {
  fetchHealth,
  fetchIncidents,
  fetchRun,
  startInvestigation,
  submitApproval,
  type HealthResponse,
  type Incident,
  type RunDetail,
} from './api';
import './App.css';

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
    fetchIncidents().then((result) => setIncidents(result.items)).catch(() => undefined);
  }, []);

  const investigate = async (incident: Incident) => {
    setActionError(null);
    try {
      const started = await startInvestigation(incident.id);
      setRun(await fetchRun(started.id));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to start investigation');
    }
  };

  const decide = async (decision: 'approved' | 'rejected' | 'request_more_evidence') => {
    if (!run) return;
    try {
      await submitApproval(run.id, decision);
      setRun(await fetchRun(run.id));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Unable to submit decision');
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <div className="logo">
            <span className="logo-icon">⚡</span>
            <h1>NexOps</h1>
          </div>
          <p className="tagline">Agentic Incident Response System</p>
        </div>
      </header>

      <main className="main">
        <section className="status-card">
          <h2>System Status</h2>
          {loading && (
            <div className="status-loading">
              <div className="spinner" />
              <span>Connecting to backend…</span>
            </div>
          )}
          {error && (
            <div className="status-item status-error">
              <span className="status-dot dot-error" />
              <div>
                <strong>Connection Error</strong>
                <p>{error}</p>
                <p className="hint">Is the API server running on port 8000?</p>
              </div>
            </div>
          )}
          {health && (
            <>
              <div className={`status-item status-${health.status}`}>
                <span className={`status-dot dot-${health.status}`} />
                <div>
                  <strong>API</strong>
                  <p>{health.status}</p>
                </div>
              </div>
              <div
                className={`status-item ${health.checks.database === 'connected' ? 'status-healthy' : 'status-degraded'}`}
              >
                <span
                  className={`status-dot ${health.checks.database === 'connected' ? 'dot-healthy' : 'dot-degraded'}`}
                />
                <div>
                  <strong>Database</strong>
                  <p>{health.checks.database}</p>
                </div>
              </div>
            </>
          )}
        </section>

        <section className="info-grid">
          <div className="info-card">
            <span className="info-icon">🔍</span>
            <h3>Investigation</h3>
            <p>Parallel evidence gathering from logs, metrics, traces, and change history.</p>
            <span className="badge">Phase 3</span>
          </div>
          <div className="info-card">
            <span className="info-icon">🛡️</span>
            <h3>Human Approval</h3>
            <p>Every remediation action requires explicit approval before execution.</p>
            <span className="badge">Phase 5</span>
          </div>
          <div className="info-card">
            <span className="info-icon">🧪</span>
            <h3>Sandbox Actions</h3>
            <p>All remediation is confined to the local simulator — never touches production.</p>
            <span className="badge">Phase 6</span>
          </div>
          <div className="info-card">
            <span className="info-icon">📊</span>
            <h3>Observability & Resilience</h3>
            <p>Prometheus metrics, Grafana dashboards, OpenTelemetry distributed tracing.</p>
            <span className="badge">Phase 7</span>
          </div>
        </section>

        <section className="status-card">
          <h2>Observability & Telemetry Links <span className="badge">Phase 7</span></h2>
          <div className="telemetry-links" style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
            <a
              href="http://localhost:3000/d/nexops-main"
              target="_blank"
              rel="noreferrer"
              className="badge"
              style={{ textDecoration: 'none', padding: '0.5rem 1rem', background: '#2563eb', color: '#fff' }}
            >
              📈 Grafana Dashboard (Port 3000)
            </a>
            <a
              href="http://localhost:16686"
              target="_blank"
              rel="noreferrer"
              className="badge"
              style={{ textDecoration: 'none', padding: '0.5rem 1rem', background: '#059669', color: '#fff' }}
            >
              🔍 Jaeger Traces (Port 16686)
            </a>
            <a
              href="/metrics"
              target="_blank"
              rel="noreferrer"
              className="badge"
              style={{ textDecoration: 'none', padding: '0.5rem 1rem', background: '#d97706', color: '#fff' }}
            >
              ⚡ Prometheus /metrics
            </a>
          </div>
        </section>

        <section className="status-card">
          <h2>Approval Workbench <span className="badge">Simulated</span></h2>
          {incidents.length === 0 && <p className="hint">No incidents are available yet.</p>}
          {incidents.map((incident) => (
            <div className="status-item" key={incident.id}>
              <div>
                <strong>{incident.title}</strong>
                <p>{incident.severity} · {incident.status}</p>
              </div>
              <button onClick={() => investigate(incident)}>Investigate</button>
            </div>
          ))}
          {run?.approval && run.is_awaiting_approval && (
            <div className="approval-panel">
              <strong>Human approval required: {run.approval.action_type}</strong>
              <p>{run.approval.reasoning}</p>
              <p className="hint">Risk: {run.approval.risk}. No simulator action runs before approval.</p>
              <div className="approval-actions">
                <button onClick={() => decide('approved')}>Approve</button>
                <button onClick={() => decide('rejected')}>Reject</button>
                <button onClick={() => decide('request_more_evidence')}>Request evidence</button>
              </div>
            </div>
          )}
          {run && !run.is_awaiting_approval && (
            <div style={{ marginTop: '0.75rem' }}>
              <p className="hint">Run status: <strong>{run.status}</strong></p>
              {run.trace_id && (
                <p className="hint" style={{ marginTop: '0.25rem' }}>
                  Distributed Trace ID:{' '}
                  <a
                    href={`http://localhost:16686/trace/${run.trace_id}`}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: '#38bdf8', fontFamily: 'monospace' }}
                  >
                    {run.trace_id}
                  </a>
                </p>
              )}
            </div>
          )}
          {actionError && <p className="status-error">{actionError}</p>}
        </section>

        <footer className="footer">
          <p>
            ⚠️ This is a <strong>simulated</strong> incident response system for learning and portfolio purposes.
          </p>
        </footer>
      </main>
    </div>
  );
}

export default App;
