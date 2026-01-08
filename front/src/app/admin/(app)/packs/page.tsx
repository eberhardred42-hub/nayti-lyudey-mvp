"use client";

import { useEffect, useMemo, useState } from "react";
import {
  adminFileDownloadUrl,
  adminPackDocuments,
  adminPackRender,
  adminPackRenderDoc,
  adminPacksList,
} from "@/lib/adminApi";
import { sendClientEvent } from "@/lib/clientEvents";

type PackRow = {
  pack_id: string;
  session_id: string;
  user_id?: string | null;
  phone_e164?: string | null;
  created_at?: string | null;
};

type DocRow = {
  doc_id: string;
  title: string;
  status: string;
  file_id?: string | null;
  attempts?: number;
  last_error?: string | null;
  access?: { enabled?: boolean; tier?: string };
};

function errorMessage(e: unknown, fallback: string) {
  if (typeof e === "object" && e !== null && "message" in e) {
    const msg = (e as Record<string, unknown>).message;
    if (typeof msg === "string" && msg.trim()) return msg;
  }
  return fallback;
}

export default function AdminPacksPage() {
  const [phone, setPhone] = useState<string>("");
  const [userId, setUserId] = useState<string>("");
  const [sessionId, setSessionId] = useState<string>("");

  const [items, setItems] = useState<PackRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [selectedPackId, setSelectedPackId] = useState<string>("");
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsError, setDocsError] = useState<string | null>(null);

  const query = useMemo(
    () => ({
      limit: 100,
      phone: phone.trim() || undefined,
      user_id: phone.trim() ? undefined : userId.trim() || undefined,
      session_id: sessionId.trim() || undefined,
    }),
    [phone, userId, sessionId]
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await adminPacksList(query);
      setItems((data?.items || []) as PackRow[]);
    } catch (e: unknown) {
      setError(errorMessage(e, "Не удалось загрузить packs"));
    } finally {
      setLoading(false);
    }
  }

  async function loadDocuments(packId: string) {
    setDocsLoading(true);
    setDocsError(null);
    try {
      const data = await adminPackDocuments(packId);
      setDocs((data?.documents || []) as DocRow[]);
    } catch (e: unknown) {
      setDocsError(errorMessage(e, "Не удалось загрузить документы пака"));
    } finally {
      setDocsLoading(false);
    }
  }

  useEffect(() => {
    sendClientEvent("ui_admin_packs_opened");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openPack(packId: string) {
    setSelectedPackId(packId);
    setNotice(null);
    sendClientEvent("ui_admin_pack_opened", { pack_id: packId });
    await loadDocuments(packId);
  }

  async function renderAll(packId: string) {
    setNotice(null);
    try {
      sendClientEvent("ui_admin_pack_render_clicked", { pack_id: packId });
      const r = await adminPackRender(packId);
      setNotice(`Render: ok (created=${r?.jobs_created ?? ""}, skipped=${r?.jobs_skipped ?? ""})`);
      await loadDocuments(packId);
    } catch (e: unknown) {
      setNotice(errorMessage(e, "Render: ошибка"));
    }
  }

  async function renderDoc(packId: string, docId: string) {
    setNotice(null);
    try {
      sendClientEvent("ui_admin_pack_render_doc_clicked", { pack_id: packId, doc_id: docId });
      const r = await adminPackRenderDoc(packId, docId);
      setNotice(`Render doc: ok (job_id=${r?.job_id ?? ""})`);
      await loadDocuments(packId);
    } catch (e: unknown) {
      setNotice(errorMessage(e, "Render doc: ошибка"));
    }
  }

  async function downloadFile(fileId: string) {
    setNotice(null);
    try {
      const r = await adminFileDownloadUrl(fileId);
      const url = r?.url;
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    } catch (e: unknown) {
      setNotice(errorMessage(e, "Не удалось получить ссылку на файл"));
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Packs</h1>

      <div className="flex flex-wrap gap-2 items-end">
        <label className="flex flex-col gap-1">
          <span className="text-sm opacity-70">phone (E.164 или как вводите в OTP)</span>
          <input
            className="border rounded px-2 py-1"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+79991234567"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm opacity-70">user_id (UUID)</span>
          <input
            className="border rounded px-2 py-1"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="uuid"
            disabled={Boolean(phone.trim())}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm opacity-70">session_id</span>
          <input
            className="border rounded px-2 py-1"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            placeholder="session"
          />
        </label>
        <button className="border rounded px-3 py-1" onClick={() => load()} disabled={loading}>
          {loading ? "Загрузка…" : "Применить"}
        </button>
      </div>

      {notice ? <div className="text-sm">{notice}</div> : null}
      {error ? <div className="text-sm text-red-700">{error}</div> : null}

      <div className="overflow-x-auto border rounded">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left p-2">created_at</th>
              <th className="text-left p-2">pack_id</th>
              <th className="text-left p-2">phone</th>
              <th className="text-left p-2">session_id</th>
              <th className="text-left p-2">actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td className="p-2" colSpan={5}>
                  Пусто
                </td>
              </tr>
            ) : (
              items.map((p) => (
                <tr key={p.pack_id} className="border-t">
                  <td className="p-2">{p.created_at || ""}</td>
                  <td className="p-2">
                    <div className="break-all">{p.pack_id}</div>
                  </td>
                  <td className="p-2">
                    <div>{p.phone_e164 || ""}</div>
                    {!p.phone_e164 && p.user_id ? <div className="opacity-60 break-all">{p.user_id}</div> : null}
                  </td>
                  <td className="p-2">
                    <div className="break-all">{p.session_id}</div>
                  </td>
                  <td className="p-2 flex gap-2">
                    <button className="border rounded px-2 py-1" onClick={() => openPack(p.pack_id)}>
                      Documents
                    </button>
                    <button className="border rounded px-2 py-1" onClick={() => renderAll(p.pack_id)}>
                      Render all
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selectedPackId ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Pack documents</h2>
            <div className="text-sm opacity-70 break-all">{selectedPackId}</div>
          </div>

          {docsLoading ? <div>Загрузка…</div> : null}
          {docsError ? <div className="text-sm text-red-700">{docsError}</div> : null}

          <div className="overflow-x-auto border rounded">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left p-2">status</th>
                  <th className="text-left p-2">doc_id</th>
                  <th className="text-left p-2">title</th>
                  <th className="text-left p-2">attempts</th>
                  <th className="text-left p-2">file_id</th>
                  <th className="text-left p-2">actions</th>
                </tr>
              </thead>
              <tbody>
                {docs.length === 0 ? (
                  <tr>
                    <td className="p-2" colSpan={6}>
                      Пусто
                    </td>
                  </tr>
                ) : (
                  docs.map((d) => (
                    <tr key={d.doc_id} className="border-t">
                      <td className="p-2">{d.status}</td>
                      <td className="p-2">{d.doc_id}</td>
                      <td className="p-2">{d.title}</td>
                      <td className="p-2">{d.attempts ?? 0}</td>
                      <td className="p-2">
                        <div className="break-all">{d.file_id || ""}</div>
                        {d.last_error ? (
                          <div className="text-xs text-red-700 mt-1 break-words">{d.last_error}</div>
                        ) : null}
                      </td>
                      <td className="p-2 flex gap-2">
                        <button
                          className="border rounded px-2 py-1"
                          onClick={() => renderDoc(selectedPackId, d.doc_id)}
                        >
                          Render
                        </button>
                        {d.status === "ready" && d.file_id ? (
                          <button className="border rounded px-2 py-1" onClick={() => downloadFile(d.file_id!)}>
                            Download
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
