const USER_ID_KEY = "nly_user_id";
const USER_ROLE_KEY = "nly_user_role";
const USER_TOKEN_KEY = "user_token";

function notifyAuthChanged() {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(new Event("nly-auth-changed"));
  } catch {
    // ignore
  }
}

export function getUserId(): string | null {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(USER_ID_KEY);
  return v ? v : null;
}

export function setUserId(userId: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(USER_ID_KEY, userId);
  notifyAuthChanged();
}

export function clearUserId() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(USER_ID_KEY);
  notifyAuthChanged();
}

export function getOrCreateUserId(): string {
  if (typeof window === "undefined") return "";
  const existing = window.localStorage.getItem(USER_ID_KEY);
  if (existing) return existing;
  const id = crypto.randomUUID();
  window.localStorage.setItem(USER_ID_KEY, id);
  return id;
}

export function getUserToken(): string | null {
  if (typeof window === "undefined") return null;
  // tolerate different keys (future-proof)
  const v = window.localStorage.getItem(USER_TOKEN_KEY) || window.localStorage.getItem("token");
  return v ? v : null;
}

export function setUserToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(USER_TOKEN_KEY, token);
  notifyAuthChanged();
}

export function clearUserToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(USER_TOKEN_KEY);
  notifyAuthChanged();
}

export function getUserRole(): string | null {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(USER_ROLE_KEY);
  return v ? v : null;
}

export function setUserRole(role: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(USER_ROLE_KEY, role);
  notifyAuthChanged();
}

export function clearUserRole() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(USER_ROLE_KEY);
  notifyAuthChanged();
}

export function clearUserSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(USER_TOKEN_KEY);
  window.localStorage.removeItem("token");
  window.localStorage.removeItem(USER_ROLE_KEY);
  // NOTE: keep USER_ID_KEY? spec wants logout to clean localStorage.
  window.localStorage.removeItem(USER_ID_KEY);
  notifyAuthChanged();
}

