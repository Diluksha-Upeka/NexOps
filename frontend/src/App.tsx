import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  createIncident,
  fetchHealth,
  fetchIncidentAudit,
  fetchIncidents,
  fetchRun,
  fetchRunEvents,
  fetchRunsForIncident,
  generateScenarioTraffic,
  resolveIncident,
  startInvestigation,
  startScenario,
  submitApproval,
  subscribeRunEvents,
  type AuditEvent,
  type HealthResponse,
  type Incident,
  type RunDetail,
  type RunEvent,
} from './api';
import {
  RavelLogo,
  DashboardIcon,
  SignalIcon,
  BookIcon,
  ChartIcon,
  SearchIcon,
  ActivityIcon,
  ShieldIcon,
  ToolIcon,
  TargetIcon,
  LightbulbIcon,
  CheckCircleIcon,
  XCircleIcon,
  AlertTriangleIcon,
  ClipboardListIcon,
  FileTextIcon,
  LinkIcon,
  RocketIcon,
  RefreshIcon,
  InboxIcon,
  ZapIcon,
  ExternalLinkIcon,
  BrainIcon,
  TerminalIcon,
  NetworkIcon,
  CpuIcon,
} from './Icons';
import { MultiAgentView, OrchestrationPage } from './MultiAgentView';
import './App.css';

/* ── Helpers ── */
const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

function severityColor(severity: string): string {
  return { critical: 'critical', high: 'high', medium: 'medium', low: 'low' }[severity] ?? 'medium';
}

type Page = 'dashboard' | 'orchestration' | 'observability';

/* ── Workflow stage map ── */
const PIPELINE_STAGES: readonly { key: string; label: string; icon: ReactNode; description: string }[] = [
  { key: 'triage', label: 'Triage', icon: <SearchIcon size={18} />, description: 'Understanding the incident' },
  { key: 'evidence', label: 'Evidence', icon: <ActivityIcon size={18} />, description: 'Collecting logs, metrics, traces, and changes' },
  { key: 'analysis', label: 'Analysis', icon: <BrainIcon size={18} />, description: 'Finding the most likely cause' },
  { key: 'proposal', label: 'Proposal', icon: <LightbulbIcon size={18} />, description: 'Preparing a safe action' },
  { key: 'approval', label: 'Approval', icon: <ShieldIcon size={18} />, description: 'Waiting for your decision' },
  { key: 'remediation', label: 'Fix', icon: <ToolIcon size={18} />, description: 'Applying the approved sandbox fix' },
  { key: 'verification', label: 'Verify', icon: <CheckCircleIcon size={18} />, description: 'Checking that the service recovered' },
] as const;

function resolveStageIndex(status: string, isAwaitingApproval: boolean): number {
  if (status === 'completed' || status === 'resolved') return PIPELINE_STAGES.length;
  if (status === 'failed') return -1;
  if (isAwaitingApproval || status === 'awaiting_approval') return 4;
  if (status === 'running') return 2;
  return 0;
}

/* ═══════════════════════════════════════════════════════════
   APP COMPONENT
   ═══════════════════════════════════════════════════════════ */

