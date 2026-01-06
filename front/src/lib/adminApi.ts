import { getAdminToken } from "./adminSession";
import { getUserToken } from "./userSession";

type ApiErrorBody = { detail?: string };

function friendlyAdminError(detail?: string): string {
  switch (detail) {
    case "admin_login_disabled":
      return "Админка отключена на сервере";
    case "password_required":
      return "Введите пароль";
    case "invalid_password":
      return "Неверный пароль";
    case "not_allowed":
      return "Этот номер телефона не в allowlist";
    case "missing_admin_token":
      return "Нужна админ-сессия";
    case "invalid_admin_token":
      return "Админ-сессия недействительна";
    case "expired_admin_token":
      return "Админ-сессия истекла";
    default:
      return "Ошибка админки";
  }
}

export async function adminFetch(path: string, init?: RequestInit) {
  const token = getAdminToken();
  const headers = new Headers(init?.headers || undefined);
  if (token) headers.set("X-Admin-Token", token);
  const r = await fetch(path, { ...init, headers });
  let data: any = null;
  try {
    data = await r.json();
  } catch {
    // ignore
  }
  if (!r.ok) {
    const body = (data || {}) as ApiErrorBody;
    const msg = friendlyAdminError(body.detail) || "Ошибка";
    const err: any = new Error(msg);
    err.status = r.status;
    err.detail = body.detail;
    throw err;
  }
  return data;
}

export async function adminMe() {
  return adminFetch("/api/admin/me", { method: "GET" });
}

export async function adminLogin(password: string) {
  const userToken = getUserToken();
  if (!userToken) {
    const err: any = new Error("Сначала войдите как пользователь");
    err.detail = "Unauthorized";
    throw err;
  }
  const r = await fetch("/api/admin/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: userToken.toLowerCase().startsWith("bearer ") ? userToken : `Bearer ${userToken}`,
    },
    body: JSON.stringify({ admin_password: password }),
  });
  const data = await r.json();
  if (!r.ok) {
    const msg = friendlyAdminError(data?.detail);
    const err: any = new Error(msg);
    err.status = r.status;
    err.detail = data?.detail;
    throw err;
  }
  return data as { ok: boolean; admin_token: string; expires_in_sec: number };
}
