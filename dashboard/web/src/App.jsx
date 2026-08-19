import { useEffect, useState } from "react";
import { api, AGENTS, STATIC_MODE } from "./api";
import "./App.css";

const SECTIONS = [
  { id: "system", label: "System" },
  { id: "ask", label: "Ask" },
  { id: "companies", label: "Companies" },
  { id: "incidents", label: "Incidents" },
];

const RISK_COLOR_CLASS = { critical: "bar-fill-bad", high: "bar-fill-warn", medium: "bar-fill-accent", low: "bar-fill-accent" };
const OPEN_STATUSES = new Set(["pending_review", "pending_human_approval"]);

// This company's own product demo app (companies/*), published as a separate static GitHub
// Pages site — read-only, never feeds data back into this monitoring pipeline (see CLAUDE.md).
const COMPANY_DEMO_URLS = {
  meridian: "https://aniknicks.github.io/meridian-labs/",
  wayfinder: "https://aniknicks.github.io/wayfinder-ai/",
  cascade: "https://aniknicks.github.io/cascade-analytics/",
};

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

/** A subheading with a one-line purpose caption — so a panel's "what is this and why is it
 * here" reads the same way SectionHeader's description does at the section level, just
 * scaled down to a single panel within a section. */
function SubHeading({ title, purpose, first = false }) {
  return (
    <div className={first ? "subhead-block subhead-block-first" : "subhead-block"}>
      <h4 className="company-subhead">{title}</h4>
      {purpose && <p className="subhead-purpose">{purpose}</p>}
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
function HealthChart({ entries, compact = false, onPointClick, metricField = "error_rate_pct", label = "Error rate", unit = "%" }) {
  if (!entries || entries.length < 2) {
    return <p className="muted chart-empty">Not enough cycles yet for a trend.</p>;
  }
  const W = 600;
  const H = compact ? 56 : 130;
  const padX = 10;
  const padY = compact ? 8 : 18;
  const values = entries.map((e) => e.metric_snapshot?.operational_health?.[metricField] ?? 0);
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
          <span>{label}</span>
          <span className="muted">{values[values.length - 1]}{unit} latest</span>
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
              onClick={onPointClick ? (e) => { e.stopPropagation(); onPointClick(entries[i]); } : undefined}
            >
              {!compact && <title>{`${entries[i].cycle}: ${values[i]}${unit} ${label.toLowerCase()} — click for detail`}</title>}
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

function IncidentDrilldownModal({ title, incidents, onClose, onSelect }) {
  return (
    <Modal title={title} subtitle={`${incidents.length} incident(s)`} onClose={onClose}>
      {incidents.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul className="detail-list">
          {incidents.map((i) => (
            <li key={i.incident_id} className={onSelect ? "detail-list-clickable" : undefined} onClick={onSelect ? () => onSelect(i) : undefined}>
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

/** Full incident record — kind, routing, remediation reasoning, and (new) the real per-company
 * policy-compliance-checker read that ran against this incident's routing decision. Kept out
 * of the incidents table itself (which stays a scannable list) and only shown on click, per
 * the "concise on the page, detailed in the popup" rule. */
function IncidentDetailModal({ incident, onClose }) {
  const policyChecks = incident.policy_check ? Object.entries(incident.policy_check) : [];
  return (
    <Modal title={incident.incident_id} subtitle={`${incident.kind} · ${incident.company_ids?.join(", ")} · ${incident.detected_at}`} onClose={onClose}>
      <div className="modal-row">
        <span className={`risk risk-${incident.risk_tier}`}>{incident.risk_tier}</span>
        <span className="muted">routing={incident.routing} · status={incident.status}</span>
      </div>

      <h4>What happened</h4>
      <p className="modal-rationale">{incident.remediation_detail}</p>

      {policyChecks.length > 0 && (
        <>
          <h4>Policy check</h4>
          <ul className="detail-list">
            {policyChecks.map(([cid, check]) => (
              <li key={cid}>
                <strong className="mono">{cid}</strong>:{" "}
                {check.checked ? (
                  <span className={check.compliant ? "ok-text" : "bad-text"}>{check.compliant ? "compliant" : "NON-COMPLIANT"}</span>
                ) : (
                  <span className="muted">not checked</span>
                )}
                {check.matched_clause_titles?.length > 0 && (
                  <div className="muted">clauses: {check.matched_clause_titles.join(", ")}</div>
                )}
                <div className="muted">{check.rationale}</div>
              </li>
            ))}
          </ul>
        </>
      )}

      {incident.counterfactual && (
        <>
          <h4>Counterfactual (what the last known-good version would have said)</h4>
          <pre className="policy-text">{JSON.stringify(incident.counterfactual, null, 2)}</pre>
        </>
      )}

      {incident.human_note && (
        <>
          <h4>Human decision</h4>
          <p className="modal-rationale">
            {incident.human_note} <span className="muted">— {incident.resolved_by}</span>
          </p>
        </>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// System — Stack Sentinel's own status, first: portfolio KPIs, per-company snapshot,
// incident-rollup visualizations, and Stack Sentinel's own seven classifier versions. This is
// "system info," distinct from any one monitored company's own detail (below, in Companies).
// ---------------------------------------------------------------------------

function KpiStrip({ companies, incidents }) {
  const open = incidents ? incidents.filter((i) => OPEN_STATUSES.has(i.status)).length : null;
  const autoResolved = incidents ? incidents.filter((i) => i.status === "auto_resolved").length : null;
  const kpis = [
    { label: "Companies monitored", value: companies?.length ?? "—" },
    { label: "Open incidents", value: open ?? "—" },
    { label: "Auto-resolved", value: autoResolved ?? "—" },
    { label: "Total incidents", value: incidents?.length ?? "—" },
  ];
  return (
    <div className="kpi-strip">
      {kpis.map((k) => (
        <div key={k.label} className="kpi-chip">
          <span className="kpi-value">{k.value}</span>
          <span className="kpi-label">{k.label}</span>
        </div>
      ))}
    </div>
  );
}

function RegistryAgentModal({ agent, data, onClose }) {
  return (
    <Modal
      title={agent}
      subtitle={data?.active ? `active: ${data.active.version} · by ${data.active.activated_by}` : "not yet activated"}
      onClose={onClose}
    >
      {data && (
        <ul className="version-list">
          {data.versions.map((v) => (
            <li key={v.version} className={v.version === data.active?.version ? "version-active" : ""}>
              <strong className="mono">{v.version}</strong> <span className="muted">({v.created})</span> — {v.changelog}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

function RegistryPill({ agent, onOpen }) {
  const { data } = useAsync(() => api.getRegistry(agent), [agent]);
  return (
    <button className="registry-pill" onClick={() => onOpen(agent, data)}>
      <span className="mono registry-pill-name">{agent}</span>
      <span className="registry-pill-version">{data?.active?.version ?? "—"}</span>
    </button>
  );
}

function RegistryPillRow() {
  const [open, setOpen] = useState(null); // { agent, data }
  return (
    <>
      <div className="registry-pill-row">
        {AGENTS.map((a) => (
          <RegistryPill key={a} agent={a} onOpen={(agent, data) => setOpen({ agent, data })} />
        ))}
      </div>
      {open && <RegistryAgentModal agent={open.agent} data={open.data} onClose={() => setOpen(null)} />}
    </>
  );
}

function SystemSection({ onSelectCompany, selectedCompanyId }) {
  const { loading, error, data: companies } = useAsync(api.listCompanies, []);
  const { data: incidents } = useAsync(() => api.listIncidents(), []);
  const { data: metrics } = useAsync(api.getMetrics, []);
  const [recent, setRecent] = useState({});
  const [drilldown, setDrilldown] = useState(null); // { title, incidents }
  const [drilldownDetail, setDrilldownDetail] = useState(null);

  useEffect(() => {
    if (!companies) return;
    companies.forEach((c) => {
      api.getTrend(c.company_id, 6).then((h) => {
        setRecent((prev) => ({ ...prev, [c.company_id]: h }));
      });
    });
  }, [companies]);

  function showKind(kind) {
    setDrilldown({ title: `Incidents — ${kind}`, incidents: (incidents || []).filter((i) => i.kind === kind) });
  }
  function showTier(tier) {
    setDrilldown({ title: `Incidents — ${tier} risk`, incidents: (incidents || []).filter((i) => i.risk_tier === tier) });
  }

  return (
    <section id="system" className="page-section">
      <SectionHeader
        eyebrow="System"
        title="Stack Sentinel"
        description="Portfolio-wide status and Stack Sentinel's own seven classifier versions — the monitoring system's own health, checked every cycle the same way it checks the companies it watches."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading…</p>}

      <SubHeading
        first
        title="Portfolio snapshot"
        purpose="At-a-glance counts across every monitored company this run — how many are being watched, and how many incidents are open, auto-resolved, or on record in total."
      />
      {companies && <KpiStrip companies={companies} incidents={incidents} />}

      <SubHeading
        title="Companies"
        purpose="Each company's latest recorded classification and a 6-cycle error-rate trend. Click a card to jump to its full detail below."
      />
      {companies && (
        <div className="card-grid">
          {companies.map((c) => {
            const history = recent[c.company_id];
            const entry = history?.[history.length - 1];
            return (
              <div
                key={c.company_id}
                className={
                  c.company_id === selectedCompanyId
                    ? "company-card company-card-clickable company-card-selected"
                    : "company-card company-card-clickable"
                }
                role="button"
                tabIndex={0}
                onClick={() => onSelectCompany(c.company_id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelectCompany(c.company_id)}
              >
                <h3>{c.name}</h3>
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
              </div>
            );
          })}
        </div>
      )}

      <SubHeading
        title="Incident rollups"
        purpose="Every incident on record, grouped by kind and by risk tier. Click a bar to drill into the matching incidents."
      />
      {metrics && (
        <div className="health-grid">
          <div className="health-card">
            <h4>Incidents by kind</h4>
            <BarChart data={metrics.incident_rates.by_kind} onBarClick={showKind} />
          </div>
          <div className="health-card">
            <h4>Incidents by risk tier</h4>
            <BarChart
              data={metrics.incident_rates.by_risk_tier}
              colorClassFor={(l) => RISK_COLOR_CLASS[l] || "bar-fill-accent"}
              onBarClick={showTier}
            />
          </div>
        </div>
      )}

      <SubHeading
        title="Extended monitoring rollups"
        purpose="Pure aggregations over real data already on file — schema-validation compliance over time, real PII/injection scan results, and human-approval quality. No new incidents live here; these are population-level signals, not per-event alerts."
      />
      {metrics && (
        <div className="health-grid">
          <div className="health-card">
            <h4>Schema compliance by company</h4>
            {metrics.schema_compliance.length === 0 ? (
              <p className="muted">No cycles recorded yet.</p>
            ) : (
              <ul className="rollup-list">
                {metrics.schema_compliance.map((s) => (
                  <li key={s.company_id}>
                    <span className="mono">{s.company_id}</span>: {s.compliance_rate_pct}% ({s.assessment_failed_count} failed / {s.total_cycles} cycles)
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="health-card">
            <h4>Security scan summary</h4>
            <ul className="rollup-list">
              <li>PII scans: {metrics.security_scan_summary.pii_detected} detected / {metrics.security_scan_summary.pii_scans_run} run</li>
              <li>Injection scans: {metrics.security_scan_summary.injection_marker_hits} marker hit(s) / {metrics.security_scan_summary.injection_scans_run} run</li>
            </ul>
          </div>
          <div className="health-card health-card-wide">
            <h4>Human-approval quality</h4>
            {metrics.approval_quality_flags.length === 0 ? (
              <p className="muted">No decided approvals yet.</p>
            ) : (
              <ul className="rollup-list">
                {metrics.approval_quality_flags.map((f) => (
                  <li key={f.incident_id}>
                    {f.incident_id}: {f.status} in {f.review_minutes} minute(s){" "}
                    {f.rubber_stamp_candidate ? "(rubber-stamp candidate)" : "(reviewed with time to spare)"}
                  </li>
                ))}
              </ul>
            )}
            {Object.keys(metrics.unexpected_tool_calls).length > 0 && (
              <>
                <h4>Unexpected tool calls</h4>
                <ul className="rollup-list">
                  {Object.entries(metrics.unexpected_tool_calls).map(([agent, calls]) => (
                    <li key={agent}>
                      <span className="mono">{agent}</span>: {calls.map((c) => c.tool_name).join(", ")}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}

      <SubHeading
        title="Stack Sentinel's own classifiers"
        purpose="The seven single-shot agents that produce the classifications above — versioned and rollback-protected the same way as any company's own agents. Click one for its full version history."
      />
      <RegistryPillRow />

      {drilldown && (
        <IncidentDrilldownModal
          title={drilldown.title}
          incidents={drilldown.incidents}
          onClose={() => setDrilldown(null)}
          onSelect={(i) => setDrilldownDetail(i)}
        />
      )}
      {drilldownDetail && <IncidentDetailModal incident={drilldownDetail} onClose={() => setDrilldownDetail(null)} />}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Companies — pick one company from the dropdown for its full detail. Kept separate from
// System above: System is the portfolio-wide snapshot, this is the per-company deep dive.
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
  // Branch on the DATA's actual shape, not just isCharter: for exactly one render right after
  // switching companies, `data` can still hold the PREVIOUS company's response (the refetch
  // effect hasn't run yet) while isCharter has already flipped for the new company — branching
  // on isCharter alone would then read the wrong shape (e.g. .slos on a charter response) and
  // crash. Checking the field itself is resilient to that one-render staleness.
  if (!data) return null;
  const showCharter = isCharter && Array.isArray(data.agent_behavior_boundaries);
  const showSlo = !isCharter && data.slos && typeof data.slos === "object";
  if (!showCharter && !showSlo) return null;
  return (
    <div className="charter-panel">
      <p className="charter-summary">{data.summary}</p>
      {showCharter ? (
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
 * Distinct from System's classifier pills above, which are Stack Sentinel's OWN seven
 * classifiers, not any company's agents. Cards stay concise; a click opens the full version
 * history. */
function CompanyAgentsPanel({ companyId, refreshKey }) {
  const { data: agents } = useAsync(() => api.getCompanyAgents(companyId), [companyId, refreshKey]);
  const [openAgent, setOpenAgent] = useState(null);
  if (!agents || agents.length === 0) return null;
  return (
    <>
      <div className="company-agents-grid">
        {agents.map((a) => {
          const auto = a.active?.activated_by;
          const wasRolledBack = auto && auto !== "initial-deployment";
          return (
            <div
              key={a.agent}
              className={wasRolledBack ? "agent-card agent-card-rolled-back" : "agent-card"}
              role="button"
              tabIndex={0}
              onClick={() => setOpenAgent(a)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setOpenAgent(a)}
            >
              <div className="agent-card-name mono">{a.agent}</div>
              <div className="agent-card-version">
                active <strong>{a.active?.version ?? "—"}</strong>
                {a.versions.length > 1 && <span className="muted"> · {a.versions.length} versions</span>}
              </div>
              {wasRolledBack && <div className="agent-card-flag">rolled back</div>}
            </div>
          );
        })}
      </div>
      {openAgent && (
        <Modal
          title={openAgent.agent}
          subtitle={openAgent.active ? `active: ${openAgent.active.version} · by ${openAgent.active.activated_by}` : "not yet activated"}
          onClose={() => setOpenAgent(null)}
        >
          <ul className="version-list">
            {openAgent.versions.map((v) => (
              <li key={v.version} className={v.version === openAgent.active?.version ? "version-active" : ""}>
                <strong className="mono">{v.version}</strong> <span className="muted">({v.created})</span> — {v.changelog}
              </li>
            ))}
          </ul>
        </Modal>
      )}
    </>
  );
}

/** This company's own policy document. On-page: just the clause titles (concise). Full text
 * only in the popup, per the "concise page, detailed popup" rule. */
function CompanyPolicyPanel({ companyId }) {
  const { data } = useAsync(() => api.getCompanyPolicy(companyId), [companyId]);
  const [open, setOpen] = useState(false);
  if (!data) return null;
  const titles = data.markdown
    .split("\n")
    .filter((l) => l.startsWith("## "))
    .map((l) => l.replace(/^##\s*/, "").trim());
  return (
    <div className="policy-summary">
      <ul className="clause-list">
        {titles.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
      <button className="btn-secondary btn-small" onClick={() => setOpen(true)}>
        View full policy
      </button>
      {open && (
        <Modal title={`${data.company_id} — company policy`} onClose={() => setOpen(false)}>
          <pre className="policy-text policy-text-full">{data.markdown}</pre>
        </Modal>
      )}
    </div>
  );
}

function CompanyBlock({ company, incidents, onSelectCycle, agentsRefreshKey, onViewIncidents }) {
  const { data: trend } = useAsync(() => api.getTrend(company.company_id), [company.company_id]);
  const companyIncidents = (incidents || []).filter((i) => i.company_ids?.includes(company.company_id));

  return (
    <div id={`company-${company.company_id}`} className="company-block">
      <div className="company-block-header">
        <h3>{company.name}</h3>
        <span className="track-pill">{company.monitoring_track}</span>
        {COMPANY_DEMO_URLS[company.company_id] && (
          <a
            className="company-demo-link"
            href={COMPANY_DEMO_URLS[company.company_id]}
            target="_blank"
            rel="noopener noreferrer"
          >
            View live demo ↗
          </a>
        )}
      </div>
      <p className="muted">{company.sector}</p>

      <SubHeading
        first
        title={company.monitoring_track === "CHARTER" ? "Charter boundaries" : "SLO thresholds"}
        purpose={
          company.monitoring_track === "CHARTER"
            ? "The behavior rules goal-drift-tracker checks this company's agents against every cycle."
            : "The error-budget thresholds slo-risk-tracker checks this company's operational health against every cycle."
        }
      />
      <CompanyCharterPanel key={company.company_id} company={company} />

      <SubHeading
        title="Internal agents"
        purpose="This company's OWN agents (not Stack Sentinel's) — the actual subject of the risk-tiered rollback mechanism. Click a card for its full version history."
      />
      <CompanyAgentsPanel companyId={company.company_id} refreshKey={agentsRefreshKey} />

      <SubHeading
        title="Policy"
        purpose="This company's own escalation clauses, checked alongside the shared portfolio-wide policy on every incident."
      />
      <CompanyPolicyPanel companyId={company.company_id} />

      <SubHeading
        title="Operational health & incidents"
        purpose="Full cycle-by-cycle history. Click a chart point or a table row for the complete record of that cycle."
      />
      {trend && trend.length >= 2 && (
        <>
          <HealthChart entries={trend} onPointClick={(entry) => onSelectCycle(company, entry)} />
          <div className="mini-trend-grid">
            <div>
              <HealthChart entries={trend} compact metricField="llm_cost_usd" label="LLM cost" unit="$" />
              <p className="mini-trend-label">Cost</p>
            </div>
            <div>
              <HealthChart entries={trend} compact metricField="context_utilization_pct" label="Context utilization" unit="%" />
              <p className="mini-trend-label">Context pressure</p>
            </div>
            <div>
              <HealthChart entries={trend} compact metricField="user_escalation_rate_pct" label="User escalation" unit="%" />
              <p className="mini-trend-label">User escalation</p>
            </div>
          </div>
        </>
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
                    <td className="rationale-cell" title={e.rationale}>{e.rationale}</td>
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
            <button
              key={i.incident_id}
              className="mini-incident-chip"
              onClick={() => onViewIncidents(company.company_id)}
            >
              {i.incident_id} · {i.kind} · {i.status}
            </button>
          ))}
          <button className="mini-incidents-viewall" onClick={() => onViewIncidents(company.company_id)}>
            View all in Incidents →
          </button>
        </div>
      )}
    </div>
  );
}

function CompaniesSection({ agentsRefreshKey, selectedCompanyId, onSelectCompanyId, onViewCompanyIncidents }) {
  const { loading, error, data: companies } = useAsync(api.listCompanies, []);
  const { data: incidents } = useAsync(() => api.listIncidents(), []);
  const [selected, setSelected] = useState(null); // { company, entry }

  useEffect(() => {
    if (companies && !selectedCompanyId && companies.length > 0) {
      onSelectCompanyId(companies[0].company_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companies]);

  const company = companies?.find((c) => c.company_id === selectedCompanyId);

  return (
    <section id="companies" className="page-section">
      <SectionHeader
        eyebrow="Detail"
        title="Companies"
        description="Pick a company for its charter/SLO, internal agents and their rollback status, policy, and full cycle-by-cycle history."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading…</p>}
      {companies && (
        <>
          <div className="company-select-row">
            <label className="company-select-label" htmlFor="company-select">
              Company
            </label>
            <select
              id="company-select"
              className="company-select"
              value={selectedCompanyId || ""}
              onChange={(e) => onSelectCompanyId(e.target.value)}
            >
              {companies.map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.name} — {c.monitoring_track}
                </option>
              ))}
            </select>
          </div>
          {company && (
            <CompanyBlock
              company={company}
              incidents={incidents}
              onSelectCycle={(company, entry) => setSelected({ company, entry })}
              agentsRefreshKey={agentsRefreshKey}
              onViewIncidents={onViewCompanyIncidents}
            />
          )}
        </>
      )}
      {selected && (
        <CycleDetailModal company={selected.company} entry={selected.entry} onClose={() => setSelected(null)} />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

function IncidentsSection({ onDecisionRecorded, companyFilter, onCompanyFilterChange }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const { loading, error, data: incidentList } = useAsync(() => api.listIncidents(), [refreshKey]);
  const { data: companies } = useAsync(api.listCompanies, []);
  const [decidedBy, setDecidedBy] = useState("");
  const [note, setNote] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [detail, setDetail] = useState(null);

  const filtered = (incidentList || []).filter(
    (i) => companyFilter === "all" || i.company_ids?.includes(companyFilter)
  );

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
        description="Every incident on record — click a row for the full detail, including its policy check. The only write action in this app lives here: Approve or Reject on anything pending_human_approval."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading incidents…</p>}
      {incidentList && (
        <>
          <div className="company-select-row">
            <label className="company-select-label" htmlFor="incident-company-filter">
              Company
            </label>
            <select
              id="incident-company-filter"
              className="company-select"
              value={companyFilter}
              onChange={(e) => onCompanyFilterChange(e.target.value)}
            >
              <option value="all">All companies</option>
              {(companies || []).map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.name}
                </option>
              ))}
            </select>
            {companyFilter !== "all" && (
              <span className="muted">
                {filtered.length} of {incidentList.length} incident(s)
              </span>
            )}
          </div>
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
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">No incidents for this company.</td>
                  </tr>
                )}
                {filtered.map((i) => (
                  <tr key={i.incident_id} className="row-clickable" onClick={() => setDetail(i)}>
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
                          <button
                            disabled={busyId === i.incident_id}
                            onClick={(e) => { e.stopPropagation(); decide(i.incident_id, "approved"); }}
                          >
                            Approve
                          </button>
                          <button
                            className="btn-secondary"
                            disabled={busyId === i.incident_id}
                            onClick={(e) => { e.stopPropagation(); decide(i.incident_id, "rejected"); }}
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
      {detail && <IncidentDetailModal incident={detail} onClose={() => setDetail(null)} />}
    </section>
  );
}

// ---------------------------------------------------------------------------

function AskSection() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [cached, setCached] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    setAnswer(null);
    try {
      const res = await api.ask(question);
      setAnswer(res.answer);
      setCached(Boolean(res.cached));
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
        description="Grounded on this run's real data — every company, cycle, and incident. Repeat questions are served from cache instead of re-calling the LLM, until the underlying data actually changes. Requires OPENAI_API_KEY on the console API process; the one place this app calls a live third-party LLM, separate from the deterministic core and the seven Claude subagents."
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
      {answer && (
        <div className="ask-answer">
          {cached && <div className="ask-cached-badge">served from cache</div>}
          <div>{answer}</div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

export default function App() {
  const active = useActiveSection(SECTIONS.map((s) => s.id));
  const [agentsRefreshKey, setAgentsRefreshKey] = useState(0);
  const [selectedCompanyId, setSelectedCompanyId] = useState(null);
  const [incidentCompanyFilter, setIncidentCompanyFilter] = useState("all");

  // The single place a company gets "selected" — from a System card, the Companies dropdown,
  // or any other company-picking control. Keeps the Companies detail AND the Incidents filter
  // in lockstep: picking a company anywhere immediately scopes Incidents to that company too,
  // so a click always shows "this company's detail + this company's incidents, and only
  // those" rather than requiring a second manual filter step.
  function selectCompany(companyId) {
    setSelectedCompanyId(companyId);
    setIncidentCompanyFilter(companyId);
  }

  function jumpToCompany(companyId) {
    selectCompany(companyId);
    document.getElementById("companies")?.scrollIntoView({ behavior: "smooth" });
  }

  function jumpToCompanyIncidents(companyId) {
    setIncidentCompanyFilter(companyId);
    document.getElementById("incidents")?.scrollIntoView({ behavior: "smooth" });
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Stack Sentinel</h1>
        <p className="subtitle">Multi-agent AI software monitoring — live operator console</p>
      </header>

      {STATIC_MODE && (
        <div className="static-preview-banner">
          Read-only preview of one real simulation run — Approve/Reject and Ask are disabled
          here. Clone the repo and run the live console locally to use them.
        </div>
      )}

      <nav className="section-nav">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#${s.id}`} className={active === s.id ? "nav-link nav-link-active" : "nav-link"}>
            {s.label}
          </a>
        ))}
      </nav>

      <main className="page-body">
        <SystemSection onSelectCompany={jumpToCompany} selectedCompanyId={selectedCompanyId} />
        <AskSection />
        <CompaniesSection
          agentsRefreshKey={agentsRefreshKey}
          selectedCompanyId={selectedCompanyId}
          onSelectCompanyId={selectCompany}
          onViewCompanyIncidents={jumpToCompanyIncidents}
        />
        <IncidentsSection
          onDecisionRecorded={() => setAgentsRefreshKey((k) => k + 1)}
          companyFilter={incidentCompanyFilter}
          onCompanyFilterChange={setIncidentCompanyFilter}
        />
      </main>

      <footer className="app-footer">
        {STATIC_MODE
          ? "Stack Sentinel — static preview. Full source: github.com/AnikNicks/stack-sentinel"
          : "Stack Sentinel — local-only operator console."}
      </footer>
    </div>
  );
}
