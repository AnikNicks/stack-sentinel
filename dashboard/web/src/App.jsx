import { useEffect, useState } from "react";
import { api, AGENTS } from "./api";
import "./App.css";

const TABS = ["Overview", "Company", "Incidents", "Registry", "System Health", "Ask"];

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

function StatusBadge({ classification }) {
  const cls = classification || "unknown";
  return <span className={`badge badge-${cls}`}>{cls}</span>;
}

function ErrorBanner({ error }) {
  if (!error) return null;
  return (
    <div className="error-banner">
      Could not reach the console API at http://127.0.0.1:8000 — is{" "}
      <code>uvicorn dashboard.api.main:app --reload</code> running? ({error.message})
    </div>
  );
}

function OverviewPage({ onSelectCompany }) {
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

  if (error) return <ErrorBanner error={error} />;
  if (loading) return <p>Loading portfolio...</p>;

  return (
    <div className="card-grid">
      {companies.map((c) => {
        const entry = latest[c.company_id];
        return (
          <div
            key={c.company_id}
            className="company-card"
            onClick={() => onSelectCompany(c.company_id)}
          >
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
          </div>
        );
      })}
    </div>
  );
}

function CompanyPage({ companyId, onSelectCompany }) {
  const { loading, error, data: companies } = useAsync(api.listCompanies, []);
  const active = companyId || companies?.[0]?.company_id;
  const { data: trend } = useAsync(
    () => (active ? api.getTrend(active) : Promise.resolve([])),
    [active]
  );
  const { data: incidents } = useAsync(api.listIncidents.bind(null, undefined), []);

  if (error) return <ErrorBanner error={error} />;
  if (loading) return <p>Loading...</p>;

  const companyIncidents = (incidents || []).filter((i) =>
    Object.values(i.company_ids || []).includes(active) || i.company_ids?.includes(active)
  );

  return (
    <div>
      <div className="tab-strip">
        {companies?.map((c) => (
          <button
            key={c.company_id}
            className={c.company_id === active ? "chip chip-active" : "chip"}
            onClick={() => onSelectCompany(c.company_id)}
          >
            {c.name}
          </button>
        ))}
      </div>
      {!trend || trend.length === 0 ? (
        <p>No cycles recorded yet for {active}.</p>
      ) : (
        <table className="trend-table">
          <thead>
            <tr>
              <th>Cycle</th>
              <th>Classification</th>
              <th>Behavior incidents</th>
              <th>Layer changes this cycle</th>
              <th>Rationale</th>
            </tr>
          </thead>
          <tbody>
            {[...trend].reverse().map((e) => {
              const layers = e.metric_snapshot?.layers || {};
              const changed = Object.entries(layers).filter(([, v]) => v.change_event);
              const incidentsCount = e.metric_snapshot?.behavior_incidents?.length || 0;
              return (
                <tr key={e.cycle}>
                  <td>{e.cycle}</td>
                  <td>
                    <StatusBadge classification={e.classification} />
                  </td>
                  <td>{incidentsCount}</td>
                  <td>
                    {changed.length === 0
                      ? "—"
                      : changed.map(([layer]) => layer).join(", ")}
                  </td>
                  <td className="rationale-cell">{e.rationale}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <h4>Incidents involving {active}</h4>
      {companyIncidents.length === 0 ? (
        <p>None on record.</p>
      ) : (
        <ul className="incident-mini-list">
          {companyIncidents.map((i) => (
            <li key={i.incident_id}>
              <strong>{i.incident_id}</strong> — {i.kind} ({i.status})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function IncidentsPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const { loading, error, data: incidentList } = useAsync(
    () => api.listIncidents(),
    [refreshKey]
  );
  const [decidedBy, setDecidedBy] = useState("");
  const [note, setNote] = useState("");
  const [busyId, setBusyId] = useState(null);

  if (error) return <ErrorBanner error={error} />;
  if (loading) return <p>Loading incidents...</p>;

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
    <div>
      <div className="decision-form">
        <input
          placeholder="decided_by (your name/email)"
          value={decidedBy}
          onChange={(e) => setDecidedBy(e.target.value)}
        />
        <input
          placeholder="note (why)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>
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
              <td>{i.incident_id}</td>
              <td>{i.kind}</td>
              <td>{i.company_ids?.join(", ")}</td>
              <td>
                <span className={`risk risk-${i.risk_tier}`}>{i.risk_tier}</span>
              </td>
              <td>{i.routing}</td>
              <td>{i.status}</td>
              <td>
                {i.status === "pending_human_approval" ? (
                  <>
                    <button
                      disabled={busyId === i.incident_id}
                      onClick={() => decide(i.incident_id, "approved")}
                    >
                      Approve
                    </button>
                    <button
                      disabled={busyId === i.incident_id}
                      onClick={() => decide(i.incident_id, "rejected")}
                    >
                      Reject
                    </button>
                  </>
                ) : (
                  <em>—</em>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RegistryPage() {
  const [agent, setAgent] = useState(AGENTS[2]);
  const { loading, error, data } = useAsync(() => api.getRegistry(agent), [agent]);

  return (
    <div>
      <div className="tab-strip">
        {AGENTS.map((a) => (
          <button
            key={a}
            className={a === agent ? "chip chip-active" : "chip"}
            onClick={() => setAgent(a)}
          >
            {a}
          </button>
        ))}
      </div>
      {error && <ErrorBanner error={error} />}
      {loading && <p>Loading...</p>}
      {data && (
        <>
          <p>
            Active version: <strong>{data.active?.version}</strong> (activated by{" "}
            {data.active?.activated_by})
          </p>
          <ul className="version-list">
            {data.versions.map((v) => (
              <li key={v.version} className={v.version === data.active?.version ? "version-active" : ""}>
                <strong>{v.version}</strong> ({v.created}) — {v.changelog}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function SystemHealthPage() {
  const { loading, error, data } = useAsync(api.getMetrics, []);
  if (error) return <ErrorBanner error={error} />;
  if (loading) return <p>Loading...</p>;
  return (
    <div>
      <h4>Incidents by kind</h4>
      <pre>{JSON.stringify(data.incident_rates.by_kind, null, 2)}</pre>
      <h4>Incidents by risk tier</h4>
      <pre>{JSON.stringify(data.incident_rates.by_risk_tier, null, 2)}</pre>
      <h4>Human-approval turnaround</h4>
      {data.approval_turnaround.length === 0 ? (
        <p>No decided approvals yet.</p>
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
      <p>{data.companies_tracked.join(", ") || "none yet"}</p>
    </div>
  );
}

function AskPage() {
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
    <div>
      <p>
        Ask a question grounded in this run's real data. Requires <code>OPENAI_API_KEY</code>{" "}
        set on the console API process — the one place this app calls a live third-party LLM,
        separate from the deterministic core and the six Claude subagents.
      </p>
      <textarea
        rows={3}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="e.g. Why was change-impact-synthesizer rolled back?"
      />
      <div>
        <button disabled={busy || !question.trim()} onClick={submit}>
          {busy ? "Asking..." : "Ask"}
        </button>
      </div>
      {err && <div className="error-banner">{err}</div>}
      {answer && <div className="ask-answer">{answer}</div>}
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("Overview");
  const [selectedCompany, setSelectedCompany] = useState(null);

  function goToCompany(id) {
    setSelectedCompany(id);
    setTab("Company");
  }

  return (
    <div className="app-shell">
      <header>
        <h1>Stack Sentinel</h1>
        <p className="subtitle">Multi-agent AI software monitoring — live operator console</p>
      </header>
      <nav>
        {TABS.map((t) => (
          <button
            key={t}
            className={t === tab ? "nav-btn nav-btn-active" : "nav-btn"}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>
      <main>
        {tab === "Overview" && <OverviewPage onSelectCompany={goToCompany} />}
        {tab === "Company" && (
          <CompanyPage companyId={selectedCompany} onSelectCompany={setSelectedCompany} />
        )}
        {tab === "Incidents" && <IncidentsPage />}
        {tab === "Registry" && <RegistryPage />}
        {tab === "System Health" && <SystemHealthPage />}
        {tab === "Ask" && <AskPage />}
      </main>
    </div>
  );
}
