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
    case "UNSUPPORTED_KEY":
      return "Неизвестный ключ конфига";
    case "VERSION_NOT_FOUND":
      return "Версия конфига не найдена";
    case "NO_DRAFT":
      return "Нет черновика (сначала Draft)";
    case "PUBLISH_FORBIDDEN":
      return "Нельзя публиковать: сначала Validate";
    case "NO_ROLLBACK":
      return "Нет предыдущей valid версии для rollback";
    case "DOC_NOT_FOUND":
      return "Документ не найден";
    case "INVALID_TIER":
      return "tier должен быть free или paid";
    case "ALERT_NOT_FOUND":
      return "Алерт не найден";
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

export async function adminOverview() {
  return adminFetch("/api/admin/overview", { method: "GET" });
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

export async function adminConfigKeys() {
  return adminFetch("/api/admin/config/keys", { method: "GET" });
}

export async function adminConfigVersions(key: string) {
  return adminFetch(`/api/admin/config/${encodeURIComponent(key)}/versions`, { method: "GET" });
}

export async function adminConfigGet(key: string, version: number) {
  return adminFetch(`/api/admin/config/${encodeURIComponent(key)}/versions/${encodeURIComponent(String(version))}`, {
    method: "GET",
  });
}

export async function adminConfigDraft(key: string) {
  return adminFetch(`/api/admin/config/${encodeURIComponent(key)}/draft`, { method: "POST" });
}

export async function adminConfigUpdate(key: string, payload_text: string, comment?: string) {
  return adminFetch(`/api/admin/config/${encodeURIComponent(key)}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload_text, comment: comment || null }),
  });
}

export async function adminConfigValidate(key: string, version: number) {
  const url = new URL(`/api/admin/config/${encodeURIComponent(key)}/validate`, window.location.origin);
  url.searchParams.set("version", String(version));
  return adminFetch(url.pathname + url.search, { method: "POST" });
}

export async function adminConfigDryRun(key: string, version: number) {
  const url = new URL(`/api/admin/config/${encodeURIComponent(key)}/dry-run`, window.location.origin);
  url.searchParams.set("version", String(version));
  return adminFetch(url.pathname + url.search, { method: "POST" });
}

export async function adminConfigPublish(key: string, version: number) {
  const url = new URL(`/api/admin/config/${encodeURIComponent(key)}/publish`, window.location.origin);
  url.searchParams.set("version", String(version));
  return adminFetch(url.pathname + url.search, { method: "POST" });
}

export async function adminConfigRollback(key: string) {
  return adminFetch(`/api/admin/config/${encodeURIComponent(key)}/rollback`, { method: "POST" });
}

export async function adminDocumentsList() {
  return adminFetch("/api/admin/documents", { method: "GET" });
}

export async function adminDocumentUpdateMetadata(
  docId: string,
  payload: { title?: string | null; description?: string | null }
) {
  return adminFetch(`/api/admin/documents/${encodeURIComponent(docId)}/metadata`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function adminDocumentUpdateAccess(docId: string, payload: { enabled: boolean; tier: string }) {
  return adminFetch(`/api/admin/documents/${encodeURIComponent(docId)}/access`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function adminAlertsList(params?: { limit?: number; severity?: string; event?: string }) {
  const url = new URL("/api/admin/alerts", window.location.origin);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  if (params?.severity) url.searchParams.set("severity", params.severity);
  if (params?.event) url.searchParams.set("event", params.event);
  return adminFetch(url.pathname + url.search, { method: "GET" });
}

export async function adminAlertAck(alertId: string) {
  return adminFetch(`/api/admin/alerts/${encodeURIComponent(alertId)}/ack`, { method: "POST" });
}

export async function adminLogs(params?: {
  kind?: string;
  pack_id?: string;
  doc_id?: string;
  status?: string;
  limit?: number;
}) {
  const url = new URL("/api/admin/logs", window.location.origin);
  if (params?.kind) url.searchParams.set("kind", params.kind);
  if (params?.pack_id) url.searchParams.set("pack_id", params.pack_id);
  if (params?.doc_id) url.searchParams.set("doc_id", params.doc_id);
  if (params?.status) url.searchParams.set("status", params.status);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  return adminFetch(url.pathname + url.search, { method: "GET" });
}

export async function adminPacksList(params?: { limit?: number; user_id?: string; phone?: string; session_id?: string }) {
  const url = new URL("/api/admin/packs", window.location.origin);
  if (params?.limit != null) url.searchParams.set("limit", String(params.limit));
  if (params?.user_id) url.searchParams.set("user_id", params.user_id);
  if (params?.phone) url.searchParams.set("phone", params.phone);
  if (params?.session_id) url.searchParams.set("session_id", params.session_id);
  return adminFetch(url.pathname + url.search, { method: "GET" });
}

export async function adminPackDocuments(packId: string) {
  return adminFetch(`/api/admin/packs/${encodeURIComponent(packId)}/documents`, { method: "GET" });
}

export async function adminPackRender(packId: string) {
  return adminFetch(`/api/admin/packs/${encodeURIComponent(packId)}/render`, { method: "POST" });
}

export async function adminPackRenderDoc(packId: string, docId: string) {
  return adminFetch(`/api/admin/packs/${encodeURIComponent(packId)}/render/${encodeURIComponent(docId)}`, {
    method: "POST",
  });
}
