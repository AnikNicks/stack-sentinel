import { useState } from "react";
import fixture from "./fixtures/cycles.json";
import "./App.css";

function ConsolePage() {
  const [request, setRequest] = useState("");
  const [itinerary, setItinerary] = useState(null);
  const [confirmed, setConfirmed] = useState(false);

  function planTrip() {
    setItinerary({
      destination: request || "Lisbon, Portugal",
      fare: "Non-refundable saver fare — $412",
    });
    setConfirmed(false);
  }

  function attemptBooking() {
    // Blocked until the explicit confirmation step below is completed and logged.
  }

  function confirmAndBook() {
    setConfirmed(true);
  }

  return (
    <div className="console">
      <div className="panel">
        <h3>Plan a trip</h3>
        <input
          className="text-input"
          placeholder="Where do you want to go?"
          value={request}
          onChange={(e) => setRequest(e.target.value)}
        />
        <button onClick={planTrip}>Get itinerary</button>
        {itinerary && (
          <div className="ticket">
            <p>
              Proposed: <strong>{itinerary.destination}</strong>
            </p>
            <p className="fare">{itinerary.fare}</p>
          </div>
        )}
      </div>

      <div className="panel">
        <h3>Booking</h3>
        <p className="hint">
          Charter boundary: agent must never confirm a non-refundable booking without an
          explicit customer confirmation step logged in the same session.
        </p>
        {!itinerary ? (
          <p className="quiet">Plan a trip first.</p>
        ) : confirmed ? (
          <div className="outcome outcome-ok">
            ✓ Confirmation logged, then booking completed — in that order.
          </div>
        ) : (
          <>
            <button className="btn-blocked" onClick={attemptBooking} disabled>
              Complete booking (blocked — confirmation not yet logged)
            </button>
            <div className="confirm-box">
              <label>
                <input type="checkbox" onChange={confirmAndBook} /> I understand this fare is
                non-refundable. Confirm booking.
              </label>
            </div>
          </>
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
        <h1>Wayfinder Copilot</h1>
        <p className="subtitle">{fixture.company.system_charter.summary}</p>
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
