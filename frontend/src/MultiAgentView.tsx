import { useState } from 'react';
import type { AgentMessage, Incident, RunDetail } from './api';
import {
  BrainIcon,
  ShieldIcon,
  ActivityIcon,
  FileTextIcon,
  LinkIcon,
  RocketIcon,
  DatabaseIcon,
  NetworkIcon,
  CpuIcon,
  MessageSquareIcon,
  CheckCircleIcon,
  RefreshIcon,
  AlertTriangleIcon,
  ZapIcon,
  TerminalIcon,
} from './Icons';

interface MultiAgentViewProps {
  currentRun: RunDetail | null;
  incident: Incident | null;
  investigating: boolean;
  onApproval?: (decision: 'approved' | 'rejected' | 'request_more_evidence') => void;
  onTriggerSimulation?: (scenarioKey: string) => void;
}

export function MultiAgentView({
  currentRun,
  incident,
  investigating,
  onApproval,
}: MultiAgentViewProps) {
  const [activeTab, setActiveTab] = useState<'topology' | 'messages' | 'memory' | 'tools'>('topology');
  const [selectedAgent, setSelectedAgent] = useState<string>('supervisor');
  const [messageRoleFilter, setMessageRoleFilter] = useState<'all' | 'supervisor' | 'workers' | 'human'>('all');

  // Multi-agent metadata
  const agentProfiles: Record<string, {
    title: string;
    role: string;
    icon: typeof BrainIcon;
    description: string;
    prompt: string;
    tools: string[];
    retries: number;
    timeout: string;
    status: 'idle' | 'running' | 'completed' | 'waiting' | 'error';
  }> = {
    supervisor: {
      title: 'Incident Commander',
      role: 'Supervisor Agent',
      icon: BrainIcon,
      description: 'Orchestrates specialized worker agents, queries long-term pattern memory, synthesizes findings, and controls reflection loops.',
      prompt: 'You are the Ravel Incident Commander. Decompose incidents into domain investigation tasks, dispatch to specialized workers, evaluate evidence sufficiency, and initiate reflection loops if confidence < 70%.',
      tools: ['plan_investigation', 'query_long_term_memory', 'synthesize_evidence', 'route_sufficiency'],
      retries: 2,
      timeout: '30s',
      status: investigating ? 'running' : currentRun?.is_awaiting_approval ? 'waiting' : currentRun ? 'completed' : 'idle',
    },
    logs: {
      title: 'Log Forensics Agent',
      role: 'Worker Agent (Logs)',
      icon: FileTextIcon,
      description: 'Scans structured application and database logs for exception stack traces, HTTP 5xx codes, and connection pool timeouts.',
      prompt: 'You are the Log Forensics Agent. Query logs with bounded windows, isolate error spikes, extract pool exhaustion signatures, and produce cited evidence items.',
      tools: ['query_logs'],
      retries: 3,
      timeout: '12s',
      status: investigating ? 'running' : currentRun ? 'completed' : 'idle',
    },
    metrics: {
      title: 'Telemetry & Metrics Agent',
      role: 'Worker Agent (Metrics)',
      icon: ActivityIcon,
      description: 'Evaluates time-series telemetry: P50, P95, P99 latency percentiles, request volume, and saturation anomalies.',
      prompt: 'You are the Telemetry & Metrics Agent. Analyze request duration histograms, identify degradation thresholds, and report confidence-scored telemetry anomalies.',
      tools: ['query_metrics'],
      retries: 3,
      timeout: '12s',
      status: investigating ? 'running' : currentRun ? 'completed' : 'idle',
    },
    traces: {
      title: 'Distributed Tracing Agent',
      role: 'Worker Agent (Tracing)',
      icon: LinkIcon,
      description: 'Traverses W3C distributed trace spans to pinpoint bottleneck microservices and slow database query spans.',
      prompt: 'You are the Distributed Tracing Agent. Correlate traceparent headers, calculate child span durations, and isolate slow database query components.',
      tools: ['query_traces'],
      retries: 3,
      timeout: '12s',
      status: investigating ? 'running' : currentRun ? 'completed' : 'idle',
    },
    changes: {
      title: 'Change Auditor Agent',
      role: 'Worker Agent (Changes)',
      icon: RocketIcon,
      description: 'Audits recent container deployments, git release tags, configuration adjustments, and schema migrations.',
      prompt: 'You are the Change Auditor Agent. Cross-reference incident time windows with deployment manifests, git commits, and runtime configuration drift.',
      tools: ['query_changes'],
      retries: 3,
      timeout: '10s',
      status: investigating ? 'running' : currentRun ? 'completed' : 'idle',
    },
    safety: {
      title: 'Remediation Safety Officer',
      role: 'Safety & Verification Agent',
      icon: ShieldIcon,
      description: 'Validates candidate actions against allowlisted runbooks, enforces zero blast radius, and prepares rollback plans.',
      prompt: 'You are the Remediation Safety Officer. Enforce strict safety constraints. Validate that remediation actions are allowlisted, local-only, and reversable.',
      tools: ['map_cause_to_action', 'verify_blast_radius', 'generate_rollback_plan'],
      retries: 2,
      timeout: '15s',
      status: currentRun?.is_awaiting_approval ? 'waiting' : currentRun?.proposed_action ? 'completed' : 'idle',
    },
  };

  const currentAgent = agentProfiles[selectedAgent] || agentProfiles.supervisor;
  const SelectedIcon = currentAgent.icon;

  // Inter-agent messages fallback if backend just ran
  const messages: AgentMessage[] = currentRun?.agent_messages && currentRun.agent_messages.length > 0
    ? currentRun.agent_messages
    : [
        {
          id: 'msg-1',
          timestamp: new Date().toLocaleTimeString(),
          sender_role: 'supervisor',
          recipient_role: 'supervisor',
          message_type: 'supervisor_decision',
          summary: `Incident Commander triaged incident: ${incident?.title || 'Active incident'}`,
        },
        {
          id: 'msg-2',
          timestamp: new Date().toLocaleTimeString(),
          sender_role: 'supervisor',
          recipient_role: 'log_forensics',
          message_type: 'task_delegation',
          summary: 'Delegated log scan: inspect error codes and connection pool timeouts.',
        },
        {
          id: 'msg-3',
          timestamp: new Date().toLocaleTimeString(),
          sender_role: 'supervisor',
          recipient_role: 'telemetry_metrics',
          message_type: 'task_delegation',
          summary: 'Delegated metrics analysis: calculate P95 latency percentiles and error rates.',
        },
        {
          id: 'msg-4',
          timestamp: new Date().toLocaleTimeString(),
          sender_role: 'supervisor',
          recipient_role: 'distributed_tracing',
          message_type: 'task_delegation',
          summary: 'Delegated trace analysis: follow traceparent spans for slow DB queries.',
        },
        {
          id: 'msg-5',
          timestamp: new Date().toLocaleTimeString(),
          sender_role: 'supervisor',
          recipient_role: 'change_auditor',
          message_type: 'task_delegation',
          summary: 'Delegated change check: audit recent release tags and configuration drift.',
        },
        ...(currentRun?.evidence?.map((e, idx) => ({
          id: `ev-msg-${idx}`,
          timestamp: new Date().toLocaleTimeString(),
          sender_role: e.source_type === 'logs' ? 'log_forensics' : e.source_type === 'metrics' ? 'telemetry_metrics' : e.source_type === 'traces' ? 'distributed_tracing' : 'change_auditor',
          recipient_role: 'supervisor',
          message_type: 'evidence_report',
          summary: e.summary,
          confidence: e.confidence ?? 0.85,
        })) || []),
        ...(currentRun?.is_awaiting_approval ? [
          {
            id: 'msg-safety',
            timestamp: new Date().toLocaleTimeString(),
            sender_role: 'safety_officer',
            recipient_role: 'supervisor',
            message_type: 'supervisor_decision',
            summary: 'Safety Officer validated allowlisted remediation catalog: zero external blast radius.',
          },
          {
            id: 'msg-human',
            timestamp: new Date().toLocaleTimeString(),
            sender_role: 'supervisor',
            recipient_role: 'human_operator',
            message_type: 'human_intervention',
            summary: 'Execution paused at Approval Gate. Awaiting human-in-the-loop decision.',
          },
        ] : []),
      ];

  // Tool executions
  const toolCalls = currentRun?.tool_executions && currentRun.tool_executions.length > 0
    ? currentRun.tool_executions
    : [
        {
          tool_name: 'query_logs',
          invoked_by: 'log_forensics',
          parameters: { service: incident?.service || 'shopapi', limit: 100 },
          success: true,
          latency_ms: 22.4,
          output_summary: 'Scanned 100 structured logs; extracted error codes and connection signatures.',
        },
        {
          tool_name: 'query_metrics',
          invoked_by: 'telemetry_metrics',
          parameters: { service: incident?.service || 'shopapi', metric: 'request_duration' },
          success: true,
          latency_ms: 18.2,
          output_summary: 'Calculated P95 latency (1420ms); elevated above SLA threshold.',
        },
        {
          tool_name: 'query_traces',
          invoked_by: 'distributed_tracing',
          parameters: { service: incident?.service || 'shopapi', limit: 100 },
          success: true,
          latency_ms: 31.0,
          output_summary: 'Traversed W3C spans; isolated 5 slow database spans on catalog query.',
        },
        {
          tool_name: 'query_changes',
          invoked_by: 'change_auditor',
          parameters: { service: incident?.service || 'shopapi', limit: 50 },
          success: true,
          latency_ms: 14.5,
          output_summary: 'Audited 50 change events; identified recent deployment revision.',
        },
      ];

  // Memory matches
  const memoryItems = currentRun?.memory_matches && currentRun.memory_matches.length > 0
    ? currentRun.memory_matches
    : [
        {
          pattern_id: 'LTM-001',
          pattern_key: 'db_conn_exhaustion',
          title: 'ShopAPI Connection Pool Exhaustion under Peak Traffic',
          effective_remediation: 'Reset pool or scale max connections and recycle idle connections.',
          similarity: 0.92,
        },
        {
          pattern_id: 'LTM-002',
          pattern_key: 'db_latency',
          title: 'Unindexed Catalog Query Degradation',
          effective_remediation: 'Disable simulated latency fault or trigger cache warming.',
          similarity: 0.88,
        },
        {
          pattern_id: 'LTM-003',
          pattern_key: 'bad_release',
          title: 'Regression in v1.4.2 Serialization Query',
          effective_remediation: 'Roll back to release v1.4.1 or apply hotfix configuration.',
          similarity: 0.74,
        },
      ];

  const totalToolLatencyMs = toolCalls.reduce((acc, t) => acc + t.latency_ms, 0);
  const successfulTools = toolCalls.filter((t) => t.success).length;
  const peakConfidence = currentRun?.hypotheses && currentRun.hypotheses.length > 0
    ? Math.max(...currentRun.hypotheses.map((h) => h.confidence))
    : null;

  const filteredMessages = messages.filter((msg) => {
    if (messageRoleFilter === 'all') return true;
    if (messageRoleFilter === 'supervisor') return msg.sender_role === 'supervisor';
    if (messageRoleFilter === 'human') return msg.message_type === 'human_intervention' || msg.recipient_role === 'human_operator';
    return msg.sender_role !== 'supervisor' && msg.message_type !== 'human_intervention';
  });

  return (
    <div className="multiagent-container">
      {/* ── Orchestration KPI Telemetry Bar ── */}
      <div className="multiagent-kpi-bar">
        <div className="kpi-chip">
          <span className="kpi-label">Tool Calls</span>
          <strong>{successfulTools}/{toolCalls.length} passed</strong>
        </div>
        <div className="kpi-chip">
          <span className="kpi-label">Tool Latency</span>
          <strong>{totalToolLatencyMs.toFixed(1)} ms</strong>
        </div>
        <div className="kpi-chip">
          <span className="kpi-label">Peak Confidence</span>
          <strong>{peakConfidence != null ? `${(peakConfidence * 100).toFixed(0)}%` : 'Pending'}</strong>
        </div>
        <div className="kpi-chip">
          <span className="kpi-label">Thread Checkpoint</span>
          <code>{currentRun?.thread_id ?? 'standby'}</code>
        </div>
      </div>

      {/* ── Sub-header Navigation Tabs ── */}
      <div className="multiagent-subnav">
        <button
          className={`multiagent-tab-btn ${activeTab === 'topology' ? 'active' : ''}`}
          onClick={() => setActiveTab('topology')}
        >
          <NetworkIcon size={14} /> Agent map
        </button>
        <button
          className={`multiagent-tab-btn ${activeTab === 'messages' ? 'active' : ''}`}
          onClick={() => setActiveTab('messages')}
        >
          <MessageSquareIcon size={14} /> Live messages ({messages.length})
        </button>
        <button
          className={`multiagent-tab-btn ${activeTab === 'memory' ? 'active' : ''}`}
          onClick={() => setActiveTab('memory')}
        >
          <DatabaseIcon size={14} /> Memory
        </button>
        <button
          className={`multiagent-tab-btn ${activeTab === 'tools' ? 'active' : ''}`}
          onClick={() => setActiveTab('tools')}
        >
          <TerminalIcon size={14} /> Tool calls ({toolCalls.length})
        </button>
      </div>

      {/* ── Tab 1: Topology Map ── */}
      {activeTab === 'topology' && (
        <div className="topology-view">
          {/* Supervisor Card */}
          <div className="topology-level supervisor-level">
            <div
              className={`agent-card supervisor-card ${selectedAgent === 'supervisor' ? 'selected' : ''}`}
              onClick={() => setSelectedAgent('supervisor')}
            >
              <div className="agent-card-header">
                <div className="agent-avatar supervisor">
                  <BrainIcon size={20} />
                </div>
                <div>
                  <div className="agent-name">Incident Commander</div>
                  <div className="agent-badge supervisor">Supervisor Agent</div>
                </div>
                <span className={`agent-status-indicator ${agentProfiles.supervisor.status}`}>
                  {agentProfiles.supervisor.status}
                </span>
              </div>
              <p className="agent-card-desc">
                High-level strategy, Long-Term Memory retrieval, task delegation, and loop control.
              </p>
              <div className="agent-stats-row">
                <span>Timeout: 30s</span>
                <span>Retries: 2</span>
                <span>Checkpointer: Active</span>
              </div>
            </div>
          </div>

          {/* Delegation Flow Diagram */}
          <div className="topology-connector-lines">
            <div className="down-line" />
            <div className="fan-horizontal" />
          </div>

          {/* Specialized Workers Grid */}
          <div className="topology-level workers-grid">
            {(['logs', 'metrics', 'traces', 'changes'] as const).map((key) => {
              const prof = agentProfiles[key];
              const IconComp = prof.icon;
              return (
                <div
                  key={key}
                  className={`agent-card worker-card ${selectedAgent === key ? 'selected' : ''}`}
                  onClick={() => setSelectedAgent(key)}
                >
                  <div className="agent-card-header">
                    <div className={`agent-avatar ${key}`}>
                      <IconComp size={16} />
                    </div>
                    <div>
                      <div className="agent-name">{prof.title}</div>
                      <div className="agent-badge worker">{prof.role}</div>
                    </div>
                    <span className={`agent-status-indicator ${prof.status}`} />
                  </div>
                  <p className="agent-card-desc">{prof.description}</p>
                  <div className="agent-tool-tag">
                    <TerminalIcon size={11} /> {prof.tools[0]}()
                  </div>
                </div>
              );
            })}
          </div>

          {/* Safety Officer & Gate Level */}
          <div className="topology-connector-lines">
            <div className="down-line" />
          </div>

          <div className="topology-level safety-level">
            <div
              className={`agent-card safety-card ${selectedAgent === 'safety' ? 'selected' : ''}`}
              onClick={() => setSelectedAgent('safety')}
            >
              <div className="agent-card-header">
                <div className="agent-avatar safety">
                  <ShieldIcon size={18} />
                </div>
                <div>
                  <div className="agent-name">Remediation Safety Officer</div>
                  <div className="agent-badge safety">Safety & Verification Agent</div>
                </div>
                <span className={`agent-status-indicator ${agentProfiles.safety.status}`} />
              </div>
              <p className="agent-card-desc">
                Enforces allowlisted catalog constraints, evaluates risk level, and prepares rollback plan.
              </p>
            </div>
          </div>

          {/* Detailed Inspector Panel for Selected Agent */}
          <div className="agent-inspector-card">
            <div className="inspector-header">
              <div className="inspector-title">
                <SelectedIcon size={20} />
                <div>
                  <h4>{currentAgent.title}</h4>
                  <span className="inspector-role">{currentAgent.role}</span>
                </div>
              </div>
              <div className="inspector-meta-pills">
                <span className="meta-pill">Max Retries: {currentAgent.retries}</span>
                <span className="meta-pill">Timeout: {currentAgent.timeout}</span>
                <span className="meta-pill">Error Isolation: True</span>
              </div>
            </div>
            <div className="inspector-body">
              <div className="inspector-field">
                <label>System Instructions (Prompt):</label>
                <div className="prompt-box">{currentAgent.prompt}</div>
              </div>
              <div className="inspector-field">
                <label>Allowed Tools & Capabilities:</label>
                <div className="tool-chips">
                  {currentAgent.tools.map((t) => (
                    <span className="tool-chip" key={t}>
                      <TerminalIcon size={12} /> {t}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Tab 2: Inter-Agent Message Bus ── */}
      {activeTab === 'messages' && (
        <div className="messages-view">
          <div className="section-subheading">
            <MessageSquareIcon size={16} />
            <span>Real-time Inter-Agent Communication Bus</span>
            <span className="message-count-badge">{filteredMessages.length} / {messages.length} messages</span>
          </div>
          <div className="bus-filter-bar">
            {([
              { key: 'all', label: 'All Messages' },
              { key: 'supervisor', label: 'Supervisor' },
              { key: 'workers', label: 'Worker Agents' },
              { key: 'human', label: 'Human Gate' },
            ] as const).map((opt) => (
              <button
                key={opt.key}
                type="button"
                className={`filter-pill ${messageRoleFilter === opt.key ? 'active' : ''}`}
                onClick={() => setMessageRoleFilter(opt.key)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="messages-stream">
            {filteredMessages.map((msg, i) => (
              <div className={`message-item ${msg.message_type}`} key={msg.id || i}>
                <div className="message-header">
                  <span className={`role-badge from ${msg.sender_role}`}>
                    {msg.sender_role.replace('_', ' ')}
                  </span>
                  <span className="arrow-sep">→</span>
                  <span className={`role-badge to ${msg.recipient_role}`}>
                    {msg.recipient_role.replace('_', ' ')}
                  </span>
                  <span className="message-type-tag">{msg.message_type.replace('_', ' ')}</span>
                  <span className="message-time">{msg.timestamp}</span>
                </div>
                <div className="message-body">
                  <p>{msg.summary}</p>
                  {msg.confidence != null && (
                    <span className="message-confidence">
                      Confidence: {(msg.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Tab 3: Short-Term & Long-Term Memory ── */}
      {activeTab === 'memory' && (
        <div className="memory-view">
          {/* Short-Term Working Memory */}
          <div className="memory-section">
            <h4 className="memory-title">
              <CpuIcon size={16} /> Short-Term Working Memory (Active Thread Session)
            </h4>
            <div className="short-term-grid">
              <div className="memory-stat-card">
                <span className="stat-label">Thread ID</span>
                <span className="stat-code">{currentRun?.thread_id || 'thread-active-sess'}</span>
              </div>
              <div className="memory-stat-card">
                <span className="stat-label">Investigation Round</span>
                <span className="stat-val">{currentRun?.evidence?.length ? 'Round 1 / 2 (Bounded)' : 'Round 1'}</span>
              </div>
              <div className="memory-stat-card">
                <span className="stat-label">Evidence Scratchpad</span>
                <span className="stat-val">{currentRun?.evidence?.length ?? 0} Observed Items</span>
              </div>
              <div className="memory-stat-card">
                <span className="stat-label">Checkpoint Persistence</span>
                <span className="stat-val success">MemorySaver / AsyncPostgres</span>
              </div>
            </div>
          </div>

          {/* Long-Term Memory (Historical Pattern Store) */}
          <div className="memory-section">
            <h4 className="memory-title">
              <DatabaseIcon size={16} /> Long-Term Memory (Retrieved Historical Incident Patterns)
            </h4>
            <p className="memory-intro">
              The Incident Commander queried historical post-mortems using symptom semantic similarity to guide worker task planning.
            </p>
            <div className="long-term-grid">
              {memoryItems.map((item) => (
                <div className="memory-pattern-card" key={item.pattern_id}>
                  <div className="pattern-header">
                    <span className="pattern-id">{item.pattern_id}</span>
                    <span className="pattern-key">{item.pattern_key}</span>
                    <span className="pattern-similarity">
                      {(item.similarity * 100).toFixed(0)}% match
                    </span>
                  </div>
                  <h5 className="pattern-title">{item.title}</h5>
                  <div className="pattern-remediation">
                    <strong>Proven Effective Fix:</strong> {item.effective_remediation}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab 4: Structured Tool Calling ── */}
      {activeTab === 'tools' && (
        <div className="tools-view">
          <div className="section-subheading">
            <TerminalIcon size={16} />
            <span>Structured Tool Calling & Audited Executions</span>
          </div>
          <div className="tools-grid">
            {toolCalls.map((t, i) => (
              <div className="tool-card" key={i}>
                <div className="tool-card-header">
                  <div className="tool-name-group">
                    <span className="tool-name">{t.tool_name}</span>
                    <span className="tool-caller">Called by {t.invoked_by}</span>
                  </div>
                  <span className="tool-latency">{t.latency_ms.toFixed(1)}ms</span>
                </div>
                <div className="tool-params-box">
                  <span className="params-label">Parameters:</span>
                  <code>{JSON.stringify(t.parameters)}</code>
                </div>
                <p className="tool-summary">{t.output_summary}</p>
                <div className="tool-footer">
                  <span className="tool-status success">
                    <CheckCircleIcon size={12} /> Status: Validated Output Schema
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Human-in-the-Loop Approval Action (if paused) ── */}
      {currentRun?.is_awaiting_approval && currentRun.approval && onApproval && (
        <div className="orchestrator-hitl-banner">
          <div className="hitl-content">
            <AlertTriangleIcon size={20} />
            <div>
              <strong>Human-in-the-Loop Interrupt Active</strong>
              <p>
                The Supervisor paused execution before remediation. Action: <code>{currentRun.approval.action_type}</code>
              </p>
            </div>
          </div>
          <div className="hitl-actions">
            <button className="btn btn-approve" onClick={() => onApproval('approved')}>
              ✓ Approve & Resume
            </button>
            <button className="btn btn-reject" onClick={() => onApproval('rejected')}>
              ✕ Reject
            </button>
            <button className="btn btn-secondary" onClick={() => onApproval('request_more_evidence')}>
              <RefreshIcon size={12} /> Loop: Request More Evidence
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   STANDALONE MULTI-AGENT ORCHESTRATION HUB PAGE
   ═══════════════════════════════════════════════════════════ */

export function OrchestrationPage({
  incidents,
  onTriggerSimulation,
}: {
  incidents: Incident[];
  onTriggerSimulation: (scenarioKey: string) => void;
}) {
  const [selectedScenario, setSelectedScenario] = useState('db_conn_exhaustion');

  return (
    <>
      <div className="page-header">
        <div>
          <div className="eyebrow">SUPERVISOR / WORKER RUNTIME</div>
          <h1 className="page-title">Agent graph</h1>
          <p className="page-subtitle">
            Inspect how six specialists coordinate through shared state, durable checkpoints, and human gates.
          </p>
        </div>
        <div className="header-actions">
          <select
            value={selectedScenario}
            onChange={(e) => setSelectedScenario(e.target.value)}
            className="scenario-select"
          >
            <option value="db_conn_exhaustion">⚡ DB Pool Saturation (Critical)</option>
            <option value="db_latency">⏱️ ShopAPI High Latency (High)</option>
            <option value="bad_release">⚠️ Release v1.4.2 Regression (Medium)</option>
          </select>
          <button
            className="simulate-btn"
            onClick={() => onTriggerSimulation(selectedScenario)}
          >
            <ZapIcon size={14} /> Launch investigation
          </button>
        </div>
      </div>

      {/* Architecture Highlights Row */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="stat-card purple" style={{ '--stagger': 0 } as React.CSSProperties}>
          <div className="stat-label">Architecture</div>
          <div className="stat-value" style={{ fontSize: '1.25rem', marginTop: '0.2rem' }}>Supervisor-Worker</div>
          <div className="stat-detail">1 Commander · 5 Specialized Workers</div>
          <span className="stat-icon"><NetworkIcon size={28} /></span>
        </div>
        <div className="stat-card blue" style={{ '--stagger': 1 } as React.CSSProperties}>
          <div className="stat-label">State & Memory</div>
          <div className="stat-value" style={{ fontSize: '1.25rem', marginTop: '0.2rem' }}>Dual-Layer</div>
          <div className="stat-detail">Thread Scratchpad + Vector Post-Mortems</div>
          <span className="stat-icon"><DatabaseIcon size={28} /></span>
        </div>
        <div className="stat-card amber" style={{ '--stagger': 2 } as React.CSSProperties}>
          <div className="stat-label">Routing & Loops</div>
          <div className="stat-value" style={{ fontSize: '1.25rem', marginTop: '0.2rem' }}>Bounded Loops</div>
          <div className="stat-detail">Confidence check & refinement cycles</div>
          <span className="stat-icon"><RefreshIcon size={28} /></span>
        </div>
        <div className="stat-card green" style={{ '--stagger': 3 } as React.CSSProperties}>
          <div className="stat-label">Safety Gate</div>
          <div className="stat-value" style={{ fontSize: '1.25rem', marginTop: '0.2rem' }}>HITL Interrupt</div>
          <div className="stat-detail">Zero unintended blast radius</div>
          <span className="stat-icon"><ShieldIcon size={28} /></span>
        </div>
      </div>

      {/* Interactive Multi-Agent View */}
      <div className="section-card" style={{ padding: '1.5rem' }}>
        <div className="section-header" style={{ borderBottom: 'none', padding: '0 0 1rem 0' }}>
          <span className="section-title">
            <span className="icon"><NetworkIcon size={18} /></span>
            Active Multi-Agent Orchestration Topology
          </span>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            LangGraph StateGraph v1.0.0
          </span>
        </div>
        <MultiAgentView
          currentRun={null}
          incident={incidents[0] || null}
          investigating={false}
        />
      </div>
    </>
  );
}

