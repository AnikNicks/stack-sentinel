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

// ---------------------------------------------------------------------------

function OverviewSection() {
  const { loading, error, data: companies } = useAsync(api.listCompanies, []);
  const [latest, setLatest] = useState({});

  useEffect(() => {
    if (!companies) return;
    companies.forEach((c) => {
      api.getTrend(c.company_id, 1).then((h) => {
        setLatest((prev) => ({ ...prev, [c.company_id]: h[0] || null }));
      });
    });
  }, [companies]);

  return (
    <section id="overview" className="page-section">
      <SectionHeader
        eyebrow="Portfolio"
        title="Overview"
        description="Latest recorded classification for every monitored company."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading portfolio…</p>}
      {companies && (
        <div className="card-grid">
          {companies.map((c) => {
            const entry = latest[c.company_id];
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
              </a>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

function CompanyBlock({ company, incidents }) {
  const { data: trend } = useAsync(() => api.getTrend(company.company_id), [company.company_id]);
  const companyIncidents = (incidents || []).filter((i) => i.company_ids?.includes(company.company_id));

  return (
    <div id={`company-${company.company_id}`} className="company-block">
      <div className="company-block-header">
        <h3>{company.name}</h3>
        <span className="track-pill">{company.monitoring_track}</span>
      </div>
      <p className="muted">{company.sector}</p>

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
                  <tr key={e.cycle} className={incidentsCount ? "row-flagged" : ""}>
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

function CompaniesSection() {
  const { loading, error, data: companies } = useAsync(api.listCompanies, []);
  const { data: incidents } = useAsync(() => api.listIncidents(), []);

  return (
    <section id="companies" className="page-section">
      <SectionHeader
        eyebrow="Detail"
        title="Companies"
        description="Full cycle-by-cycle trend history for every monitored company."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading…</p>}
      {companies && (
        <div className="company-block-list">
          {companies.map((c) => (
            <CompanyBlock key={c.company_id} company={c} incidents={incidents} />
          ))}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------

function IncidentsSection() {
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
        title="Registry"
        description="Every agent's version history and which version is currently active."
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

function SystemHealthSection() {
  const { loading, error, data } = useAsync(api.getMetrics, []);
  return (
    <section id="health" className="page-section">
      <SectionHeader
        eyebrow="Observability"
        title="System Health"
        description="Read-only rollups over the trend store and incident log."
      />
      {error && <ErrorBanner error={error} />}
      {loading && <p className="muted">Loading…</p>}
      {data && (
        <div className="health-grid">
          <div className="health-card">
            <h4>Incidents by kind</h4>
            <pre>{JSON.stringify(data.incident_rates.by_kind, null, 2)}</pre>
          </div>
          <div className="health-card">
            <h4>Incidents by risk tier</h4>
            <pre>{JSON.stringify(data.incident_rates.by_risk_tier, null, 2)}</pre>
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
        <CompaniesSection />
        <IncidentsSection />
        <RegistrySection />
        <SystemHealthSection />
        <AskSection />
      </main>

      <footer className="app-footer">Stack Sentinel — local-only operator console.</footer>
    </div>
  );
}
