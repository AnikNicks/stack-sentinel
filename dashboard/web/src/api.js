import snapshot from "./fixtures/dashboard_snapshot.json";

const API_BASE = "http://127.0.0.1:8000";

async function request(path, options) {
  const res = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

const liveApi = {
  listCompanies: () => request("/companies"),
  getTrend: (companyId, limit) =>
    request(`/companies/${companyId}/trend${limit ? `?limit=${limit}` : ""}`),
  getCharter: (companyId) => request(`/companies/${companyId}/charter`),
  getSlo: (companyId) => request(`/companies/${companyId}/slo`),
  getCompanyAgents: (companyId) => request(`/companies/${companyId}/agents`),
  getCompanyPolicy: (companyId) => request(`/companies/${companyId}/policy`),
  listIncidents: (status) =>
    request(`/incidents${status ? `?status=${status}` : ""}`),
  getIncident: (incidentId) => request(`/incidents/${incidentId}`),
  recordDecision: (incidentId, decision, decidedBy, note) =>
    request(`/incidents/${incidentId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, decided_by: decidedBy, note }),
    }),
  getRegistry: (agent) => request(`/registry/${agent}`),
  getMetrics: () => request("/metrics"),
  ask: (question) =>
    request("/ask", { method: "POST", body: JSON.stringify({ question }) }),
};

// Static preview mode — built for GitHub Pages (VITE_STATIC_MODE=true), reading a bundled
// snapshot of one real simulation run instead of hitting a live dashboard/api backend, which
// Pages can't host. The write action and the live-LLM Ask call have no static equivalent by
// design (see CLAUDE.md: the operator console's real write action and OPENAI_API_KEY-backed
// Ask stay local-only) — both reject with a message the existing error-banner UI already
// renders, rather than silently no-oping.
export const STATIC_MODE = import.meta.env.VITE_STATIC_MODE === "true";

const STATIC_PREVIEW_MESSAGE =
  "Not available in this static preview — clone the repo and run the live console locally " +
  "(see README) to use this.";

function buildStaticApi() {
  return {
    listCompanies: () => Promise.resolve(snapshot.companies),
    getTrend: (companyId, limit) => {
      const full = snapshot.trends[companyId] || [];
      return Promise.resolve(limit ? full.slice(-limit) : full);
    },
    getCharter: (companyId) => Promise.resolve(snapshot.charters[companyId]),
    getSlo: (companyId) => Promise.resolve(snapshot.slos[companyId]),
    getCompanyAgents: (companyId) => Promise.resolve(snapshot.agents[companyId] || []),
    getCompanyPolicy: (companyId) => Promise.resolve(snapshot.policies[companyId]),
    listIncidents: (status) =>
      Promise.resolve(status ? snapshot.incidents.filter((i) => i.status === status) : snapshot.incidents),
    getIncident: (incidentId) => {
      const found = snapshot.incidents.find((i) => i.incident_id === incidentId);
      return found ? Promise.resolve(found) : Promise.reject(new Error(`unknown incident_id '${incidentId}'`));
    },
    recordDecision: () => Promise.reject(new Error(STATIC_PREVIEW_MESSAGE)),
    getRegistry: (agent) => Promise.resolve(snapshot.registry[agent]),
    getMetrics: () => Promise.resolve(snapshot.metrics),
    ask: () => Promise.reject(new Error(STATIC_PREVIEW_MESSAGE)),
  };
}

export const api = STATIC_MODE ? buildStaticApi() : liveApi;

export const AGENTS = [
  "goal-drift-tracker",
  "slo-risk-tracker",
  "change-impact-synthesizer",
  "model-boundary-interpreter",
  "portfolio-rollup-writer",
  "policy-compliance-checker",
  "groundedness-checker",
];
