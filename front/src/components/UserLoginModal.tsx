"use client";

import { useEffect, useMemo, useState } from "react";
import { setUserId, setUserRole, setUserToken } from "@/lib/userSession";
import { setAdminToken } from "@/lib/adminSession";

type Props = {
  open: boolean;
  onClose: () => void;
  onLoggedIn?: () => void;
};

type OtpVerifyResponse = {
  ok?: boolean;
  token?: string;
  user_id?: string;
  role?: string;
  is_admin_candidate?: boolean;
  detail?: string;
};

type AdminLoginResponse = {
  ok?: boolean;
  admin_token?: string;
  expires_in_sec?: number;
  detail?: string;
};

function getErrorMessage(e: unknown, fallback: string) {
  if (e instanceof Error) return e.message || fallback;
  return fallback;
}

export function UserLoginModal({ open, onClose, onLoggedIn }: Props) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [otpRequested, setOtpRequested] = useState(false);
  const [adminStage, setAdminStage] = useState<"none" | "offer" | "pin">("none");
  const [adminPassword, setAdminPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const canRequest = useMemo(() => !!phone.trim() && !loading, [phone, loading]);
  const canVerify = useMemo(() => !!phone.trim() && !!code.trim() && !loading, [phone, code, loading]);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setInfo(null);
    // keep inputs as-is to make retries easier
  }, [open]);

  function resetStateAfterClose() {
    setOtpRequested(false);
    setCode("");
    setAdminStage("none");
    setAdminPassword("");
    setInfo(null);
    setError(null);
  }

  if (!open) return null;

  async function requestOtp() {
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const r = await fetch("/api/auth/otp/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phone.trim() }),
      });
      const data = (await r.json()) as { detail?: string };
      if (!r.ok) throw new Error(data?.detail || "Не удалось запросить код");
      setOtpRequested(true);
      setInfo("Код отправлен. Введите его и нажмите «Войти». ");
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Ошибка"));
    } finally {
      setLoading(false);
    }
  }

  async function verifyOtp() {
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const r = await fetch("/api/auth/otp/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phone.trim(), code: code.trim() }),
      });
      const data = (await r.json()) as OtpVerifyResponse;
      if (!r.ok) throw new Error(data?.detail || "Не удалось войти");
      if (!data?.token) throw new Error("Сервер не вернул token");

      setUserToken(String(data.token));
      if (data.user_id) setUserId(String(data.user_id));
      if (data.role) setUserRole(String(data.role));

      const candidate = Boolean(data.is_admin_candidate);
      onLoggedIn?.();

      if (candidate) {
        setAdminStage("offer");
        setInfo(null);
        return;
      }

      resetStateAfterClose();
      onClose();
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Ошибка"));
    } finally {
      setLoading(false);
    }
  }

  async function adminLogin() {
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const userToken = typeof window !== "undefined" ? window.localStorage.getItem("user_token") : null;
      if (!userToken) throw new Error("Нет user token");

      const r = await fetch("/api/admin/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: userToken.toLowerCase().startsWith("bearer ") ? userToken : `Bearer ${userToken}`,
        },
        body: JSON.stringify({ admin_password: adminPassword.trim() }),
      });

      const data = (await r.json()) as AdminLoginResponse;
      if (!r.ok) throw new Error(data?.detail || "Не удалось войти как админ");
      if (!data?.admin_token) throw new Error("Сервер не вернул admin_token");
      const expiresIn = Number(data.expires_in_sec || 0);
      const expiresAtIso = new Date(Date.now() + Math.max(0, expiresIn) * 1000).toISOString();
      setAdminToken(String(data.admin_token), expiresAtIso);

      resetStateAfterClose();
      onClose();
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Ошибка"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        zIndex: 1000,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 420,
          background: "#fff",
          color: "#000",
          border: "1px solid #eee",
          padding: 16,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 700 }}>Вход</div>
          <button onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>

        <div style={{ marginTop: 12 }}>
          <label style={{ display: "block" }}>
            Телефон
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder={"89062592834"}
              style={{ display: "block", width: "100%", marginTop: 6, padding: 8 }}
              autoComplete="tel"
            />
          </label>

          {adminStage === "none" ? (
            <label style={{ display: "block", marginTop: 12 }}>
              Код
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder={"906090"}
                style={{ display: "block", width: "100%", marginTop: 6, padding: 8 }}
                autoComplete="one-time-code"
              />
            </label>
          ) : null}

          {adminStage === "offer" ? (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontWeight: 600 }}>Войти как админ?</div>
              <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  disabled={loading}
                  onClick={() => {
                    resetStateAfterClose();
                    onClose();
                  }}
                >
                  Нет
                </button>
                <button
                  disabled={loading}
                  onClick={() => {
                    setAdminStage("pin");
                  }}
                >
                  Да
                </button>
              </div>
            </div>
          ) : null}

          {adminStage === "pin" ? (
            <div style={{ marginTop: 12 }}>
              <label style={{ display: "block", marginTop: 12 }}>
                PIN
                <input
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                  placeholder={"1573"}
                  style={{ display: "block", width: "100%", marginTop: 6, padding: 8 }}
                  autoComplete="current-password"
                  inputMode="numeric"
                />
              </label>

              <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                <button disabled={loading || !adminPassword.trim()} onClick={adminLogin}>
                  {loading ? "Подождите…" : "Войти как админ"}
                </button>
                <button
                  disabled={loading}
                  onClick={() => {
                    setAdminStage("offer");
                  }}
                >
                  Назад
                </button>
              </div>
            </div>
          ) : null}

          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            {adminStage === "none" ? (
              <>
                <button disabled={!canRequest} onClick={requestOtp}>
                  {loading ? "Подождите…" : "Получить код"}
                </button>
                <button disabled={!canVerify} onClick={verifyOtp}>
                  {loading ? "Подождите…" : "Войти"}
                </button>
                {otpRequested && (
                  <button
                    disabled={loading}
                    onClick={() => {
                      setOtpRequested(false);
                      setInfo(null);
                    }}
                  >
                    Назад
                  </button>
                )}
              </>
            ) : null}
          </div>

          {info && <div style={{ marginTop: 12, color: "#333" }}>{info}</div>}
          {error && <div style={{ marginTop: 12, color: "crimson" }}>{error}</div>}
        </div>
      </div>
    </div>
  );
}
