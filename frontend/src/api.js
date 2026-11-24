// Thin wrapper around the FastAPI backend. It only carries data and error messages:
// every rule is decided by the backend, the screens just show what the backend says.
const BASE = "/api";
let token = sessionStorage.getItem("nc_token") || "";

export const setToken = (t) => {
  token = t || "";
  t ? sessionStorage.setItem("nc_token", t) : sessionStorage.removeItem("nc_token");
};
export const hasToken = () => !!token;

export class ApiError extends Error {
  constructor(message, code, toStaff, status) {
    super(message);
    this.code = code; this.toStaff = toStaff; this.status = status;
  }
}

export async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Cannot reach the clinic server. Is the backend running?", "NETWORK", false, 0);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    if (d && typeof d === "object" && !Array.isArray(d)) throw new ApiError(d.message, d.code, d.to_staff, res.status);
    if (Array.isArray(d)) throw new ApiError("Please check the details you entered.", "VALIDATION", false, res.status);
    throw new ApiError("Something went wrong.", "UNKNOWN", false, res.status);
  }
  return data;
}
