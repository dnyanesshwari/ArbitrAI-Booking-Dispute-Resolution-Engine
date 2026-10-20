async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return body;
}

export const getCases = () => request("/cases");
export const getListings = () => request("/listings");
export const getStats = () => request("/stats");
export const createCase = (payload) =>
  request("/cases", { method: "POST", body: JSON.stringify(payload) });
export const getCase = (id) => request(`/cases/${id}`);
export const analyzeCase = (id) => request(`/cases/${id}/analyze`, { method: "POST" });
export const submitDecision = (id, payload) =>
  request(`/cases/${id}/decision`, { method: "POST", body: JSON.stringify(payload) });
export const verifyEvidence = (id, payload) => request(`/cases/${id}/evidence/verify`, { method: "POST", body: JSON.stringify(payload) });
export const getDraftMessages = (id) => request(`/cases/${id}/draft-messages`, { method: "POST" });

export const getCurrentUser = () => request("/auth/me");
export const register = (payload) => request("/auth/register", { method: "POST", body: JSON.stringify(payload) });
export const login = (payload) => request("/auth/login", { method: "POST", body: JSON.stringify(payload) });
export const logout = () => request("/auth/logout", { method: "POST" });
