"use client";

import { useEffect, useMemo, useState } from "react";
import {
  adminConfigDraft,
  adminConfigDryRun,
  adminConfigGet,
  adminConfigKeys,
  adminConfigPublish,
  adminConfigRollback,
  adminConfigUpdate,
  adminConfigValidate,
  adminConfigVersions,
} from "@/lib/adminApi";

type ConfigVersionRow = {
  version: number;
  is_active: boolean;
  validation_status: string;
  validation_errors: any;
  comment?: string | null;
  created_at?: string | null;
};

export default function AdminConfigsPage() {
  const [keys, setKeys] = useState<string[]>([]);
  const [key, setKey] = useState<string>("");

  const [versions, setVersions] = useState<ConfigVersionRow[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  const [text, setText] = useState<string>("{}");
  const [comment, setComment] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [errors, setErrors] = useState<Array<{ code: string; path: string; message: string }>>([]);
  const [isActive, setIsActive] = useState<boolean>(false);

  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedRow = useMemo(
    () => versions.find((v) => v.version === selectedVersion) || null,
    [versions, selectedVersion]
  );

  async function loadKeys() {
    setLoading(true);
    setError(null);
    try {
      const data = await adminConfigKeys();
      const ks = (data?.keys || []) as string[];
      setKeys(ks);
      if (!key && ks.length) setKey(ks[0]);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить keys");
    } finally {
      setLoading(false);
    }
  }

  async function loadVersions(k: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await adminConfigVersions(k);
      const items = (data?.items || []) as ConfigVersionRow[];
      setVersions(items);
      const active = items.find((x) => x.is_active);
      const v = active?.version ?? (items[0]?.version ?? null);
      setSelectedVersion(v);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить versions");
    } finally {
      setLoading(false);
    }
  }

  async function loadVersion(k: string, v: number) {
    setLoading(true);
    setError(null);
    try {
      const data = await adminConfigGet(k, v);
      const item = data?.item;
      if (typeof item?.payload_text === "string") {
        setText(item.payload_text);
      } else {
        setText(JSON.stringify(item?.payload_json ?? {}, null, 2));
      }
      setComment(item?.comment ?? "");
      setStatus(item?.validation_status ?? "");
      setErrors((item?.validation_errors || []) as any);
      setIsActive(Boolean(item?.is_active));
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить версию");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadKeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!key) return;
    loadVersions(key);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    if (!key || selectedVersion == null) return;
    loadVersion(key, selectedVersion);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, selectedVersion]);

  async function doDraft() {
    setNotice(null);
    setError(null);
    try {
      const r = await adminConfigDraft(key);
      await loadVersions(key);
      if (r?.version != null) setSelectedVersion(Number(r.version));
      setNotice("Draft создан");
    } catch (e: any) {
      setError(e?.message || "Draft: ошибка");
    }
  }

  async function doSave() {
    setNotice(null);
    setError(null);
    try {
      const r = await adminConfigUpdate(key, text, comment);
      setNotice("Сохранено");
      await loadVersions(key);
      if (r?.version != null) setSelectedVersion(Number(r.version));
    } catch (e: any) {
      setError(e?.message || "Save: ошибка");
    }
  }

  async function doValidate() {
    if (selectedVersion == null) return;
    setNotice(null);
    setError(null);
    try {
      const r = await adminConfigValidate(key, selectedVersion);
      setStatus(r?.status || "");
      setErrors((r?.errors || []) as any);
      setNotice(`Validate: ${r?.status}`);
      await loadVersions(key);
    } catch (e: any) {
      setError(e?.message || "Validate: ошибка");
    }
  }

  async function doDryRun() {
    if (selectedVersion == null) return;
    setNotice(null);
    setError(null);
    try {
      const r = await adminConfigDryRun(key, selectedVersion);
      if (r?.ok) {
        setNotice(`Dry-run ok: ${r?.pdf_bytes_size} bytes, ${r?.elapsed_ms} ms`);
      } else {
        setNotice(`Dry-run fail: ${r?.error?.message || "ошибка"}`);
      }
    } catch (e: any) {
      setError(e?.message || "Dry-run: ошибка");
    }
  }

  async function doPublish() {
    if (selectedVersion == null) return;
    setNotice(null);
    setError(null);
    try {
      await adminConfigPublish(key, selectedVersion);
      setNotice("Publish: ok");
      await loadVersions(key);
    } catch (e: any) {
      setError(e?.message || "Publish: ошибка");
    }
  }

  async function doRollback() {
    setNotice(null);
    setError(null);
    try {
      const r = await adminConfigRollback(key);
      setNotice(`Rollback: ok (active=${r?.active_version ?? ""})`);
      await loadVersions(key);
    } catch (e: any) {
      setError(e?.message || "Rollback: ошибка");
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Configs</h1>

      <div className="flex flex-wrap gap-2 items-end">
        <label className="flex flex-col gap-1">
          <span className="text-sm opacity-70">key</span>
          <select className="border rounded px-2 py-1" value={key} onChange={(e) => setKey(e.target.value)}>
            {keys.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm opacity-70">version</span>
          <select
            className="border rounded px-2 py-1"
            value={selectedVersion ?? ""}
            onChange={(e) => setSelectedVersion(e.target.value ? Number(e.target.value) : null)}
          >
            {versions.map((v) => (
              <option key={v.version} value={v.version}>
                v{v.version}{v.is_active ? " (active)" : ""} — {v.validation_status}
              </option>
            ))}
          </select>
        </label>

        <button className="border rounded px-3 py-1" onClick={doDraft} disabled={!key || loading}>
          Draft
        </button>
        <button className="border rounded px-3 py-1" onClick={doSave} disabled={!key || loading}>
          Save
        </button>
        <button className="border rounded px-3 py-1" onClick={doValidate} disabled={!key || selectedVersion == null || loading}>
          Validate
        </button>
        <button className="border rounded px-3 py-1" onClick={doDryRun} disabled={!key || selectedVersion == null || loading}>
          Dry-run
        </button>
        <button className="border rounded px-3 py-1" onClick={doPublish} disabled={!key || selectedVersion == null || loading}>
          Publish
        </button>
        <button className="border rounded px-3 py-1" onClick={doRollback} disabled={!key || loading}>
          Rollback
        </button>
      </div>

      <div className="text-sm">
        <span className="opacity-70">status:</span> {status || ""}{" "}
        {isActive ? <span className="ml-2">(active)</span> : null}
        {selectedRow?.created_at ? <span className="ml-2 opacity-70">created_at: {selectedRow.created_at}</span> : null}
      </div>

      {notice ? <div className="text-sm">{notice}</div> : null}
      {error ? <div className="text-sm text-red-700">{error}</div> : null}

      <label className="flex flex-col gap-1">
        <span className="text-sm opacity-70">comment</span>
        <input className="border rounded px-2 py-1" value={comment} onChange={(e) => setComment(e.target.value)} />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-sm opacity-70">payload_json</span>
        <textarea
          className="border rounded p-2 font-mono text-xs min-h-[360px]"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>

      <div>
        <div className="text-sm font-medium">validation_errors</div>
        <pre className="text-xs bg-gray-50 border rounded p-2 overflow-auto max-h-64 whitespace-pre-wrap">
          {JSON.stringify(errors || [], null, 2)}
        </pre>
      </div>
    </div>
  );
}
