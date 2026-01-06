import { getAdminToken } from "./adminSession";
import { getUserToken } from "./userSession";

type ApiErrorBody = { detail?: string };

type ApiErrorCodeBody = {
  detail?: string | { code?: string; message?: string };
};

function friendlyAdminError(codeOrDetail?: string): string {
  switch (codeOrDetail) {
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
    case "JOB_NOT_FOUND":
      return "Job не найден";
    case "ALREADY_IN_PROGRESS":
      return "Уже есть queued/rendering для этого pack+doc";
    case "INVALID_STATUS":
      return "Requeue доступен только для failed";
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
    const body = (data || {}) as ApiErrorCodeBody;
    let code: string | undefined;
    let message: string | undefined;
    if (typeof body.detail === "string") {
      code = body.detail;
    } else if (body.detail && typeof body.detail === "object") {
      code = body.detail.code;
      message = body.detail.message;
    }
    const msg = message || friendlyAdminError(code) || "Ошибка";
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

export async function adminAudit(params?: { limit?: number; action?: string; target_type?: string }) {
  const url = new URL("/api/admin/audit", window.location.origin);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  if (params?.action) url.searchParams.set("action", params.action);
  if (params?.target_type) url.searchParams.set("target_type", params.target_type);
  return adminFetch(url.pathname + url.search, { method: "GET" });
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

export async function adminRenderJobsList(params?: {
  status?: string;
  pack_id?: string;
  doc_id?: string;
  limit?: number;
}) {
  const url = new URL("/api/admin/render-jobs", window.location.origin);
  if (params?.status) url.searchParams.set("status", params.status);
  if (params?.pack_id) url.searchParams.set("pack_id", params.pack_id);
  if (params?.doc_id) url.searchParams.set("doc_id", params.doc_id);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  return adminFetch(url.pathname + url.search, { method: "GET" });
}

export async function adminRenderJobDetails(jobId: string) {
  return adminFetch(`/api/admin/render-jobs/${encodeURIComponent(jobId)}`, { method: "GET" });
}

export async function adminRenderJobRequeue(jobId: string) {
  return adminFetch(`/api/admin/render-jobs/${encodeURIComponent(jobId)}/requeue`, { method: "POST" });
}

export async function adminRenderJobsRequeueFailed(limit?: number) {
  const url = new URL("/api/admin/render-jobs/requeue-failed", window.location.origin);
  if (limit) url.searchParams.set("limit", String(limit));
  return adminFetch(url.pathname + url.search, { method: "POST" });
}

export async function adminFileDownloadUrl(fileId: string) {
  return adminFetch(`/api/admin/files/${encodeURIComponent(fileId)}/download`, { method: "GET" });
}
