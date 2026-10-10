"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { JSX, ReactNode } from "react";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
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
  const router = useRouter();
  const { status: authStatus, email, error: authError, signOut } = useAuth();
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");
  const [signOutError, setSignOutError] = useState<string | null>(null);

  useEffect(() => {
    if (authStatus !== "authenticated") {
      return;
    }
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
  }, [authStatus]);

  useEffect(() => {
    if (authStatus === "unauthenticated" && pathname !== "/sign-in") {
      router.replace("/sign-in");
    }
  }, [authStatus, pathname, router]);

  if (pathname === "/sign-in") {
    return <>{children}</>;
  }

  if (authStatus === "loading") {
    return (
      <main className="auth-state" role="status">
        Checking your ATLAS sign-in session…
      </main>
    );
  }

  if (authStatus === "error") {
    return (
      <main className="auth-state" role="alert">
        <h1>Authentication unavailable</h1>
        <p>{authError}</p>
        <Link className="ghost-button" href="/sign-in">Try signing in</Link>
      </main>
    );
  }

  if (authStatus !== "authenticated") {
    return (
      <main className="auth-state" role="status">
        <p>Sign in to access your ATLAS workspace.</p>
        <Link className="primary-button" href="/sign-in">Sign in</Link>
      </main>
    );
  }

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
            <span className="auth-email">{email}</span>
            <button
              type="button"
              className="ghost-button sign-out-button"
              onClick={() => {
                setSignOutError(null);
                void signOut().catch(() =>
                  setSignOutError("Could not sign out. Please try again."),
                );
              }}
            >
              Sign out
            </button>
          </div>
        </header>

        <main className="page-content">
          {signOutError && <p className="inline-error" role="alert">{signOutError}</p>}
          {children}
        </main>
      </div>
    </div>
  );
}
