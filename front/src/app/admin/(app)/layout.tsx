"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { PropsWithChildren, useEffect, useMemo, useState } from "react";
import { adminMe } from "@/lib/adminApi";
import { clearAdminToken, getAdminToken, isAdminTokenExpired } from "@/lib/adminSession";
import { sendClientEvent } from "@/lib/clientEvents";

const NAV = [
  { title: "Overview", href: "/admin", page: "overview" },
  { title: "Jobs", href: "/admin/jobs", page: "jobs" },
  { title: "Packs", href: "/admin/packs", page: "packs" },
  { title: "Documents", href: "/admin/documents", page: "documents" },
  { title: "Configs", href: "/admin/configs", page: "configs" },
  { title: "Alerts", href: "/admin/alerts", page: "alerts" },
  { title: "Logs", href: "/admin/logs", page: "logs" },
];

export default function AdminAppLayout({ children }: PropsWithChildren) {
  const router = useRouter();
  const pathname = usePathname();
  const [checking, setChecking] = useState(true);

  const initialHasToken = useMemo(() => (typeof window !== "undefined" ? !!getAdminToken() : false), []);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      setChecking(true);
      try {
        if (!getAdminToken() || isAdminTokenExpired()) {
          clearAdminToken();
          router.replace("/admin/login");
          return;
        }
        await adminMe();
      } catch (e: any) {
        const detail = e?.detail || "";
        if (["expired_admin_token", "invalid_admin_token", "missing_admin_token"].includes(detail)) {
          clearAdminToken();
          router.replace("/admin/login");
          return;
        }
        // other errors: still show shell, but keep message on the page
      } finally {
        if (!cancelled) setChecking(false);
      }
    }
    check();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (checking) {
    return <main style={{ padding: 24 }}>Проверяю сессию…</main>;
  }

  // If we got here without a token, the router.replace should have fired;
  // keep the UI minimal to avoid flashing the admin shell.
  if (!initialHasToken && !getAdminToken()) {
    return null;
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <aside style={{ width: 240, borderRight: "1px solid #eee", padding: 16 }}>
        <div style={{ fontWeight: 700, marginBottom: 12 }}>Admin</div>
        <nav style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => sendClientEvent("ui_admin_nav_clicked", { page: item.page })}
              style={{
                textDecoration: "none",
                color: pathname === item.href ? "black" : "#444",
                fontWeight: pathname === item.href ? 700 : 400,
              }}
            >
              {item.title}
            </Link>
          ))}
        </nav>
      </aside>

      <main style={{ flex: 1, padding: 24 }}>{checking ? <div>Проверяю сессию…</div> : children}</main>
    </div>
  );
}
