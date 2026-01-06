"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { adminLogin } from "@/lib/adminApi";
import { clearAdminToken, isAdminTokenExpired, setAdminToken } from "@/lib/adminSession";
import { getUserToken, setUserToken } from "@/lib/userSession";
import { sendClientEvent } from "@/lib/clientEvents";

export default function AdminLoginPage() {
  const router = useRouter();
  const initialUserToken = useMemo(() => (typeof window !== "undefined" ? getUserToken() : null), []);
  const [userToken, setUserTokenState] = useState<string | null>(initialUserToken);

  const [showUserLogin, setShowUserLogin] = useState(false);
  const [phone, setPhone] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpRequested, setOtpRequested] = useState(false);
  const [otpLoading, setOtpLoading] = useState(false);
  const [otpError, setOtpError] = useState<string | null>(null);

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
    setShowUserLogin(true);
  }

  async function requestOtp() {
    setOtpLoading(true);
    setOtpError(null);
    try {
      const r = await fetch("/api/auth/otp/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phone.trim() }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка запроса кода");
      setOtpRequested(true);
    } catch (e: any) {
      setOtpError(e?.message || "Ошибка");
    } finally {
      setOtpLoading(false);
    }
  }

  async function verifyOtp() {
    setOtpLoading(true);
    setOtpError(null);
    try {
      const r = await fetch("/api/auth/otp/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phone.trim(), code: otpCode.trim() }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Ошибка проверки кода");
      if (!data?.token) throw new Error("Не удалось получить токен");
      setUserToken(String(data.token));
      setUserTokenState(String(data.token));
      setShowUserLogin(false);
      setOtpRequested(false);
      setOtpCode("");
    } catch (e: any) {
      setOtpError(e?.message || "Ошибка");
    } finally {
      setOtpLoading(false);
    }
  }

  async function submit() {
    setLoading(true);
    setError(null);
    sendClientEvent("ui_admin_login_submitted");
    try {
      const data = await adminLogin(password);
      const expiresAtIso = new Date(Date.now() + (data.expires_in_sec || 0) * 1000).toISOString();
      setAdminToken(data.admin_token, expiresAtIso);
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

      {!userToken ? (
        <section style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 12 }}>Нужна пользовательская авторизация.</div>
          <button onClick={ensureUser}>Войти</button>

          {showUserLogin && (
            <div style={{ marginTop: 16, border: "1px solid #eee", padding: 12 }}>
              <div style={{ fontWeight: 700, marginBottom: 8 }}>Вход по SMS</div>

              <label style={{ display: "block" }}>
                Телефон (E.164)
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder={"+79991234567"}
                  style={{ display: "block", width: "100%", marginTop: 6, padding: 8 }}
                />
              </label>

              {!otpRequested ? (
                <button
                  disabled={otpLoading || !phone.trim()}
                  onClick={requestOtp}
                  style={{ marginTop: 12 }}
                >
                  {otpLoading ? "Отправляю…" : "Получить код"}
                </button>
              ) : (
                <>
                  <label style={{ display: "block", marginTop: 12 }}>
                    Код из SMS
                    <input
                      value={otpCode}
                      onChange={(e) => setOtpCode(e.target.value)}
                      style={{ display: "block", width: "100%", marginTop: 6, padding: 8 }}
                    />
                  </label>
                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <button disabled={otpLoading || !otpCode.trim()} onClick={verifyOtp}>
                      {otpLoading ? "Проверяю…" : "Подтвердить"}
                    </button>
                    <button
                      disabled={otpLoading}
                      onClick={() => {
                        setOtpRequested(false);
                        setOtpCode("");
                      }}
                    >
                      Назад
                    </button>
                  </div>
                </>
              )}

              {otpError && <div style={{ color: "crimson", marginTop: 12 }}>{otpError}</div>}
            </div>
          )}
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
