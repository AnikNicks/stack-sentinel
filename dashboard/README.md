# Stack Sentinel — live operator console

`api/` is a FastAPI backend that's a thin read (+ one write) layer directly over `pulse/*`
and `mcp_server/tools_impl.py` — see `api/main.py`'s module docstring. `web/` is a Vite +
React frontend consuming that API.

Local-only by design: no auth, no deployment target, CORS restricted to the Vite dev server's
origin. This is a single-user local demo console, not a production multi-tenant app.

## Run it

From the repo root, in two terminals:

```bash
# 1. Backend (needs the repo root's .venv, with fastapi/uvicorn installed via requirements.txt)
.venv\Scripts\python -m uvicorn dashboard.api.main:app --reload

# 2. Frontend
cd dashboard/web
npm install   # first time only
npm run dev
```

Open http://localhost:5173. The backend serves real data straight from `data/` — run
`python scripts/simulate_production_run.py --reset` first if you want a fresh run's data.

## Pages

- **Overview** — per-company status cards (latest classification, cycle).
- **Company** — full cycle-by-cycle trend table: classification, behavior-incident count,
  which layers changed, and the real scripted rationale for that cycle.
- **Incidents** — every incident on record; the only write action in the whole app lives
  here — Approve/Reject on any incident still `pending_human_approval`, which calls
  `pulse.incidents.record_approval_decision` and nothing else.
- **Registry** — each agent's version history and which version is currently active.
- **System Health** — `pulse/metrics.py`'s rollups: incident rate by kind/tier, human-approval
  turnaround, companies tracked.
- **Ask** — grounded Q&A over the real run data via OpenAI (`POST /ask`), the one place this
  app calls a live third-party LLM. Requires `OPENAI_API_KEY` set in the backend's
  environment (or repo-root `.env`); without it, the endpoint returns a clear 503 rather than
  a wrong answer.
