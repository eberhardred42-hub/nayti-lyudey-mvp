"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { adminLogin } from "@/lib/adminApi";
import { clearAdminToken, isAdminTokenExpired, setAdminToken } from "@/lib/adminSession";
import { getOrCreateUserId, getUserId } from "@/lib/userSession";
import { sendClientEvent } from "@/lib/clientEvents";

export default function AdminLoginPage() {
  const router = useRouter();
  const userId = useMemo(() => (typeof window !== "undefined" ? getUserId() : null), []);

  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    sendClientEvent("ui_admin_login_opened");
  }, []);

  useEffect(() => {
    // If there's an expired token sitting around, clear it.
    if (typeof window === "undefined") return;
    if (isAdminTokenExpired()) clearAdminToken();
  }, []);

  async function ensureUser() {
    setError(null);
    getOrCreateUserId();
    router.refresh();
  }

  async function submit() {
    const uid = getUserId();
    if (!uid) return;
    setLoading(true);
    setError(null);
    sendClientEvent("ui_admin_login_submitted");
    try {
      const data = await adminLogin(password, uid);
      setAdminToken(data.admin_token, data.expires_at);
      sendClientEvent("ui_admin_login_ok");
      router.push("/admin");
    } catch (e: any) {
      setError(e?.message || "Ошибка");
      sendClientEvent("ui_admin_login_fail", { error: e?.message || "error" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 520, margin: "0 auto" }}>
      <h1>Админка</h1>

      {!userId ? (
        <section style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 12 }}>Нужна пользовательская сессия.</div>
          <button onClick={ensureUser}>Войти</button>
        </section>
      ) : (
        <section style={{ marginTop: 16 }}>
          <label style={{ display: "block" }}>
            Admin password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ display: "block", width: "100%", marginTop: 6, padding: 8 }}
            />
          </label>
          <button disabled={loading || !password.trim()} onClick={submit} style={{ marginTop: 12 }}>
            {loading ? "Вхожу…" : "Войти в админку"}
          </button>
          {error && <div style={{ color: "crimson", marginTop: 12 }}>{error}</div>}
        </section>
      )}
    </main>
  );
}
