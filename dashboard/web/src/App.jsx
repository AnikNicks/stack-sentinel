import { useEffect, useState } from "react";
import { api, AGENTS } from "./api";
import "./App.css";

const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "companies", label: "Companies" },
  { id: "incidents", label: "Incidents" },
  { id: "registry", label: "Registry" },
  { id: "health", label: "System Health" },
  { id: "ask", label: "Ask" },
];

function useAsync(fn, deps) {
  const [state, setState] = useState({ loading: true, error: null, data: null });
  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, error: null, data: null });
    fn()
      .then((data) => !cancelled && setState({ loading: false, error: null, data }))
      .catch((error) => !cancelled && setState({ loading: false, error, data: null }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

function useActiveSection(ids) {
  const [active, setActive] = useState(ids[0]);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) setActive(entry.target.id);
        });
      },
      { rootMargin: "-35% 0px -55% 0px", threshold: 0 }
    );
    const els = ids.map((id) => document.getElementById(id)).filter(Boolean);
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return active;
}

function StatusBadge({ classification }) {
  const cls = classification || "unknown";
  return <span className={`badge badge-${cls}`}>{cls}</span>;
}

function ErrorBanner({ error }) {
  if (!error) return null;
  return (
    <div className="error-banner">
      Could not reach the console API at <code>http://127.0.0.1:8000</code> — is{" "}
      <code>uvicorn dashboard.api.main:app --reload</code> running? ({error.message})
    </div>
  );
}

function SectionHeader({ eyebrow, title, description }) {
  return (
    <div className="section-header">
      {eyebrow && <div className="eyebrow">{eyebrow}</div>}
      <h2>{title}</h2>
      {description && <p className="section-description">{description}</p>}
    </div>
  );
}

