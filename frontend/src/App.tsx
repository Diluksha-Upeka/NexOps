import { useEffect, useState } from 'react';
import { fetchHealth, type HealthResponse } from './api';
import './App.css';

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

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
