"use client";

import { useEffect, useMemo, useState } from "react";
import { setUserId, setUserRole, setUserToken } from "@/lib/userSession";

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
  detail?: string;
};

export function UserLoginModal({ open, onClose, onLoggedIn }: Props) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [otpRequested, setOtpRequested] = useState(false);
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
      const data = await r.json();
      if (!r.ok) throw new Error(data?.detail || "Не удалось запросить код");
      setOtpRequested(true);
      setInfo("Код отправлен. Введите его и нажмите «Войти». ");
    } catch (e: any) {
      setError(e?.message || "Ошибка");
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
      if (!r.ok) throw new Error((data as any)?.detail || "Не удалось войти");
      if (!data?.token) throw new Error("Сервер не вернул token");

      setUserToken(String(data.token));
      if (data.user_id) setUserId(String(data.user_id));
      if (data.role) setUserRole(String(data.role));

      setOtpRequested(false);
      setCode("");
      setInfo(null);
      onClose();
      onLoggedIn?.();
    } catch (e: any) {
      setError(e?.message || "Ошибка");
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

          <label style={{ display: "block", marginTop: 12 }}>
            Код
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={"1573"}
              style={{ display: "block", width: "100%", marginTop: 6, padding: 8 }}
              autoComplete="one-time-code"
            />
          </label>

          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
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
          </div>

          {info && <div style={{ marginTop: 12, color: "#333" }}>{info}</div>}
          {error && <div style={{ marginTop: 12, color: "crimson" }}>{error}</div>}
        </div>
      </div>
    </div>
  );
}