function Modal({ title, subtitle, onClose, children }) {
  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3>{title}</h3>
            {subtitle && <p className="modal-subtitle">{subtitle}</p>}
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

/** A small line chart of error_rate_pct across cycles, with points colored by that
 * cycle's status and clickable to drill into the full cycle record — the same
 * "click a point on the graph to see the event" pattern a real monitoring tool uses. */
function HealthChart({ entries, compact = false, onPointClick }) {
  if (!entries || entries.length < 2) {
    return <p className="muted chart-empty">Not enough cycles yet for a trend.</p>;
  }
  const W = 600;
  const H = compact ? 56 : 130;
  const padX = 10;
  const padY = compact ? 8 : 18;
  const values = entries.map((e) => e.metric_snapshot?.operational_health?.error_rate_pct ?? 0);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = (W - padX * 2) / (entries.length - 1);

  const yFor = (v) => H - padY - ((v - min) / range) * (H - padY * 2);
  const coords = values.map((v, i) => [padX + i * stepX, yFor(v)]);
  const linePath = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1][0].toFixed(1)},${H - padY} L${coords[0][0].toFixed(1)},${H - padY} Z`;

  function statusFor(entry) {
    const incidentCount = entry.metric_snapshot?.behavior_incidents?.length || 0;
    const destructive = Object.values(entry.metric_snapshot?.layers || {}).some(
      (l) => l.change_event && l.change_event.reversible === false
    );
    if (destructive) return "bad";
    if (incidentCount > 0) return "warn";
    return "ok";
  }

  return (
    <div className={compact ? "health-chart health-chart-compact" : "health-chart"}>
      {!compact && (
        <div className="health-chart-legend">
          <span>Error rate</span>
          <span className="muted">{values[values.length - 1]}% latest</span>
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className="health-chart-svg" style={{ width: "100%", height: "auto", display: "block" }}>
        <path d={areaPath} className="health-chart-area" />
        <path d={linePath} className="health-chart-line" />
        {coords.map(([x, y], i) => {
          const status = statusFor(entries[i]);
          return (
            <circle
              key={entries[i].cycle}
              cx={x}
              cy={y}
              r={compact ? 3 : 5}
              className={`health-chart-point health-chart-point-${status}${onPointClick ? " clickable" : ""}`}
              onClick={onPointClick ? () => onPointClick(entries[i]) : undefined}
            >
              {!compact && <title>{`${entries[i].cycle}: ${values[i]}% error rate — click for detail`}</title>}
            </circle>
          );
        })}
      </svg>
      {!compact && (
        <div className="health-chart-axis">
          <span>{entries[0].cycle}</span>
          <span>{entries[entries.length - 1].cycle}</span>
        </div>
      )}
    </div>
  );
}

/** Horizontal bar chart for count-by-label rollups (incidents by kind/tier). Each bar is a
 * real button, clickable to drill into the matching incidents — same idea as clicking a
 * category slice in a real observability dashboard. */
function BarChart({ data, colorClassFor, onBarClick }) {
  const entries = Object.entries(data || {});
  if (entries.length === 0) return <p className="muted">None recorded yet.</p>;
  const max = Math.max(...entries.map(([, v]) => v));
  return (
    <div className="bar-chart">
      {entries.map(([label, value]) => (
        <button key={label} className="bar-row" onClick={() => onBarClick(label)}>
          <span className="bar-label mono">{label}</span>
          <span className="bar-track">
            <span
              className={`bar-fill ${colorClassFor ? colorClassFor(label) : "bar-fill-accent"}`}
              style={{ width: `${(value / max) * 100}%` }}
            />
          </span>
          <span className="bar-value">{value}</span>
        </button>
      ))}
    </div>
  );
}

function CycleDetailModal({ company, entry, onClose }) {
  const health = entry.metric_snapshot?.operational_health || {};
  const layers = entry.metric_snapshot?.layers || {};
  const incidents = entry.metric_snapshot?.behavior_incidents || [];
  const changed = Object.entries(layers).filter(([, v]) => v.change_event);

  return (
    <Modal title={`${company.name} — ${entry.cycle}`} subtitle={company.sector} onClose={onClose}>
      <div className="modal-row">
        <StatusBadge classification={entry.classification} />
        <span className="muted">classified by {entry.classifying_agent} {entry.agent_version} ({entry.model})</span>
      </div>

      <h4>Operational health</h4>
      <div className="stat-row">
        {Object.entries(health).map(([k, v]) => (
          <div key={k} className="stat-chip">
            <span className="stat-value">{v}</span>
            <span className="stat-label mono">{k}</span>
          </div>
        ))}
      </div>

      <h4>Layer changes this cycle</h4>
      {changed.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul className="detail-list">
          {changed.map(([layer, v]) => (
            <li key={layer}>
              <span className={`layer-chip${v.change_event.reversible === false ? " layer-chip-bad" : ""}`}>{layer}</span>{" "}
              {v.change_event.description}
              {v.change_event.reversible === false && <strong className="bad-text"> — NON-REVERSIBLE</strong>}
            </li>
          ))}
        </ul>
      )}

      <h4>Behavior incidents this cycle</h4>
      {incidents.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul className="detail-list">
          {incidents.map((inc, i) => (
            <li key={i}>
              {inc.description}
              <div className="muted">boundary: {inc.boundary_violated}</div>
            </li>
          ))}
        </ul>
      )}

      <h4>Rationale</h4>
      <p className="modal-rationale">{entry.rationale}</p>
    </Modal>
  );
}

// ---------------------------------------------------------------------------

function OverviewSection() {
  const { loading, error, data: companies } = useAsync(api.listCompanies, []);
  const [recent, setRecent] = useState({});

  useEffect(() => {
    if (!companies) return;
    companies.forEach((c) => {
      api.getTrend(c.company_id, 6).then((h) => {
        setRecent((prev) => ({ ...prev, [c.company_id]: h }));
      });
    });
  }, [companies]);

  return (
    <section id="overview" className="page-section">
      <SectionHeader
        eyebrow="Portfolio"
        title="Overview"
        description="Latest recorded classification for every monitored company, with a recent error-rate trend at a glance."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading portfolio…</p>}
      {companies && (
        <div className="card-grid">
          {companies.map((c) => {
            const history = recent[c.company_id];
            const entry = history?.[history.length - 1];
            return (
              <a href={`#company-${c.company_id}`} key={c.company_id} className="company-card">
                <h3>{c.name}</h3>
                <p className="sector">{c.sector}</p>
                <p className="track">{c.monitoring_track}-tracked</p>
                {entry ? (
                  <>
                    <StatusBadge classification={entry.classification} />
                    <p className="cycle-label">as of {entry.cycle}</p>
                  </>
                ) : (
                  <p className="cycle-label">no data yet</p>
                )}
                {history && history.length >= 2 && <HealthChart entries={history} compact />}
              </a>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

/** This company's charter (behavior boundaries) or SLO (error-budget thresholds) — whichever
 * applies to its monitoring_track. This is what goal-drift-tracker / slo-risk-tracker check
 * every cycle against; showing it inline is what makes a company's status legible without
 * cross-referencing a separate doc. */
