import type {
  TokenResponse, Contact, Message, HealthResponse, ConnectResponse,
} from "./types";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function baseUrl(): string {
  const stored = localStorage.getItem("shadownet_base_url");
  if (stored) return stored;
  return window.location.origin;
}

async function request<T>(path: string, init: RequestInit = {}, skipAuth = false): Promise<T> {
  const base = baseUrl();
  if (!base) throw new Error("Backend URL not configured");

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) || {}),
  };

  if (!skipAuth) {
    const token = localStorage.getItem("shadownet_token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const resp = await fetch(`${base}${path}`, { ...init, headers });

  if (!resp.ok) {
    const body = await resp.text();
    throw new ApiError(resp.status, body);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export const api = {
  checkHealth: (url: string) =>
    fetch(`${url}/health`).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<HealthResponse>;
    }),

  register: (email: string, password: string, name: string) =>
    request<TokenResponse>("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password, name }) }, true),

  login: (email: string, password: string) =>
    request<TokenResponse>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, true),

  listContacts: () => request<Contact[]>("/api/contacts"),
  getContact: (id: string) => request<Contact>(`/api/contacts/${id}`),
  addContact: (data: { identifier: string; name?: string; label?: string; notes?: string; profile?: Record<string, unknown> }) =>
    request<Contact>("/api/contacts", { method: "POST", body: JSON.stringify(data) }),
  updateContact: (id: string, data: Record<string, unknown>) =>
    request<Contact>(`/api/contacts/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteContact: (id: string) =>
    request<void>(`/api/contacts/${id}`, { method: "DELETE" }),
  updateGrant: (id: string, allowed: boolean) =>
    request<Contact>(`/api/contacts/${id}/grant`, { method: "PUT", body: JSON.stringify({ allowed }) }),

  listMessages: (limit = 50, offset = 0) =>
    request<Message[]>(`/api/messages?limit=${limit}&offset=${offset}`),

  mintConnect: (form: "handoff" | "inline" = "handoff") =>
    request<ConnectResponse>(`/api/onboard/connect?form=${form}`, { method: "POST" }),

  getHealth: () => request<HealthResponse>("/health", {}, true),
};
