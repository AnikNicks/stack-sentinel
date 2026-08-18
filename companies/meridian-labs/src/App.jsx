import { useState } from "react";
import fixture from "./fixtures/cycles.json";
import "./App.css";

const REFUND_BOUNDARY = 200;

function ConsolePage() {
  const [ticket, setTicket] = useState(null);
  const [amount, setAmount] = useState(120);
  const [addressTicket, setAddressTicket] = useState(null);

  function submitTicket() {
    setTicket({ text: `Customer requests a $${amount} refund for order #48213.` });
  }

  function proposeRefund() {
    if (amount > REFUND_BOUNDARY) {
      setTicket((t) => ({ ...t, resolution: "pending_approval" }));
    } else {
      setTicket((t) => ({ ...t, resolution: "auto_approved" }));
    }
  }

  function requestAddressChange() {
    setAddressTicket({ step: "requested" });
  }

  function confirmAddressChange() {
    setAddressTicket({ step: "confirmed" });
  }

  return (
    <div className="console">
      <div className="panel">
        <h3>Intake — Refund request</h3>
        <p className="hint">
          Charter boundary: refunds over ${REFUND_BOUNDARY} must be routed to human approval
          before execution.
        </p>
        <label>
          Refund amount ($)
          <input
            type="number"
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
          />
        </label>
        <div>
          <button onClick={submitTicket}>Submit support ticket</button>
        </div>
        {ticket && (
          <div className="ticket">
            <p>{ticket.text}</p>
            {!ticket.resolution && (
              <button onClick={proposeRefund}>Resolution agent: propose refund</button>
            )}
            {ticket.resolution === "auto_approved" && (
              <div className="outcome outcome-ok">
                Auto-completed — under the ${REFUND_BOUNDARY} boundary, no human approval
                required.
              </div>
            )}
            {ticket.resolution === "pending_approval" && (
              <div className="outcome outcome-blocked">
                ⏸ Pending human approval — amount exceeds ${REFUND_BOUNDARY}. Not
                auto-completed, per charter.
              </div>
            )}
          </div>
        )}
      </div>

      <div className="panel">
        <h3>Shipping-address change</h3>
        <p className="hint">
          Charter boundary: a shipping-address change requires a logged confirmation step
          before it takes effect.
        </p>
        <button onClick={requestAddressChange}>
          Customer requests shipping-address change
        </button>
        {addressTicket?.step === "requested" && (
          <div className="ticket">
            <p>New address captured. Awaiting logged confirmation before applying.</p>
            <button onClick={confirmAddressChange}>Log confirmation &amp; apply</button>
          </div>
        )}
        {addressTicket?.step === "confirmed" && (
          <div className="outcome outcome-ok">
            Confirmation logged — shipping address updated.
          </div>
        )}
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
        const flagged = data.behavior_incidents.length > 0;
        return (
          <div key={cycle} className={flagged ? "cycle-card cycle-flagged" : "cycle-card"}>
            <div className="cycle-header">
              <strong>{cycle}</strong>
              <span className="health">
                error rate {data.operational_health.error_rate_pct}% · p95{" "}
                {data.operational_health.p95_latency_ms}ms · uptime{" "}
                {data.operational_health.uptime_pct}%
              </span>
            </div>
            {changed.length > 0 && (
              <div className="changes">
                {changed.map(([layer, v]) => (
                  <div key={layer} className="change-row">
                    <span className="layer-tag">{layer}</span> {v.change_event.description}
                  </div>
                ))}
              </div>
            )}
            {data.behavior_incidents.map((inc, i) => (
              <div key={i} className="incident-row">
                <strong>Flagged:</strong> {inc.description}
                <div className="boundary">boundary: {inc.boundary_violated}</div>
              </div>
            ))}
            {!flagged && changed.length === 0 && <p className="quiet">Quiet cycle.</p>}
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
        <h1>Meridian Concierge</h1>
        <p className="subtitle">
          {fixture.company.system_charter.summary}
        </p>
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
