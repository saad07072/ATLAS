"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { JSX, ReactNode } from "react";
import { useEffect, useState } from "react";

import { ActivityIndicator } from "@/components/ui/activity-indicator";
import { getHealth } from "@/services/api";

const navigation = [
  { href: "/", label: "Home" },
  { href: "/activity", label: "Activity" },
  { href: "/memory", label: "Memory" },
  { href: "/connected-services", label: "Connected Services" },
  { href: "/settings", label: "Settings" },
];

export function AppShell({ children }: { children: ReactNode }): JSX.Element {
  const pathname = usePathname();
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");

  useEffect(() => {
    let isCurrent = true;

    async function checkHealth(): Promise<void> {
      try {
        await getHealth();
        if (isCurrent) {
          setBackendStatus("online");
        }
      } catch {
        if (isCurrent) {
          setBackendStatus("offline");
        }
      }
    }

    void checkHealth();

    return () => {
      isCurrent = false;
    };
  }, []);

  const indicatorState =
    backendStatus === "online"
      ? "success"
      : backendStatus === "offline"
        ? "error"
        : "processing";

  const healthLabel =
    backendStatus === "online"
      ? "Backend online"
      : backendStatus === "offline"
        ? "Backend offline"
        : "Checking backend...";

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Sidebar navigation">
        <div className="sidebar-brand">
          <div className="brand-mark">A</div>
          <div>
            <strong>ATLAS</strong>
            <span>Foundation</span>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Main navigation">
          {navigation.map((item) => {
            const isActive = pathname === item.href;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-link${isActive ? " active" : ""}`}
                aria-current={isActive ? "page" : undefined}
              >
                <span className="nav-dot" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="shell-body">
        <header className="topbar" aria-label="Application header">
          <div>
            <p className="eyebrow">Autonomous task system</p>
            <h1>ATLAS</h1>
          </div>

          <div className="topbar-actions">
            <ActivityIndicator state={indicatorState} label={healthLabel} />
          </div>
        </header>

        <main className="page-content">{children}</main>
      </div>
    </div>
  );
}
