import type { AuthUser } from "./types";

const STORAGE_KEY = "malomatia-auth";

export function loadStoredAuth(): AuthUser | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    window.sessionStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export function persistAuth(user: AuthUser | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!user) {
    window.sessionStorage.removeItem(STORAGE_KEY);
    return;
  }
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}
