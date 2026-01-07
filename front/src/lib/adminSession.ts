const ADMIN_TOKEN_KEY = "admin_token";
const ADMIN_TOKEN_EXPIRES_AT_KEY = "admin_token_expires_at";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(ADMIN_TOKEN_KEY);
  return v ? v : null;
}

export function getAdminTokenExpiresAtIso(): string | null {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(ADMIN_TOKEN_EXPIRES_AT_KEY);
  return v ? v : null;
}

export function isAdminTokenExpired(): boolean {
  const iso = getAdminTokenExpiresAtIso();
  if (!iso) return true;
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return true;
  return Date.now() >= ms;
}

export function setAdminToken(token: string, expiresAtIso: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
  window.localStorage.setItem(ADMIN_TOKEN_EXPIRES_AT_KEY, expiresAtIso);
}

export function clearAdminToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  window.localStorage.removeItem(ADMIN_TOKEN_EXPIRES_AT_KEY);
}
