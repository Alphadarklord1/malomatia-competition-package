import type {
  AuthUser,
  CaseDetail,
  DashboardSummary,
  PaginatedCases,
  RagResponse,
  TimelineEvent,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, init: RequestInit = {}, accessToken?: string): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set("Content-Type", "application/json");
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (data.detail) {
        message = data.detail;
      }
    } catch {
      // ignore parse failure
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const token = await apiFetch<{ access_token: string; role: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  const me = await apiFetch<{ user_id: string; display_name: string; role: string; auth_provider: string }>(
    "/auth/me",
    {},
    token.access_token,
  );
  return {
    accessToken: token.access_token,
    role: me.role,
    userId: me.user_id,
    displayName: me.display_name,
    authProvider: me.auth_provider,
  };
}

export function fetchDashboardSummary(accessToken: string): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/dashboard/summary", {}, accessToken);
}

export function fetchCases(
  accessToken: string,
  params: Record<string, string | number | undefined>,
): Promise<PaginatedCases> {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      qs.set(key, String(value));
    }
  });
  return apiFetch<PaginatedCases>(`/cases?${qs.toString()}`, {}, accessToken);
}

export function fetchCase(accessToken: string, caseId: string): Promise<CaseDetail> {
  return apiFetch<CaseDetail>(`/cases/${caseId}`, {}, accessToken);
}

export function fetchTimeline(accessToken: string, caseId: string): Promise<{ case_id: string; events: TimelineEvent[] }> {
  return apiFetch<{ case_id: string; events: TimelineEvent[] }>(`/cases/${caseId}/timeline`, {}, accessToken);
}

export function approveCase(accessToken: string, caseId: string, reason: string): Promise<{ message: string; case: CaseDetail }> {
  return apiFetch<{ message: string; case: CaseDetail }>(
    `/cases/${caseId}/approve`,
    { method: "POST", body: JSON.stringify({ reason }) },
    accessToken,
  );
}

export function overrideCase(accessToken: string, caseId: string, reason: string): Promise<{ message: string; case: CaseDetail }> {
  return apiFetch<{ message: string; case: CaseDetail }>(
    `/cases/${caseId}/override`,
    { method: "POST", body: JSON.stringify({ reason }) },
    accessToken,
  );
}

export function queryRag(
  accessToken: string,
  query: string,
  top_k = 5,
  department_hint?: string,
): Promise<RagResponse> {
  return apiFetch<RagResponse>(
    "/rag/query",
    {
      method: "POST",
      body: JSON.stringify({ query, language: "en", top_k, department_hint: department_hint || null }),
    },
    accessToken,
  );
}
