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

export const api = {
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

export const AGENTS = [
  "goal-drift-tracker",
  "slo-risk-tracker",
  "change-impact-synthesizer",
  "model-boundary-interpreter",
  "portfolio-rollup-writer",
  "policy-compliance-checker",
  "groundedness-checker",
];