function CompanyCharterPanel({ company }) {
  const isCharter = company.monitoring_track === "CHARTER";
  const { data } = useAsync(
    () => (isCharter ? api.getCharter(company.company_id) : api.getSlo(company.company_id)),
    [company.company_id]
  );
  if (!data) return null;
  return (
    <div className="charter-panel">
      <p className="charter-summary">{data.summary}</p>
      {isCharter ? (
        <ul className="boundary-list">
          {data.agent_behavior_boundaries.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      ) : (
        <ul className="boundary-list">
          {Object.entries(data.slos).map(([k, v]) => (
            <li key={k}>
              <span className="mono">{k}</span>:{" "}
              {typeof v === "object" ? Object.entries(v).map(([k2, v2]) => `${k2}=${v2}`).join(", ") : String(v)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** This company's OWN internal agents (e.g. Cascade's auto-remediation-agent) — the actual
 * subject of the risk-tiered rollback mechanism: low/medium-risk events auto-roll an agent
 * back with no human in the loop; high/critical-risk events never roll back automatically.
 * Distinct from the portfolio-wide Registry section below, which is Stack Sentinel's OWN six
 * classifiers, not any company's agents. */
function CompanyAgentsPanel({ companyId, refreshKey }) {
  const { data: agents } = useAsync(() => api.getCompanyAgents(companyId), [companyId, refreshKey]);
  if (!agents || agents.length === 0) return null;
  return (
    <div className="company-agents-grid">
      {agents.map((a) => {
        const auto = a.active?.activated_by;
        const wasRolledBack = auto && auto !== "initial-deployment";
        return (
          <div key={a.agent} className={wasRolledBack ? "agent-card agent-card-rolled-back" : "agent-card"}>
            <div className="agent-card-name mono">{a.agent}</div>
            <div className="agent-card-version">
              active <strong>{a.active?.version ?? "—"}</strong>
              {a.versions.length > 1 && <span className="muted"> · {a.versions.length} versions on record</span>}
            </div>
            {wasRolledBack && <div className="agent-card-flag">rolled back — by {auto}</div>}
          </div>
        );
      })}
    </div>
  );
}

/** This company's own policy document, read alongside (never instead of) the shared
 * portfolio-wide policy in the Incidents section's governance rules. */
function CompanyPolicyPanel({ companyId }) {
  const { data } = useAsync(() => api.getCompanyPolicy(companyId), [companyId]);
  if (!data) return null;
  return (
    <details className="policy-details">
      <summary>Company policy</summary>
      <pre className="policy-text">{data.markdown}</pre>
    </details>
  );
}

function CompanyBlock({ company, incidents, onSelectCycle, agentsRefreshKey }) {
  const { data: trend } = useAsync(() => api.getTrend(company.company_id), [company.company_id]);
  const companyIncidents = (incidents || []).filter((i) => i.company_ids?.includes(company.company_id));

  return (
    <div id={`company-${company.company_id}`} className="company-block">
      <div className="company-block-header">
        <h3>{company.name}</h3>
        <span className="track-pill">{company.monitoring_track}</span>
      </div>
      <p className="muted">{company.sector}</p>

      <h4 className="company-subhead">{company.monitoring_track === "CHARTER" ? "Charter boundaries" : "SLO thresholds"}</h4>
      <CompanyCharterPanel company={company} />

      <h4 className="company-subhead">Internal agents</h4>
      <CompanyAgentsPanel companyId={company.company_id} refreshKey={agentsRefreshKey} />

      <CompanyPolicyPanel companyId={company.company_id} />

      <h4 className="company-subhead">Operational health &amp; incidents</h4>
      {trend && trend.length >= 2 && (
        <HealthChart entries={trend} onPointClick={(entry) => onSelectCycle(company, entry)} />
      )}

      {!trend || trend.length === 0 ? (
        <p className="muted">No cycles recorded yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="trend-table">
            <thead>
              <tr>
                <th>Cycle</th>
                <th>Classification</th>
                <th>Incidents</th>
                <th>Layer changes</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {[...trend].reverse().map((e) => {
                const layers = e.metric_snapshot?.layers || {};
                const changed = Object.entries(layers).filter(([, v]) => v.change_event);
                const incidentsCount = e.metric_snapshot?.behavior_incidents?.length || 0;
                return (
                  <tr
                    key={e.cycle}
                    className={incidentsCount ? "row-flagged row-clickable" : "row-clickable"}
                    onClick={() => onSelectCycle(company, e)}
                  >
                    <td className="mono">{e.cycle}</td>
                    <td>
                      <StatusBadge classification={e.classification} />
                    </td>
                    <td>{incidentsCount}</td>
                    <td>{changed.length === 0 ? "—" : changed.map(([layer]) => layer).join(", ")}</td>
                    <td className="rationale-cell">{e.rationale}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {companyIncidents.length > 0 && (
        <div className="mini-incidents">
          <span className="mini-incidents-label">Incidents:</span>
          {companyIncidents.map((i) => (
            <span key={i.incident_id} className="mini-incident-chip">
              {i.incident_id} · {i.kind} · {i.status}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function CompaniesSection({ agentsRefreshKey }) {
  const { loading, error, data: companies } = useAsync(api.listCompanies, []);
  const { data: incidents } = useAsync(() => api.listIncidents(), []);
  const [selected, setSelected] = useState(null); // { company, entry }

  return (
    <section id="companies" className="page-section">
      <SectionHeader
        eyebrow="Detail"
        title="Companies"
        description="Everything about one monitored company in one place: its charter/SLO, its own internal agents and their rollback status, its own policy, and its full cycle-by-cycle history. Click any point on a health chart, or any table row's cycle, for the full record."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading…</p>}
      {companies && (
        <div className="company-block-list">
          {companies.map((c) => (
            <CompanyBlock
              key={c.company_id}
              company={c}
              incidents={incidents}
              onSelectCycle={(company, entry) => setSelected({ company, entry })}
              agentsRefreshKey={agentsRefreshKey}
            />
          ))}
        </div>
      )}
      {selected && (
        <CycleDetailModal company={selected.company} entry={selected.entry} onClose={() => setSelected(null)} />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

function IncidentsSection({ onDecisionRecorded }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const { loading, error, data: incidentList } = useAsync(() => api.listIncidents(), [refreshKey]);
  const [decidedBy, setDecidedBy] = useState("");
  const [note, setNote] = useState("");
  const [busyId, setBusyId] = useState(null);

  async function decide(incidentId, decision) {
    if (!decidedBy.trim()) {
      alert("Enter who is making this decision first.");
      return;
    }
    setBusyId(incidentId);
    try {
      await api.recordDecision(incidentId, decision, decidedBy, note);
      setRefreshKey((k) => k + 1);
      onDecisionRecorded?.();
    } catch (e) {
      alert("Failed: " + e.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section id="incidents" className="page-section">
      <SectionHeader
        eyebrow="Governance"
        title="Incidents"
        description="Every incident on record. The only write action in this app lives here — Approve or Reject on any incident still pending_human_approval."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading incidents…</p>}
      {incidentList && (
        <>
          <div className="decision-form">
            <input
              placeholder="decided_by (your name/email)"
              value={decidedBy}
              onChange={(e) => setDecidedBy(e.target.value)}
            />
            <input placeholder="note (why)" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="table-scroll">
            <table className="incidents-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Kind</th>
                  <th>Companies</th>
                  <th>Risk</th>
                  <th>Routing</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {incidentList.map((i) => (
                  <tr key={i.incident_id}>
                    <td className="mono">{i.incident_id}</td>
                    <td>{i.kind}</td>
                    <td>{i.company_ids?.join(", ")}</td>
                    <td>
                      <span className={`risk risk-${i.risk_tier}`}>{i.risk_tier}</span>
                    </td>
                    <td>{i.routing}</td>
                    <td>{i.status}</td>
                    <td className="action-cell">
                      {i.status === "pending_human_approval" ? (
                        <>
                          <button disabled={busyId === i.incident_id} onClick={() => decide(i.incident_id, "approved")}>
                            Approve
                          </button>
                          <button
                            className="btn-secondary"
                            disabled={busyId === i.incident_id}
                            onClick={() => decide(i.incident_id, "rejected")}
                          >
                            Reject
                          </button>
                        </>
                      ) : (
                        <em className="muted">—</em>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

function RegistryAgentBlock({ agent }) {
  const { data } = useAsync(() => api.getRegistry(agent), [agent]);
  return (
    <div className="registry-block">
      <div className="registry-block-header">
        <h3 className="mono">{agent}</h3>
        {data?.active && (
          <span className="active-pill">
            active: {data.active.version} <span className="muted">by {data.active.activated_by}</span>
          </span>
        )}
      </div>
      {data && (
        <ul className="version-list">
          {data.versions.map((v) => (
            <li key={v.version} className={v.version === data.active?.version ? "version-active" : ""}>
              <strong className="mono">{v.version}</strong>{" "}
              <span className="muted">({v.created})</span> — {v.changelog}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RegistrySection() {
  return (
    <section id="registry" className="page-section">
      <SectionHeader
        eyebrow="Versioning"
        title="Registry — Stack Sentinel's own agents"
        description="Version history for Stack Sentinel's own six classifiers (the monitoring system itself). Each monitored company's OWN internal agents — with their own risk-tiered auto-rollback — are shown inline in that company's block in the Companies section above, not here."
      />
      <div className="registry-list">
        {AGENTS.map((a) => (
          <RegistryAgentBlock key={a} agent={a} />
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------

const RISK_COLOR_CLASS = { critical: "bar-fill-bad", high: "bar-fill-warn", medium: "bar-fill-accent", low: "bar-fill-accent" };

function IncidentDrilldownModal({ title, incidents, onClose }) {
  return (
    <Modal title={title} subtitle={`${incidents.length} incident(s)`} onClose={onClose}>
      {incidents.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul className="detail-list">
          {incidents.map((i) => (
            <li key={i.incident_id}>
              <strong className="mono">{i.incident_id}</strong> — {i.company_ids?.join(", ")}
              <div className="muted">
                risk={i.risk_tier} · routing={i.routing} · status={i.status}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

function SystemHealthSection() {
  const { loading, error, data } = useAsync(api.getMetrics, []);
  const { data: incidents } = useAsync(() => api.listIncidents(), []);
  const [drilldown, setDrilldown] = useState(null); // { title, incidents }

  function showKind(kind) {
    setDrilldown({ title: `Incidents — ${kind}`, incidents: (incidents || []).filter((i) => i.kind === kind) });
  }
  function showTier(tier) {
    setDrilldown({ title: `Incidents — ${tier} risk`, incidents: (incidents || []).filter((i) => i.risk_tier === tier) });
  }

  return (
    <section id="health" className="page-section">
      <SectionHeader
        eyebrow="Observability"
        title="System Health"
        description="Read-only rollups over the trend store and incident log. Click any bar to drill into the matching incidents."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading…</p>}
      {data && (
        <div className="health-grid">
          <div className="health-card">
            <h4>Incidents by kind</h4>
            <BarChart data={data.incident_rates.by_kind} onBarClick={showKind} />
          </div>
          <div className="health-card">
            <h4>Incidents by risk tier</h4>
            <BarChart data={data.incident_rates.by_risk_tier} colorClassFor={(l) => RISK_COLOR_CLASS[l] || "bar-fill-accent"} onBarClick={showTier} />
          </div>
          <div className="health-card health-card-wide">
            <h4>Human-approval turnaround</h4>
            {data.approval_turnaround.length === 0 ? (
              <p className="muted">No decided approvals yet.</p>
            ) : (
              <ul>
                {data.approval_turnaround.map((a) => (
                  <li key={a.incident_id}>
                    {a.incident_id}: {a.status} in {a.business_days_elapsed} business day(s){" "}
                    {a.within_sla ? "(within SLA)" : "(SLA breached)"}
                  </li>
                ))}
              </ul>
            )}
            <h4>Companies tracked</h4>
            <p className="muted">{data.companies_tracked.join(", ") || "none yet"}</p>
          </div>
        </div>
      )}
      {drilldown && (
        <IncidentDrilldownModal title={drilldown.title} incidents={drilldown.incidents} onClose={() => setDrilldown(null)} />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

function AskSection() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    setAnswer(null);
    try {
      const res = await api.ask(question);
      setAnswer(res.answer);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section id="ask" className="page-section">
      <SectionHeader
        eyebrow="Grounded Q&A"
        title="Ask"
        description={
          <>
            Requires <code>OPENAI_API_KEY</code> set on the console API process — the one place
            this app calls a live third-party LLM, separate from the deterministic core and the
            six Claude subagents.
          </>
        }
      />
      <textarea
        rows={3}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="e.g. Why was change-impact-synthesizer rolled back?"
      />
      <div>
        <button disabled={busy || !question.trim()} onClick={submit}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </div>
      {err && <div className="error-banner">{err}</div>}
      {answer && <div className="ask-answer">{answer}</div>}
    </section>
  );
}

// ---------------------------------------------------------------------------

export default function App() {
  const active = useActiveSection(SECTIONS.map((s) => s.id));
  const [agentsRefreshKey, setAgentsRefreshKey] = useState(0);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Stack Sentinel</h1>
        <p className="subtitle">Multi-agent AI software monitoring — live operator console</p>
      </header>

      <nav className="section-nav">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#${s.id}`} className={active === s.id ? "nav-link nav-link-active" : "nav-link"}>
            {s.label}
          </a>
        ))}
      </nav>

      <main className="page-body">
        <OverviewSection />
        <CompaniesSection agentsRefreshKey={agentsRefreshKey} />
        <IncidentsSection onDecisionRecorded={() => setAgentsRefreshKey((k) => k + 1)} />
        <RegistrySection />
        <SystemHealthSection />
        <AskSection />
      </main>

      <footer className="app-footer">Stack Sentinel — local-only operator console.</footer>
    </div>
  );
}
