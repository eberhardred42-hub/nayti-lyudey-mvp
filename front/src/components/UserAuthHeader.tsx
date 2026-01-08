"use client";

import { useEffect, useMemo, useState } from "react";
import { clearUserSession, getUserRole, getUserToken } from "@/lib/userSession";
import { UserLoginModal } from "@/components/UserLoginModal";

type Props = {
  title?: string;
};

export function UserAuthHeader({ title }: Props) {
  const initialToken = useMemo(() => (typeof window !== "undefined" ? getUserToken() : null), []);
  const [token, setToken] = useState<string | null>(initialToken);
  const [role, setRole] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => {
      setToken(getUserToken());
      setRole(getUserRole());
    };
    sync();
    window.addEventListener("storage", sync);
    window.addEventListener("nly-auth-changed", sync as any);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("nly-auth-changed", sync as any);
    };
  }, []);

  const isLoggedIn = !!token;

  return (
    <>
      <header
        style={{
          width: "100%",
          borderBottom: "1px solid #ddd",
          padding: "12px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          background: "#fff",
          color: "#000",
        }}
      >
        <div style={{ fontWeight: 700 }}>{title || ""}</div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {isLoggedIn ? (
            <>
              <div style={{ fontSize: 12, color: "#333" }}>{role ? role : "Вы вошли"}</div>
              <button
                onClick={() => {
                  clearUserSession();
                  setToken(null);
                  setRole(null);
                }}
              >
                Выйти
              </button>
            </>
          ) : (
            <button onClick={() => setOpen(true)}>Войти</button>
          )}
        </div>
      </header>

      <UserLoginModal
        open={open}
        onClose={() => setOpen(false)}
        onLoggedIn={() => {
          setToken(getUserToken());
          setRole(getUserRole());
        }}
      />
    </>
  );
}
