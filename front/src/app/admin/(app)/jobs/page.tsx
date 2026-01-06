"use client";

import { useEffect, useMemo, useState } from "react";
import {
  adminFileDownloadUrl,
  adminRenderJobDetails,
  adminRenderJobRequeue,
  adminRenderJobsList,
} from "@/lib/adminApi";
import { sendClientEvent } from "@/lib/clientEvents";

type RenderJobRow = {
  id: string;
  pack_id: string;
  doc_id: string;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type JobDetails = {
  ok: boolean;
  job: RenderJobRow;
  artifacts: Array<{
    artifact_id: string;
    kind?: string | null;
    format?: string | null;
    created_at?: string | null;
    file_id?: string | null;
    content_type?: string | null;
    size_bytes?: number | null;
  }>;
  latest_file_id?: string | null;
};

export default function AdminJobsPage() {
  const [status, setStatus] = useState<string>("");
  const [packId, setPackId] = useState<string>("");
  const [docId, setDocId] = useState<string>("");

  const [items, setItems] = useState<RenderJobRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [details, setDetails] = useState<JobDetails | null>(null);

  const query = useMemo(
    () => ({
      status: status.trim() || undefined,
      pack_id: packId.trim() || undefined,
      doc_id: docId.trim() || undefined,
      limit: 100,
    }),
    [status, packId, docId]
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await adminRenderJobsList(query);
      setItems((data?.items || []) as RenderJobRow[]);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить jobs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    sendClientEvent("ui_admin_jobs_opened");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openDetails(jobId: string) {
    setDetailsOpen(true);
    setDetailsLoading(true);
    setDetailsError(null);
    setDetails(null);
    sendClientEvent("ui_admin_job_details_opened", { job_id: jobId });
    try {
      const d = (await adminRenderJobDetails(jobId)) as JobDetails;
      setDetails(d);
    } catch (e: any) {
      setDetailsError(e?.message || "Не удалось загрузить детали job");
    } finally {
      setDetailsLoading(false);
    }
  }

  async function requeue(jobId: string) {
    setNotice(null);
    sendClientEvent("ui_admin_job_requeue_clicked", { job_id: jobId });
    try {
      await adminRenderJobRequeue(jobId);
      sendClientEvent("ui_admin_job_requeue_ok", { job_id: jobId });
      setNotice("Requeue: ok");
      await load();
    } catch (e: any) {
      sendClientEvent("ui_admin_job_requeue_fail", { job_id: jobId, error: e?.message || "error" });
      setNotice(e?.message || "Requeue: fail");
    }
  }

  async function downloadFile(fileId: string) {
    try {
      const r = await adminFileDownloadUrl(fileId);
      const url = r?.url;
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    } catch (e: any) {
      setNotice(e?.message || "Не удалось получить ссылку на файл");
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Render jobs</h1>

      <div className="flex flex-wrap gap-2 items-end">
        <label className="flex flex-col gap-1">
          <span className="text-sm opacity-70">status</span>
          <select
            className="border rounded px-2 py-1"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">(любой)</option>
            <option value="queued">queued</option>
            <option value="rendering">rendering</option>
            <option value="ready">ready</option>
            <option value="failed">failed</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm opacity-70">pack_id</span>
          <input
            className="border rounded px-2 py-1"
            value={packId}
            onChange={(e) => setPackId(e.target.value)}
            placeholder="UUID"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm opacity-70">doc_id</span>
          <input
            className="border rounded px-2 py-1"
            value={docId}
            onChange={(e) => setDocId(e.target.value)}
            placeholder="example: free_report"
          />
        </label>
        <button
          className="border rounded px-3 py-1"
          onClick={() => load()}
          disabled={loading}
        >
          {loading ? "Загрузка…" : "Применить"}
        </button>
      </div>

      {notice ? <div className="text-sm">{notice}</div> : null}
      {error ? <div className="text-sm text-red-700">{error}</div> : null}

      <div className="overflow-x-auto border rounded">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left p-2">status</th>
              <th className="text-left p-2">doc_id</th>
              <th className="text-left p-2">attempts</th>
              <th className="text-left p-2">last_error</th>
              <th className="text-left p-2">updated_at</th>
              <th className="text-left p-2">actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td className="p-2" colSpan={6}>
                  Пусто
                </td>
              </tr>
            ) : (
              items.map((j) => (
                <tr key={j.id} className="border-t">
                  <td className="p-2">{j.status}</td>
                  <td className="p-2">{j.doc_id}</td>
                  <td className="p-2">
                    {j.attempts}/{j.max_attempts}
                  </td>
                  <td className="p-2 max-w-[520px] truncate" title={j.last_error || ""}>
                    {j.last_error || ""}
                  </td>
                  <td className="p-2">{j.updated_at || ""}</td>
                  <td className="p-2 flex gap-2">
                    <button className="border rounded px-2 py-1" onClick={() => openDetails(j.id)}>
                      Details
                    </button>
                    {j.status === "failed" ? (
                      <button className="border rounded px-2 py-1" onClick={() => requeue(j.id)}>
                        Requeue
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {detailsOpen ? (
        <div className="fixed inset-0 bg-black/30 flex items-start justify-center p-6" onClick={() => setDetailsOpen(false)}>
          <div className="bg-white rounded shadow max-w-3xl w-full p-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Job details</h2>
              <button className="border rounded px-2 py-1" onClick={() => setDetailsOpen(false)}>
                Close
              </button>
            </div>

            {detailsLoading ? <div className="mt-3">Загрузка…</div> : null}
            {detailsError ? <div className="mt-3 text-red-700 text-sm">{detailsError}</div> : null}

            {details?.job ? (
              <div className="mt-3 space-y-3">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <div className="opacity-70">job_id</div>
                    <div className="break-all">{details.job.id}</div>
                  </div>
                  <div>
                    <div className="opacity-70">status</div>
                    <div>{details.job.status}</div>
                  </div>
                  <div>
                    <div className="opacity-70">pack_id</div>
                    <div className="break-all">{details.job.pack_id}</div>
                  </div>
                  <div>
                    <div className="opacity-70">doc_id</div>
                    <div>{details.job.doc_id}</div>
                  </div>
                  <div>
                    <div className="opacity-70">attempts</div>
                    <div>
                      {details.job.attempts}/{details.job.max_attempts}
                    </div>
                  </div>
                  <div>
                    <div className="opacity-70">updated_at</div>
                    <div>{details.job.updated_at || ""}</div>
                  </div>
                </div>

                <div>
                  <div className="text-sm opacity-70">last_error</div>
                  <pre className="text-xs bg-gray-50 border rounded p-2 overflow-auto max-h-40 whitespace-pre-wrap">
                    {details.job.last_error || ""}
                  </pre>
                </div>

                <div>
                  <div className="text-sm font-medium">Artifacts</div>
                  <div className="overflow-x-auto border rounded mt-2">
                    <table className="min-w-full text-sm">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="text-left p-2">kind</th>
                          <th className="text-left p-2">artifact_id</th>
                          <th className="text-left p-2">file_id</th>
                          <th className="text-left p-2">actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(details.artifacts || []).length === 0 ? (
                          <tr>
                            <td className="p-2" colSpan={4}>
                              Нет артефактов
                            </td>
                          </tr>
                        ) : (
                          (details.artifacts || []).map((a) => (
                            <tr key={`${a.artifact_id}:${a.file_id || "nofile"}`} className="border-t">
                              <td className="p-2">{a.kind || ""}</td>
                              <td className="p-2 break-all">{a.artifact_id}</td>
                              <td className="p-2 break-all">{a.file_id || ""}</td>
                              <td className="p-2">
                                {a.file_id ? (
                                  <button className="border rounded px-2 py-1" onClick={() => downloadFile(a.file_id!)}>
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
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
