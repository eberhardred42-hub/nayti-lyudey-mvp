"use client";

import { useEffect, useMemo, useState } from "react";
import {
  adminDocumentUpdateAccess,
  adminDocumentUpdateMetadata,
  adminDocumentsList,
} from "@/lib/adminApi";
import { sendClientEvent } from "@/lib/clientEvents";

type AdminDocItem = {
  doc_id: string;
  title: string;
  description: string | null;
  registry: { title: string; is_enabled: boolean };
  metadata: { title: string | null; description: string | null };
  access: {
    enabled: boolean | null;
    tier: string | null;
    effective: { tier: string; enabled: boolean; is_locked: boolean; reason: string | null };
  };
};

type DraftRow = {
  title: string;
  description: string;
  enabled: boolean;
  tier: "free" | "paid";
};

export default function AdminDocumentsPage() {
  const [items, setItems] = useState<AdminDocItem[]>([]);
  const [drafts, setDrafts] = useState<Record<string, DraftRow>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const sorted = useMemo(() => {
    return [...items].sort((a, b) => (a.doc_id || "").localeCompare(b.doc_id || ""));
  }, [items]);

  function initDrafts(nextItems: AdminDocItem[]) {
    const next: Record<string, DraftRow> = {};
    for (const it of nextItems) {
      const enabled = it.access?.enabled ?? it.registry?.is_enabled ?? true;
      const tierRaw = (it.access?.tier || "free").toLowerCase();
      const tier = tierRaw === "paid" ? "paid" : "free";
      next[it.doc_id] = {
        title: it.title || it.doc_id,
        description: it.description || "",
        enabled,
        tier,
      };
    }
    setDrafts(next);
  }

  async function load() {
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const data = await adminDocumentsList();
      const nextItems = (data?.items || []) as AdminDocItem[];
      setItems(nextItems);
      initDrafts(nextItems);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить документы");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    sendClientEvent("ui_admin_documents_opened");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setDraft(docId: string, patch: Partial<DraftRow>) {
    setDrafts((prev) => ({
      ...prev,
      [docId]: { ...prev[docId], ...patch },
    }));
  }

  async function save(docId: string) {
    const d = drafts[docId];
    if (!d) return;
    setNotice(null);
    setError(null);
    sendClientEvent("ui_admin_document_save_clicked", { doc_id: docId });
    try {
      await adminDocumentUpdateMetadata(docId, {
        title: d.title.trim() ? d.title : null,
        description: d.description.trim() ? d.description : null,
      });
      await adminDocumentUpdateAccess(docId, { enabled: !!d.enabled, tier: d.tier });
      setNotice("Сохранено");
      sendClientEvent("ui_admin_document_save_ok", { doc_id: docId });
      await load();
    } catch (e: any) {
      sendClientEvent("ui_admin_document_save_fail", { doc_id: docId, error: e?.message || "error" });
      setError(e?.message || "Не удалось сохранить");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-xl font-semibold">Documents</h1>
        <button className="border rounded px-3 py-1" onClick={() => load()} disabled={loading}>
          {loading ? "Загрузка…" : "Обновить"}
        </button>
      </div>

      {notice ? <div className="text-sm">{notice}</div> : null}
      {error ? <div className="text-sm text-red-700">{error}</div> : null}

      <div className="overflow-x-auto border rounded">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left p-2">doc_id</th>
              <th className="text-left p-2">title</th>
              <th className="text-left p-2">description</th>
              <th className="text-left p-2">enabled</th>
              <th className="text-left p-2">tier</th>
              <th className="text-left p-2">registry</th>
              <th className="text-left p-2">actions</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td className="p-2" colSpan={7}>
                  {loading ? "Загрузка…" : "Пусто"}
                </td>
              </tr>
            ) : (
              sorted.map((it) => {
                const d = drafts[it.doc_id];
                return (
                  <tr key={it.doc_id} className="border-t align-top">
                    <td className="p-2 whitespace-nowrap">{it.doc_id}</td>
                    <td className="p-2 min-w-[260px]">
                      <input
                        className="border rounded px-2 py-1 w-full"
                        value={d?.title ?? it.title ?? it.doc_id}
                        onChange={(e) => setDraft(it.doc_id, { title: e.target.value })}
                      />
                    </td>
                    <td className="p-2 min-w-[320px]">
                      <textarea
                        className="border rounded px-2 py-1 w-full"
                        rows={2}
                        value={d?.description ?? it.description ?? ""}
                        onChange={(e) => setDraft(it.doc_id, { description: e.target.value })}
                      />
                    </td>
                    <td className="p-2">
                      <label className="inline-flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={!!(d?.enabled ?? (it.access?.enabled ?? it.registry?.is_enabled ?? true))}
                          onChange={(e) => setDraft(it.doc_id, { enabled: e.target.checked })}
                        />
                        <span className="opacity-70">{d?.enabled ? "on" : "off"}</span>
                      </label>
                    </td>
                    <td className="p-2">
                      <select
                        className="border rounded px-2 py-1"
                        value={d?.tier ?? ((it.access?.tier || "free") as any)}
                        onChange={(e) => setDraft(it.doc_id, { tier: (e.target.value as any) || "free" })}
                      >
                        <option value="free">free</option>
                        <option value="paid">paid</option>
                      </select>
                      <div className="text-xs opacity-70 mt-1">
                        eff: {it.access?.effective?.tier}
                        {it.access?.effective?.reason ? ` (${it.access.effective.reason})` : ""}
                      </div>
                    </td>
                    <td className="p-2 text-xs opacity-80">
                      <div>enabled: {String(it.registry?.is_enabled ?? true)}</div>
                      <div title={it.registry?.title || ""} className="max-w-[240px] truncate">
                        title: {it.registry?.title || ""}
                      </div>
                    </td>
                    <td className="p-2">
                      <button className="border rounded px-3 py-1" onClick={() => save(it.doc_id)} disabled={loading}>
                        Save
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