function App() {
  /* ── Global state ── */
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [page, setPage] = useState<Page>('dashboard');

  /* ── Incident detail state ── */
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [currentRun, setCurrentRun] = useState<RunDetail | null>(null);
  const [investigating, setInvestigating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pollTimer, setPollTimer] = useState<ReturnType<typeof setInterval> | null>(null);
  const sseUnsubRef = useRef<(() => void) | null>(null);

  /* ── Load on mount ── */
  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealthError(true));
    fetchIncidents()
      .then((r) => setIncidents(r.items))
      .catch(() => undefined);
  }, []);

  // The standalone Shop app reports customer-impacting failures here.
  // Keep the command center live without requiring a manual refresh.
  useEffect(() => {
    const refresh = () => {
      fetchIncidents().then((result) => {
        setIncidents(result.items);
        setSelectedIncident((current) => current ?? result.items.find((item) => item.status !== 'resolved') ?? null);
      }).catch(() => undefined);
    };
    const timer = setInterval(refresh, 2500);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedIncident || currentRun) return;
    fetchRunsForIncident(selectedIncident.id).then(async (runs) => {
      if (!runs.length) return;
      const latest = runs.sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())[0];
      setCurrentRun(await fetchRun(latest.id));
    }).catch(() => undefined);
  }, [selectedIncident, currentRun]);

  /* ── Derived stats ── */
  const openCount = incidents.filter((i) => i.status === 'open').length;
  const investigatingCount = incidents.filter((i) => i.status === 'investigating').length;

  /* ── Stream & Poll for run updates ── */
  const startPolling = useCallback(
    (runId: string) => {
      if (pollTimer) clearInterval(pollTimer);
      if (sseUnsubRef.current) {
        sseUnsubRef.current();
        sseUnsubRef.current = null;
      }

      const syncRunState = async () => {
        try {
          const run = await fetchRun(runId);
          setCurrentRun(run);
          if (['completed', 'failed', 'cancelled'].includes(run.status) || run.is_awaiting_approval) {
            clearInterval(timer);
            setPollTimer(null);
            setInvestigating(false);
            if (sseUnsubRef.current) {
              sseUnsubRef.current();
              sseUnsubRef.current = null;
            }
            fetchIncidents().then((r) => setIncidents(r.items)).catch(() => undefined);
          }
        } catch {
          /* ignore transient errors */
        }
      };

      sseUnsubRef.current = subscribeRunEvents(runId, (ev) => {
        if (['agent_message', 'agent_report', 'approval_required', 'run_finished'].includes(ev.type)) {
          void syncRunState();
        }
      });

      const timer = setInterval(() => {
        void syncRunState();
      }, 2000);
      setPollTimer(timer);
    },
    [pollTimer],
  );

  useEffect(() => {
    return () => {
      if (pollTimer) clearInterval(pollTimer);
      if (sseUnsubRef.current) sseUnsubRef.current();
    };
  }, [pollTimer]);

  /* ── Actions ── */
  const handleInvestigate = async (incident: Incident) => {
    setActionError(null);
    setInvestigating(true);
    setSelectedIncident(incident);
    setCurrentRun(null);
    try {
      const started = await startInvestigation(incident.id);
      const run = await fetchRun(started.id);
      setCurrentRun(run);
      // If not in a terminal state, start polling
      if (!['completed', 'failed'].includes(run.status) && !run.is_awaiting_approval) {
        startPolling(started.id);
      } else {
        setInvestigating(false);
      }
      // Refresh incidents
      fetchIncidents().then((r) => setIncidents(r.items)).catch(() => undefined);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to start investigation');
      setInvestigating(false);
    }
  };

  const handleSelectIncident = async (incident: Incident) => {
    setSelectedIncident(incident);
    setActionError(null);
    setCurrentRun(null);
    // Load latest run for this incident
    try {
      const runs = await fetchRunsForIncident(incident.id);
      if (runs.length > 0) {
        const latestRun = runs.sort(
          (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime(),
        )[0];
        const detail = await fetchRun(latestRun.id);
        setCurrentRun(detail);
      }
    } catch {
      /* no runs yet */
    }
  };

  const handleApproval = async (decision: 'approved' | 'rejected' | 'request_more_evidence') => {
    if (!currentRun) return;
    setActionError(null);
    try {
      await submitApproval(currentRun.id, decision);
      // Start polling for the resumed run
      setInvestigating(true);
      startPolling(currentRun.id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to submit decision');
    }
  };

  const [simulating, setSimulating] = useState(false);

  const handleResolveIncident = async (incident: Incident) => {
    setActionError(null);
    try {
      const updated = await resolveIncident(incident.id, 'Resolved via dashboard operator');
      setSelectedIncident(updated);
      setIncidents((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      if (currentRun) {
        fetchRun(currentRun.id).then(setCurrentRun).catch(() => undefined);
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to resolve incident');
    }
  };

  const handleTriggerSimulation = async (scenarioKey: string) => {
    setActionError(null);
    setSimulating(true);
    try {
      await startScenario(scenarioKey);
      await generateScenarioTraffic();
      const titles: Record<string, { title: string; desc: string; severity: 'critical' | 'high' | 'medium' }> = {
        db_conn_exhaustion: {
          title: 'ShopAPI database connection pool exhaustion',
          desc: 'Customer requests timing out due to connection pool exhaustion.',
          severity: 'critical',
        },
        db_latency: {
          title: 'ShopAPI latency spike on /products catalog endpoint',
          desc: 'Customer requests experiencing p95 response times over 1.4s.',
          severity: 'high',
        },
        bad_release: {
          title: 'ShopAPI bad release query degradation',
          desc: 'Slow response times following deployment of release v1.4.2.',
          severity: 'medium',
        },
      };
      const meta = titles[scenarioKey] || {
        title: `Simulated Fault: ${scenarioKey}`,
        desc: `Active fault injected via scenario ${scenarioKey}`,
        severity: 'high',
      };
      const created = await createIncident({
        title: meta.title,
        description: meta.desc,
        service: 'shopapi',
        severity: meta.severity,
        source: 'simulator',
        scenario_key: scenarioKey,
      });
      const incs = await fetchIncidents();
      setIncidents(incs.items);
      setSelectedIncident(created);
      setCurrentRun(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to trigger fault scenario');
    } finally {
      setSimulating(false);
    }
  };

  /* ═══════════════════════════════════════════════════════════
     RENDER
     ═══════════════════════════════════════════════════════════ */
  return (
    <div className="app-layout">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <RavelLogo size={34} className="brand-logo" />
          <div className="brand-text">
            <h1>Ravel</h1>
            <span>Incident intelligence</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          <div className="sidebar-section-label">Navigation</div>
          <a className="nav-item" href="http://127.0.0.1:5174" target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
            <span className="nav-icon"><CpuIcon size={18} /></span>
            Open Shop app
            <span className="shop-nav-live">LIVE</span>
          </a>
          <div
            className={`nav-item ${page === 'dashboard' ? 'active' : ''}`}
            onClick={() => setPage('dashboard')}
          >
            <span className="nav-icon"><DashboardIcon size={18} /></span>
            Command center
            {openCount + investigatingCount > 0 && (
              <span className="nav-badge">{openCount + investigatingCount}</span>
            )}
          </div>
          <div
            className={`nav-item ${page === 'orchestration' ? 'active' : ''}`}
            onClick={() => setPage('orchestration')}
          >
            <span className="nav-icon"><NetworkIcon size={18} /></span>
            Agent graph
          </div>
          <div
            className={`nav-item ${page === 'observability' ? 'active' : ''}`}
            onClick={() => setPage('observability')}
          >
            <span className="nav-icon"><SignalIcon size={18} /></span>
            Observability
          </div>

          <div className="sidebar-section-label">Quick Links</div>
          <a
            className="nav-item"
            href="http://127.0.0.1:8000/docs"
            target="_blank"
            rel="noreferrer"
            style={{ textDecoration: 'none' }}
          >
            <span className="nav-icon"><BookIcon size={18} /></span>
            API Docs
            <ExternalLinkIcon size={12} style={{ marginLeft: 'auto', opacity: 0.4 }} />
          </a>
          <a
            className="nav-item"
            href="http://127.0.0.1:8000/metrics"
            target="_blank"
            rel="noreferrer"
            style={{ textDecoration: 'none' }}
          >
            <span className="nav-icon"><ChartIcon size={18} /></span>
            Metrics
            <ExternalLinkIcon size={12} style={{ marginLeft: 'auto', opacity: 0.4 }} />
          </a>
        </nav>

        <div className="sidebar-status">
          <div className="status-indicator">
            <span className={`status-pulse ${healthError ? 'error' : ''}`} />
            {health
              ? `API: ${health.status} · DB: ${health.checks.database}`
              : healthError
                ? 'Connection failed'
                : 'Connecting…'}
          </div>
        </div>
      </aside>

      {/* ── Main Content ── */}
      <main className="main-content">
        <div className="page-content">
          {page === 'dashboard' && (
            <DashboardPage
              incidents={incidents}
              openCount={openCount}
              investigatingCount={investigatingCount}
              health={health}
              healthError={healthError}
              selectedIncident={selectedIncident}
              currentRun={currentRun}
              investigating={investigating}
              simulating={simulating}
              actionError={actionError}
              onSelectIncident={handleSelectIncident}
              onInvestigate={handleInvestigate}
              onResolveIncident={handleResolveIncident}
              onTriggerSimulation={handleTriggerSimulation}
              onApproval={handleApproval}
              onDismissError={() => setActionError(null)}
            />
          )}
          {page === 'orchestration' && (
            <OrchestrationPage
              incidents={incidents}
              onTriggerSimulation={handleTriggerSimulation}
            />
          )}
          {page === 'observability' && <ObservabilityPage />}
        </div>
      </main>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   DASHBOARD PAGE
   ═══════════════════════════════════════════════════════════ */

interface DashboardProps {
  incidents: Incident[];
  openCount: number;
  investigatingCount: number;
  health: HealthResponse | null;
  healthError: boolean;
  selectedIncident: Incident | null;
  currentRun: RunDetail | null;
  investigating: boolean;
  simulating: boolean;
  actionError: string | null;
  onSelectIncident: (i: Incident) => void;
  onInvestigate: (i: Incident) => void;
  onResolveIncident: (i: Incident) => void;
  onTriggerSimulation: (scenarioKey: string) => void;
  onApproval: (d: 'approved' | 'rejected' | 'request_more_evidence') => void;
  onDismissError: () => void;
}

function DashboardPage({
  incidents,
  openCount,
  investigatingCount,
  health,
  healthError,
  selectedIncident,
  currentRun,
  investigating,
  simulating,
  actionError,
  onSelectIncident,
  onInvestigate,
  onResolveIncident,
  onTriggerSimulation,
  onApproval,
  onDismissError,
}: DashboardProps) {
  const [simScenario, setSimScenario] = useState('db_conn_exhaustion');
  const [viewMode, setViewMode] = useState<'multiagent' | 'timeline' | 'audit'>('multiagent');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'open' | 'investigating' | 'resolved'>('all');
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [runEvents, setRunEvents] = useState<RunEvent[]>([]);

  useEffect(() => {
    if (!selectedIncident) {
      setAuditEvents([]);
      return;
    }
    fetchIncidentAudit(selectedIncident.id)
      .then(setAuditEvents)
      .catch(() => setAuditEvents([]));
  }, [selectedIncident, currentRun?.status]);

  useEffect(() => {
    if (!currentRun) {
      setRunEvents([]);
      return;
    }
    fetchRunEvents(currentRun.id)
      .then(setRunEvents)
      .catch(() => setRunEvents([]));
  }, [currentRun]);

  const query = searchQuery.trim().toLowerCase();
  const filtered = incidents.filter((incident) => {
    const matchesStatus =
      statusFilter === 'all'
      || (statusFilter === 'investigating'
        ? ['investigating', 'awaiting_approval', 'remediating', 'verifying'].includes(incident.status)
        : incident.status === statusFilter);
    const matchesQuery =
      !query
      || incident.title.toLowerCase().includes(query)
      || incident.service.toLowerCase().includes(query)
      || (incident.scenario_key ?? '').toLowerCase().includes(query);
    return matchesStatus && matchesQuery;
  });

  const sorted = [...filtered].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3),
  );

  return (
    <>
      {/* Page Header */}
      <div className="page-header">
        <div>
          <div className="eyebrow">LIVE OPERATIONS / LANGGRAPH</div>
          <h1 className="page-title">Command center</h1>
          <p className="page-subtitle">Turn noisy telemetry into an explainable, human-approved recovery.</p>
        </div>
        <div className="header-actions">
          <select
            value={simScenario}
            onChange={(e) => setSimScenario(e.target.value)}
            className="scenario-select"
          >
            <option value="db_conn_exhaustion">DB Pool Exhaustion (Critical)</option>
            <option value="db_latency">ShopAPI High Latency (High)</option>
            <option value="bad_release">Bad Release Degradation (Medium)</option>
          </select>
          <button
            className="simulate-btn"
            onClick={() => onTriggerSimulation(simScenario)}
            disabled={simulating}
          >
            <ZapIcon size={14} />
            {simulating ? 'Preparing…' : 'Inject scenario'}
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {actionError && (
        <div className="error-banner">
          <AlertTriangleIcon size={18} />
          <p>{actionError}</p>
          <button onClick={onDismissError}>Dismiss</button>
        </div>
      )}

      <LiveSystemStage
        incidents={incidents}
        selectedIncident={selectedIncident}
        currentRun={currentRun}
        investigating={investigating}
        backendOnline={Boolean(health) && !healthError}
      />

      {/* Two-column: Incident List + Detail Panel */}
      <div className="incident-workspace" style={{ display: 'grid', gridTemplateColumns: selectedIncident ? '310px 1fr' : '1fr', gap: '1rem', alignItems: 'start' }}>
        {/* Incident List */}
        <div className="section-card">
          <div className="section-header">
            <span className="section-title">
              <span className="icon"><AlertTriangleIcon size={16} /></span>
              Incidents
            </span>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{openCount + investigatingCount} active</span>
          </div>
          <div className="incident-filter-toolbar">
            <div className="incident-search-box">
              <SearchIcon size={13} />
              <input
                type="search"
                placeholder="Filter by title or service…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                aria-label="Filter incidents"
              />
            </div>
            <div className="incident-filter-pills">
              {(['all', 'open', 'investigating', 'resolved'] as const).map((status) => (
                <button
                  key={status}
                  type="button"
                  className={`filter-pill ${statusFilter === status ? 'active' : ''}`}
                  onClick={() => setStatusFilter(status)}
                >
                  {status === 'all' ? 'All' : status.charAt(0).toUpperCase() + status.slice(1)}
                </button>
              ))}
            </div>
          </div>
          {sorted.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon"><InboxIcon size={48} /></div>
              <p>
                {incidents.length === 0
                  ? <>No incidents yet.<br />Seed demo data to get started.</>
                  : 'No incidents match this filter.'}
              </p>
            </div>
          ) : (
            <ul className="incident-list">
              {sorted.slice(0, 8).map((incident) => (
                <li
                  key={incident.id}
                  className={`incident-row ${selectedIncident?.id === incident.id ? 'selected' : ''}`}
                  onClick={() => onSelectIncident(incident)}
                >
                  <span className={`incident-severity ${severityColor(incident.severity)}`} />
                  <div className="incident-info">
                    <div className="incident-title">{incident.title}</div>
                    <div className="incident-meta">
                      <span>{incident.severity}</span>
                      <span>·</span>
                      <span>{incident.service}</span>
                    </div>
                  </div>
                  <span className={`incident-status-badge ${incident.status}`}>
                    {incident.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Detail Panel */}
        {selectedIncident && (
          <div>
            <div className="detail-panel">
              {/* Incident Header */}
              <div className="detail-header">
                <div className="detail-title-group">
                  <h2>{selectedIncident.title}</h2>
                  <p>{selectedIncident.description || `Service: ${selectedIncident.service}`}</p>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <span className={`severity-badge ${severityColor(selectedIncident.severity)}`}>
                    {selectedIncident.severity}
                  </span>
                  {!investigating && selectedIncident.status !== 'resolved' && (
                    <>
                      <button
                        className="incident-action-btn"
                        onClick={() => onInvestigate(selectedIncident)}
                      >
                        <PlayIconSmall /> Investigate
                      </button>
                      <button
                        className="incident-action-btn resolve"
                        onClick={() => onResolveIncident(selectedIncident)}
                        title="Mark incident as resolved"
                      >
                        <CheckSmall /> Mark Resolved
                      </button>
                    </>
                  )}
                  {selectedIncident.status === 'resolved' && (
                    <span className="incident-status-badge resolved" style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem' }}>
                      <CheckSmall /> Resolved
                    </span>
                  )}
                </div>
              </div>

              {/* Loading bar when investigating */}
              {investigating && (
                <div className="loading-bar">
                  <div className="loading-bar-fill" />
                </div>
              )}

              {/* View Mode Switcher */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.65rem 1.25rem', borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-card-elevated)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  <NetworkIcon size={14} /> Orchestration View:
                </div>
                <div className="view-mode-toggle">
                  <button
                    className={`view-mode-btn ${viewMode === 'multiagent' ? 'active' : ''}`}
                    onClick={() => setViewMode('multiagent')}
                  >
                    <NetworkIcon size={12} /> Multi-Agent Graph
                  </button>
                  <button
                    className={`view-mode-btn ${viewMode === 'timeline' ? 'active' : ''}`}
                    onClick={() => setViewMode('timeline')}
                  >
                    <ActivityIcon size={12} /> Pipeline Timeline
                  </button>
                  <button
                    className={`view-mode-btn ${viewMode === 'audit' ? 'active' : ''}`}
                    onClick={() => setViewMode('audit')}
                  >
                    <ClipboardListIcon size={12} /> Audit & Events ({auditEvents.length + runEvents.length})
                  </button>
                </div>
              </div>

              {/* Multi-Agent Orchestration View */}
              {viewMode === 'multiagent' && (
                <div style={{ padding: '1.25rem' }}>
                  <MultiAgentView
                    currentRun={currentRun}
                    incident={selectedIncident}
                    investigating={investigating}
                    onApproval={onApproval}
                  />
                </div>
              )}

              {/* Classic Timeline View */}
              {viewMode === 'timeline' && (
                <>
                  {/* Workflow Pipeline */}
                  {(currentRun || investigating) && (
                    <WorkflowPipeline
                      status={currentRun?.status ?? 'running'}
                      isAwaitingApproval={currentRun?.is_awaiting_approval ?? false}
                      investigating={investigating}
                      evidenceCount={currentRun?.evidence.length ?? 0}
                      modelName={currentRun?.run.model_name}
                    />
                  )}

                  {/* Evidence Cards */}
                  {currentRun && currentRun.evidence.length > 0 && (
                    <div className="evidence-section">
                      <div className="compact-section-heading">
                        <strong>What the system found</strong>
                        <span>{currentRun.evidence.length} signals</span>
                      </div>
                      <div className="evidence-grid">
                        {currentRun.evidence.map((ev, idx) => (
                          <div className="evidence-card" key={ev.id} style={{ '--stagger': idx } as React.CSSProperties}>
                            <div className="evidence-card-header">
                              <span className={`evidence-source-icon ${ev.source_type}`}>
                                {ev.source_type === 'logs'
                                  ? <FileTextIcon size={14} />
                                  : ev.source_type === 'metrics'
                                    ? <ActivityIcon size={14} />
                                    : ev.source_type === 'traces'
                                      ? <LinkIcon size={14} />
                                      : <RocketIcon size={14} />}
                              </span>
                              <span className="evidence-source-label">{ev.source_type}</span>
                              {ev.confidence != null && (
                                <span className="evidence-confidence">
                                  {(ev.confidence * 100).toFixed(0)}%
                                </span>
                              )}
                            </div>
                            <p className="evidence-summary">{ev.summary}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Hypothesis / Root Cause */}
                  {currentRun && currentRun.hypotheses && currentRun.hypotheses.length > 0 && (
                    <div className="hypothesis-section">
                      {currentRun.hypotheses.slice(0, 1).map((h, i) => (
                        <div className="hypothesis-card" key={i}>
                          <div className="hypothesis-header">
                            <span className="hypothesis-title">
                              <TargetIcon size={18} /> Most likely cause
                            </span>
                            <ConfidenceRing value={h.confidence} />
                          </div>
                          <strong className="hypothesis-name">{h.title}</strong>
                          <p className="hypothesis-desc">{h.description}</p>
                          {h.supporting_evidence_ids.length > 0 && (
                            <p className="hypothesis-citations">
                              Citing {h.supporting_evidence_ids.length} evidence item(s)
                              {h.contradictions.length > 0 &&
                                ` · ${h.contradictions.length} contradiction(s)`}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}

              {/* Audit & Event Stream View */}
              {viewMode === 'audit' && (
                <div className="audit-panel">
                  <div className="audit-section">
                    <div className="compact-section-heading">
                      <strong>Incident Audit Ledger</strong>
                      <span>{auditEvents.length} entries</span>
                    </div>
                    {auditEvents.length === 0 ? (
                      <p className="audit-empty">No audit trail entries recorded yet.</p>
                    ) : (
                      <div className="audit-list">
                        {auditEvents.map((ev) => (
                          <div key={ev.id} className="audit-row">
                            <div className="audit-row-head">
                              <span className="audit-type">{ev.event_type}</span>
                              <span className="audit-actor">by {ev.actor}</span>
                              <time>{new Date(ev.created_at).toLocaleTimeString()}</time>
                            </div>
                            {ev.details_json && (
                              <pre className="audit-details">{JSON.stringify(ev.details_json)}</pre>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="audit-section">
                    <div className="compact-section-heading">
                      <strong>Persisted SSE Run Stream</strong>
                      <span>{runEvents.length} events</span>
                    </div>
                    {runEvents.length === 0 ? (
                      <p className="audit-empty">Start an investigation to record stream events.</p>
                    ) : (
                      <div className="audit-list">
                        {runEvents.map((ev) => (
                          <div key={ev.id} className="audit-row">
                            <div className="audit-row-head">
                              <span className="audit-seq">#{ev.sequence}</span>
                              <span className="audit-type">{ev.event_type}</span>
                              <time>{new Date(ev.created_at).toLocaleTimeString()}</time>
                            </div>
                            {ev.payload_json && (
                              <pre className="audit-details">{JSON.stringify(ev.payload_json)}</pre>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Run result */}
              {currentRun && !currentRun.is_awaiting_approval && !investigating && (
                <RunResultBanner
                  run={currentRun}
                  incident={selectedIncident}
                  onResolve={() => onResolveIncident(selectedIncident)}
                />
              )}
            </div>

            {/* Approval Panel */}
            {currentRun?.is_awaiting_approval && currentRun.approval && (
              <div className="approval-panel">
                <div className="approval-header">
                  <div className="approval-icon"><ShieldIcon size={20} /></div>
                  <div>
                    <div className="approval-title">Your decision is needed</div>
                    <div className="approval-subtitle">
                        The investigation is paused. Choose what happens next.
                    </div>
                  </div>
                </div>
                <div className="approval-body">
                  <div className="approval-action-tag">
                    <TerminalIcon size={14} /> {currentRun.approval.action_type}
                  </div>
                  <p className="approval-reasoning">{currentRun.approval.reasoning}</p>
                  <span className={`approval-risk ${currentRun.approval.risk}`}>
                    Risk: {currentRun.approval.risk}
                  </span>
                  <div className="approval-actions">
                    <button className="btn btn-approve" onClick={() => onApproval('approved')}>
                      <CheckSmall /> Approve Action
                    </button>
                    <button className="btn btn-reject" onClick={() => onApproval('rejected')}>
                      <XSmall /> Reject
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={() => onApproval('request_more_evidence')}
                    >
                      <RefreshIcon size={14} /> Request More Evidence
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Placeholder when no incident selected */}
        {!selectedIncident && incidents.length > 0 && (
          <div className="section-card" style={{ display: 'none' }}>
            {/* hidden to avoid layout shift */}
          </div>
        )}
      </div>

      {/* Footer */}
      <footer className="page-footer">
        <p>
          <AlertTriangleIcon size={12} style={{ verticalAlign: 'middle', marginRight: '0.35rem' }} />
          This is a <strong>simulated</strong> incident response system. All remediation is
          sandboxed — nothing touches real infrastructure.
        </p>
      </footer>
    </>
  );
}

function LiveSystemStage({
  incidents,
  selectedIncident,
  currentRun,
  investigating,
  backendOnline,
}: {
  incidents: Incident[];
  selectedIncident: Incident | null;
  currentRun: RunDetail | null;
  investigating: boolean;
  backendOnline: boolean;
}) {
  const activeIncident = selectedIncident ?? incidents.find((item) => item.status !== 'resolved') ?? null;
  const active = Boolean(activeIncident && activeIncident.status !== 'resolved');
  const evidenceSources = new Set(currentRun?.evidence.map((item) => item.source_type) ?? []);
  const agentState = (source: string) =>
    investigating ? 'working' : evidenceSources.has(source) ? 'done' : active ? 'ready' : 'idle';

  return (
    <section className="live-stage" aria-label="Live ShopAPI and multi-agent activity">
      <div className="live-stage-head">
        <div>
          <span className="live-kicker"><span className="live-dot" /> LIVE SYSTEM</span>
          <strong>See the incident happen</strong>
        </div>
        <span className={`service-pill ${backendOnline ? 'online' : 'offline'}`}>
          {backendOnline ? 'Stack online' : 'Start backend to stream'}
        </span>
      </div>

      <div className="system-flow">
        <div className={`flow-panel shop-panel ${active ? 'degraded' : ''}`}>
          <div className="flow-panel-label">01 / SERVICE</div>
          <div className="service-title"><CpuIcon size={20} /> ShopAPI</div>
          <div className="endpoint-row"><code>GET /products</code><span>{active ? '5xx / slow' : '200 OK'}</span></div>
          <div className="request-stream" aria-hidden="true">
            {[0, 1, 2, 3, 4].map((item) => <i key={item} style={{ '--pulse': item } as React.CSSProperties} />)}
          </div>
          <div className="service-metric">
            <span>p95 latency</span>
            <strong>{active ? '1,420 ms' : '84 ms'}</strong>
          </div>
        </div>

        <div className={`flow-arrow ${active ? 'hot' : ''}`}>
          <span>{active ? 'INCIDENT' : 'TELEMETRY'}</span><b>→</b>
        </div>

        <div className="flow-panel swarm-panel">
          <div className="flow-panel-label">02 / LANGGRAPH TEAM</div>
          <div className="swarm-head"><BrainIcon size={18} /> Commander <span>{investigating ? 'routing' : active ? 'ready' : 'watching'}</span></div>
          <div className="agent-mini-grid">
            {[
              ['logs', 'Logs', FileTextIcon],
              ['metrics', 'Metrics', ActivityIcon],
              ['traces', 'Traces', LinkIcon],
              ['changes', 'Changes', RocketIcon],
            ].map(([source, label, Icon]) => {
              const MiniIcon = Icon as typeof ActivityIcon;
              const state = agentState(source as string);
              return <div className={`agent-mini ${state}`} key={source as string}><MiniIcon size={13} /><span>{label as string}</span><i /></div>;
            })}
          </div>
        </div>

        <div className="flow-arrow"><span>DECISION</span><b>→</b></div>

        <div className={`flow-panel outcome-panel ${currentRun?.is_awaiting_approval ? 'waiting' : ''}`}>
          <div className="flow-panel-label">03 / SAFE RECOVERY</div>
          <ShieldIcon size={22} />
          <strong>{currentRun?.is_awaiting_approval ? 'Approval needed' : currentRun ? 'Evidence synthesized' : 'Human stays in control'}</strong>
          <span>{currentRun?.evidence.length ?? 0} cited signals</span>
        </div>
      </div>

      {activeIncident && (
        <div className="live-incident-strip">
          <span className={`incident-severity ${severityColor(activeIncident.severity)}`} />
          <strong>{activeIncident.title}</strong>
          <span>{activeIncident.status}</span>
        </div>
      )}
    </section>
  );
}

/* ── Tiny inline icon helpers for buttons ── */
function PlayIconSmall() {
  return (
    <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor" style={{ marginRight: '0.25rem' }}>
      <polygon points="0,0 10,6 0,12" />
    </svg>
  );
}
function CheckSmall() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '0.2rem' }}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}
function XSmall() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" style={{ marginRight: '0.2rem' }}>
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════
   WORKFLOW PIPELINE COMPONENT
   ═══════════════════════════════════════════════════════════ */

function WorkflowPipeline({
  status,
  isAwaitingApproval,
  investigating,
  evidenceCount,
  modelName,
}: {
  status: string;
  isAwaitingApproval: boolean;
  investigating: boolean;
  evidenceCount: number;
  modelName: string | null | undefined;
}) {
  const activeIdx = investigating && status === 'running' && !isAwaitingApproval
    ? 2
    : resolveStageIndex(status, isAwaitingApproval);
  const allDone = activeIdx >= PIPELINE_STAGES.length;
  const activeStage = isAwaitingApproval
    ? PIPELINE_STAGES[4]
    : activeIdx >= 0 && activeIdx < PIPELINE_STAGES.length
      ? PIPELINE_STAGES[activeIdx]
      : null;

  return (
    <div className="workflow-progress">
      <div className={`current-step ${isAwaitingApproval ? 'waiting' : allDone ? 'done' : ''}`}>
        <div className="current-step-heading">
          <span className="current-step-icon">
            {allDone
              ? <CheckCircleIcon size={22} />
              : activeStage?.icon ?? <AlertTriangleIcon size={22} />}
          </span>
          <div>
            <span className="current-step-kicker">{allDone ? 'Workflow complete' : 'Currently happening'}</span>
            <strong>
              {allDone ? 'The incident investigation is finished' : activeStage?.label ?? 'Investigation stopped'}
            </strong>
          </div>
        </div>
        <p>
          {allDone
            ? 'The system checked the result. Review the summary below.'
            : activeStage?.description ?? 'Check the error message and try again.'}
        </p>
        {!allDone && !isAwaitingApproval && (
          <span className="current-step-note">This step updates automatically.</span>
        )}
        {isAwaitingApproval && (
          <span className="current-step-note">Nothing will change until you choose an action below.</span>
        )}
        {(evidenceCount > 0 || modelName) && (
          <div className="run-facts">
            {evidenceCount > 0 && <span>{evidenceCount} signals</span>}
            {modelName && <span>{modelName}</span>}
          </div>
        )}
      </div>
      <div className="pipeline-track">
        {PIPELINE_STAGES.map((stage, i) => {
          let state: 'pending' | 'completed' | 'active' | 'waiting' | 'error' = 'pending';
          if (allDone) {
            state = 'completed';
          } else if (activeIdx === -1) {
            state = i === 0 ? 'error' : 'pending';
          } else if (i < activeIdx) {
            state = 'completed';
          } else if (i === activeIdx) {
            state = isAwaitingApproval && stage.key === 'approval' ? 'waiting' : 'active';
          }

          return (
            <div key={stage.key} style={{ display: 'flex', alignItems: 'center' }}>
              {i > 0 && (
                <div
                  className={`pipeline-connector ${
                    state === 'completed' ? 'completed' : state === 'active' || state === 'waiting' ? 'active' : ''
                  }`}
                />
              )}
              <div className="pipeline-step">
                <div className={`step-node ${state}`}>{stage.icon}</div>
                <span className={`step-label ${state}`}>{stage.label}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   CONFIDENCE RING COMPONENT
   ═══════════════════════════════════════════════════════════ */

function ConfidenceRing({ value }: { value: number }) {
  const circumference = 2 * Math.PI * 16;
  const offset = circumference * (1 - value);
  return (
    <div className="confidence-ring">
      <svg viewBox="0 0 40 40">
        <circle className="bg" cx="20" cy="20" r="16" />
        <circle
          className="fill"
          cx="20"
          cy="20"
          r="16"
          strokeDasharray={`${circumference}`}
          strokeDashoffset={`${offset}`}
        />
      </svg>
      <span className="confidence-value">{(value * 100).toFixed(0)}%</span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   RUN RESULT BANNER
   ═══════════════════════════════════════════════════════════ */

function RunResultBanner({
  run,
  incident,
  onResolve,
}: {
  run: RunDetail;
  incident: Incident;
  onResolve?: () => void;
}) {
  const status = run.status;
  const isIncidentResolved = incident.status === 'resolved';
  const isRunSuccess = status === 'completed' || status === 'resolved';
  const isFailed = status === 'failed';

  return (
    <div className="run-result">
      <div
        className={`result-banner ${
          isIncidentResolved
            ? 'resolved'
            : isRunSuccess
              ? 'completed'
              : isFailed
                ? 'failed'
                : 'completed'
        }`}
      >
        <span className="result-icon">
          {isIncidentResolved
            ? <CheckCircleIcon size={24} />
            : isRunSuccess
              ? <TargetIcon size={24} />
              : isFailed
                ? <XCircleIcon size={24} />
                : <ClipboardListIcon size={24} />}
        </span>
        <div className="result-text" style={{ flex: 1 }}>
          <strong>
            {isIncidentResolved
              ? 'Incident Successfully Resolved'
              : isRunSuccess
                ? 'Investigation & Verification Complete'
                : isFailed
                  ? 'Investigation Failed'
                  : `Run Status: ${status}`}
          </strong>
          <p>
            {isIncidentResolved
              ? 'The fix was checked and the incident is resolved.'
              : isRunSuccess
                ? 'The workflow finished successfully. You can close the incident.'
                : isFailed
                  ? 'The investigation stopped because of an error.'
                  : 'The workflow has stopped.'}
          </p>
        </div>
        {!isIncidentResolved && isRunSuccess && onResolve && (
          <button
            className="incident-action-btn resolve"
            onClick={onResolve}
            style={{ marginLeft: 'auto', alignSelf: 'center' }}
          >
            <CheckSmall /> Mark Incident Resolved
          </button>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   OBSERVABILITY PAGE
   ═══════════════════════════════════════════════════════════ */

function ObservabilityPage() {
  return (
    <>
      <div className="page-header">
        <div>
          <div className="eyebrow">SYSTEM PULSE / OPEN TELEMETRY</div>
          <h1 className="page-title">Signals</h1>
          <p className="page-subtitle">
            Distributed tracing, metrics, and dashboards
          </p>
        </div>
      </div>

      <div className="section-card">
        <div className="section-header">
          <span className="section-title">
            <span className="icon"><LinkIcon size={16} /></span>
            External Services
          </span>
        </div>
        <div className="obs-links">
          <a className="obs-link" href="http://localhost:3000/d/ravel-main" target="_blank" rel="noreferrer">
            <span className="link-dot grafana" />
            Grafana Dashboard
            <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}>:3000</span>
          </a>
          <a className="obs-link" href="http://localhost:16686" target="_blank" rel="noreferrer">
            <span className="link-dot jaeger" />
            Jaeger Traces
            <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}>:16686</span>
          </a>
          <a className="obs-link" href="http://localhost:9090" target="_blank" rel="noreferrer">
            <span className="link-dot prometheus" />
            Prometheus
            <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}>:9090</span>
          </a>
          <a className="obs-link" href="http://127.0.0.1:8000/metrics" target="_blank" rel="noreferrer">
            <span className="link-dot prometheus" />
            Raw /metrics
            <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}>:8000</span>
          </a>
        </div>
      </div>

      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <div className="section-card obs-feature-card" style={{ '--stagger': 0 } as React.CSSProperties}>
          <div className="obs-feature-icon"><ActivityIcon size={24} /></div>
          <h3>Prometheus Metrics</h3>
          <p>
            Route-template cardinality-safe metrics including HTTP request counts, latency histograms
            (P50/P95/P99), error rates, and simulator fault gauges.
          </p>
        </div>
        <div className="section-card obs-feature-card" style={{ '--stagger': 1 } as React.CSSProperties}>
          <div className="obs-feature-icon"><SearchIcon size={24} /></div>
          <h3>OpenTelemetry Tracing</h3>
          <p>
            W3C traceparent propagation across API endpoints, LangGraph nodes, and evidence tool
            calls. Spans are exported via OTLP/HTTP to Jaeger.
          </p>
        </div>
        <div className="section-card obs-feature-card" style={{ '--stagger': 2 } as React.CSSProperties}>
          <div className="obs-feature-icon"><FileTextIcon size={24} /></div>
          <h3>Structured Logging</h3>
          <p>
            JSON-formatted logs with trace ID and span ID correlation. Structured metadata enables
            filtering by run ID, incident ID, and scenario key.
          </p>
        </div>
      </div>

      <div className="section-card" style={{ padding: '1.5rem' }}>
        <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <TerminalIcon size={18} /> How to Start the Observability Stack
        </h3>
        <div className="code-block">
          <div className="code-comment"># Start Prometheus, Grafana, and Jaeger</div>
          <div>docker compose --profile observability up -d</div>
          <br />
          <div className="code-comment"># Then visit:</div>
          <div>
            Grafana → <span className="code-highlight">http://localhost:3000</span>{' '}
            (admin/admin)
          </div>
          <div>
            Jaeger → <span className="code-highlight">http://localhost:16686</span>
          </div>
          <div>
            Prometheus → <span className="code-highlight">http://localhost:9090</span>
          </div>
        </div>
      </div>

      <footer className="page-footer">
        <p>
          <AlertTriangleIcon size={12} style={{ verticalAlign: 'middle', marginRight: '0.35rem' }} />
          Observability services require <strong>Docker Compose</strong> with the{' '}
          <strong>observability</strong> profile enabled.
        </p>
      </footer>
    </>
  );
}

export default App;
