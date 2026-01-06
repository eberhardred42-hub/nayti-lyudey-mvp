const USER_ID_KEY = "nly_user_id";

export function getUserId(): string | null {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(USER_ID_KEY);
  return v ? v : null;
}

export function getOrCreateUserId(): string {
  if (typeof window === "undefined") return "";
  const existing = window.localStorage.getItem(USER_ID_KEY);
  if (existing) return existing;
  const id = crypto.randomUUID();
  window.localStorage.setItem(USER_ID_KEY, id);
  return id;
}
