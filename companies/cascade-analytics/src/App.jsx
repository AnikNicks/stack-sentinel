import { useState } from "react";
import fixture from "./fixtures/cycles.json";
import "./App.css";

const SLO = fixture.company.slo_agreement.slos.monthly_error_budget_consumed_pct;

function statusFor(pct) {
  if (pct >= SLO.breach_at_or_above) return "breach";
  if (pct >= SLO.warning_at_or_above) return "warning";
  return "compliant";
}

function Gauge({ pct }) {
  const status = statusFor(pct);
  return (
    <div className="gauge">
      <div className="gauge-track">
        <div className={`gauge-fill gauge-${status}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <div className="gauge-label">
        {pct}% of monthly error budget consumed —{" "}
        <span className={`status-tag status-${status}`}>{status}</span>
      </div>
    </div>
  );
}

function ConsolePage() {
  const cycleIds = Object.keys(fixture.cycles);
  const latestCycle = cycleIds[cycleIds.length - 1];
  const latest = fixture.cycles[latestCycle];
  const pct = latest.operational_health.monthly_error_budget_consumed_pct;

  return (
    <div className="console">
      <div className="panel">
        <h3>Sub-agent status</h3>
        <ul className="agent-list">
          <li><span className="dot dot-ok" /> schema-inference-agent — healthy</li>
          <li><span className="dot dot-ok" /> anomaly-detection-agent — healthy</li>
          <li>
            <span className={statusFor(pct) === "compliant" ? "dot dot-ok" : "dot dot-warn"} />
            auto-remediation-agent — {statusFor(pct) === "compliant" ? "healthy" : "elevated error rate"}
          </li>
        </ul>
      </div>
      <div className="panel">
        <h3>Error budget — {latestCycle}</h3>
        <Gauge pct={pct} />
        <p className="hint">
          Compliant below {SLO.warning_at_or_above}%, warning at or above{" "}
          {SLO.warning_at_or_above}%, breach at or above {SLO.breach_at_or_above}%.
        </p>
      </div>
      <div className="panel panel-wide">
        <h3>Recent schema changes</h3>
        <ul className="schema-list">
          {cycleIds.slice(-5).map((c) => {
            const ev = fixture.cycles[c].layers.database.change_event;
            if (!ev) return null;
            return (
              <li key={c} className={ev.reversible ? "" : "schema-destructive"}>
                <strong>{c}</strong> — {ev.description}{" "}
                {!ev.reversible && <span className="danger-tag">NON-REVERSIBLE — blocked, pending human approval</span>}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function ReplayPage() {
  const cycles = Object.entries(fixture.cycles);
  return (
    <div className="replay">
      {cycles.map(([cycle, data]) => {
        const changed = Object.entries(data.layers).filter(([, v]) => v.change_event);
        const destructive = changed.some(([, v]) => v.change_event.reversible === false);
        const pct = data.operational_health.monthly_error_budget_consumed_pct;
        return (
          <div key={cycle} className={destructive ? "cycle-card cycle-flagged" : "cycle-card"}>
            <div className="cycle-header">
              <strong>{cycle}</strong>
              <span className={`status-tag status-${statusFor(pct)}`}>{statusFor(pct)} ({pct}%)</span>
            </div>
            {changed.length > 0 && (
              <div className="changes">
                {changed.map(([layer, v]) => (
                  <div key={layer} className="change-row">
                    <span className="layer-tag">{layer}</span> {v.change_event.description}
                    {v.change_event.reversible === false && (
                      <span className="danger-tag"> BLOCKED — pending human approval</span>
                    )}
                  </div>
                ))}
              </div>
            )}
            {changed.length === 0 && <p className="quiet">No layer changes this cycle.</p>}
          </div>
        );
      })}
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("console");
  return (
    <div className="app-shell">
      <header>
        <h1>Cascade Pipeline Agent</h1>
        <p className="subtitle">{fixture.company.slo_agreement.summary}</p>
      </header>
      <nav>
        <button className={tab === "console" ? "nav-btn nav-btn-active" : "nav-btn"} onClick={() => setTab("console")}>
          Product
        </button>
        <button className={tab === "replay" ? "nav-btn nav-btn-active" : "nav-btn"} onClick={() => setTab("replay")}>
          Cycle Replay
        </button>
      </nav>
      <main>{tab === "console" ? <ConsolePage /> : <ReplayPage />}</main>
      <footer>
        Illustrative product demo — read-only, driven by Stack Sentinel's real monitoring
        data. Nothing here feeds back into the monitoring pipeline.
      </footer>
    </div>
  );
}
