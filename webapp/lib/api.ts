import type {
  AuthUser,
  CaseActionResult,
  CaseDetail,
  DashboardSummary,
  LoginResult,
  MfaSetupResult,
  NotificationsResponse,
  PaginatedCases,
  RagResponse,
  RegisterResult,
  ReviewSummary,
  TimelineEvent,
  UsersResponse,
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

export async function login(username: string, password: string): Promise<LoginResult> {
  return apiFetch<LoginResult>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function verifyMfa(pendingToken: string, code: string): Promise<LoginResult> {
  return apiFetch<LoginResult>("/auth/mfa/verify", {
    method: "POST",
    body: JSON.stringify({ pending_token: pendingToken, code }),
  });
}

export async function register(username: string, displayName: string, password: string, enableMfa: boolean): Promise<RegisterResult> {
  return apiFetch<RegisterResult>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, display_name: displayName, password, enable_mfa: enableMfa }),
  });
}

export async function buildAuthUser(tokenValue: string): Promise<AuthUser> {
  const me = await apiFetch<{ user_id: string; display_name: string; role: string; auth_provider: string; status: string; mfa_enabled: boolean }>(
    "/auth/me",
    {},
    tokenValue,
  );
  return {
    accessToken: tokenValue,
    role: me.role,
    userId: me.user_id,
    displayName: me.display_name,
    authProvider: me.auth_provider,
    status: me.status,
    mfaEnabled: me.mfa_enabled,
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

export function approveCase(accessToken: string, caseId: string, reason: string): Promise<CaseActionResult> {
  return apiFetch<CaseActionResult>(
    `/cases/${caseId}/approve`,
    { method: "POST", body: JSON.stringify({ reason }) },
    accessToken,
  );
}

export function assignCase(
  accessToken: string,
  caseId: string,
  assignedTeam: string,
  assignedUser: string,
  reason: string,
): Promise<CaseActionResult> {
  return apiFetch<CaseActionResult>(
    `/cases/${caseId}/assign`,
    {
      method: "POST",
      body: JSON.stringify({
        assigned_team: assignedTeam,
        assigned_user: assignedUser || null,
        reason,
      }),
    },
    accessToken,
  );
}

export function overrideCase(accessToken: string, caseId: string, reason: string): Promise<CaseActionResult> {
  return apiFetch<CaseActionResult>(
    `/cases/${caseId}/override`,
    { method: "POST", body: JSON.stringify({ reason }) },
    accessToken,
  );
}

export function fetchReviewSummary(accessToken: string): Promise<ReviewSummary> {
  return apiFetch<ReviewSummary>("/review/summary", {}, accessToken);
}

export function fetchNotifications(accessToken: string, includeAcked = false): Promise<NotificationsResponse> {
  return apiFetch<NotificationsResponse>(`/notifications?include_acked=${includeAcked ? "true" : "false"}`, {}, accessToken);
}

export function acknowledgeNotification(accessToken: string, notificationId: string): Promise<{ message: string }> {
  return apiFetch<{ message: string }>(`/notifications/${notificationId}/ack`, { method: "POST" }, accessToken);
}

export function fetchUsers(accessToken: string): Promise<UsersResponse> {
  return apiFetch<UsersResponse>("/users", {}, accessToken);
}

export function createUser(
  accessToken: string,
  payload: { user_id: string; display_name: string; password: string; role: string; status: string; enable_mfa: boolean },
): Promise<{ user_id: string }> {
  return apiFetch<{ user_id: string }>("/users", { method: "POST", body: JSON.stringify(payload) }, accessToken);
}

export function updateUser(
  accessToken: string,
  userId: string,
  payload: { display_name?: string; role?: string; status?: string },
): Promise<{ user_id: string }> {
  return apiFetch<{ user_id: string }>(`/users/${userId}`, { method: "PATCH", body: JSON.stringify(payload) }, accessToken);
}

export function resetUserPassword(accessToken: string, userId: string, newPassword: string): Promise<{ message: string }> {
  return apiFetch<{ message: string }>(
    `/users/${userId}/reset-password`,
    { method: "POST", body: JSON.stringify({ new_password: newPassword }) },
    accessToken,
  );
}

export function setupUserMfa(accessToken: string, userId: string): Promise<MfaSetupResult> {
  return apiFetch<MfaSetupResult>(`/users/${userId}/mfa/setup`, { method: "POST" }, accessToken);
}

export function disableUserMfa(accessToken: string, userId: string): Promise<{ message: string }> {
  return apiFetch<{ message: string }>(`/users/${userId}/mfa/disable`, { method: "POST" }, accessToken);
}

export function exportCasesUrl(params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      qs.set(key, String(value));
    }
  });
  return `${API_BASE_URL}/cases/export.csv?${qs.toString()}`;
}

export function exportAuditUrl(): string {
  return `${API_BASE_URL}/audit/export`;
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
