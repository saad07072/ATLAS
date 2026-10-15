"use client";

import Link from "next/link";
import type { JSX } from "react";
import { useCallback, useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/chat-panel";
import { getDashboardSummary } from "@/services/api";
import type { DashboardResponse } from "@/types";

export default function HomePage(): JSX.Element {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchDashboard = useCallback(async (isManualRefresh = false): Promise<void> => {
    if (isManualRefresh) {
      setIsRefreshing(true);
    }
    setErrorMessage(null);
    try {
      const res = await getDashboardSummary();
      setData(res);
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Failed to load operational dashboard data. Please check your connection or sign in.",
      );
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let isCurrent = true;
    async function init(): Promise<void> {
      try {
        const res = await getDashboardSummary();
        if (isCurrent) {
          setData(res);
        }
      } catch (err) {
        if (isCurrent) {
          setErrorMessage(
            err instanceof Error
              ? err.message
              : "Unable to retrieve dashboard information right now.",
          );
        }
      } finally {
        if (isCurrent) {
          setIsLoading(false);
        }
      }
    }
    void init();
    return () => {
      isCurrent = false;
    };
  }, []);

  const formatEventName = (eventType: string): { label: string; chipClass: string } => {
    switch (eventType) {
      case "workflow_started":
        return { label: "Workflow Started", chipClass: "start" };
      case "step_started":
        return { label: "Step Started", chipClass: "start" };
      case "step_completed":
        return { label: "Step Succeeded", chipClass: "success" };
      case "workflow_completed":
        return { label: "Workflow Completed", chipClass: "success" };
      case "confirmation_required":
        return { label: "Approval Required", chipClass: "warning" };
      case "confirmation_approved":
        return { label: "Approved", chipClass: "success" };
      case "confirmation_rejected":
        return { label: "Rejected", chipClass: "danger" };
      case "step_failed":
      case "workflow_failed":
        return { label: "Failed", chipClass: "danger" };
      case "step_skipped":
        return { label: "Skipped", chipClass: "warning" };
      case "workflow_partially_completed":
        return { label: "Partial Success", chipClass: "warning" };
      case "workflow_paused":
        return { label: "Paused", chipClass: "warning" };
      default:
        return { label: eventType.replace(/_/g, " "), chipClass: "start" };
    }
  };

  return (
    <div className="page-shell">
      {/* Hero / Header */}
      <section className="hero-panel">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.35rem" }}>
            <span className="eyebrow" style={{ margin: 0 }}>Operations Overview</span>
            {data?.system_status && (
              <span
                style={{
                  fontSize: "0.7rem",
                  padding: "0.15rem 0.5rem",
                  borderRadius: "999px",
                  background: "rgba(47, 143, 99, 0.12)",
                  color: "var(--success)",
                  fontWeight: 600,
                  border: "1px solid rgba(47, 143, 99, 0.25)",
                }}
              >
                ● System Live
              </span>
            )}
          </div>
          <h2>ATLAS Autonomous Operations</h2>
        </div>
        <div className="hero-actions" style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          <button
            type="button"
            className="ghost-button"
            onClick={() => void fetchDashboard(true)}
            disabled={isRefreshing || isLoading}
            title="Refresh operational data in-place"
          >
            {isRefreshing ? "Refreshing..." : "↻ Refresh"}
          </button>
          <Link href="/workflows" className="primary-button" style={{ textDecoration: "none" }}>
            Workflows &rarr;
          </Link>
          <Link href="/activity" className="ghost-button" style={{ textDecoration: "none" }}>
            Activity Log
          </Link>
        </div>
      </section>

      {/* Recoverable Error Banner */}
      {errorMessage && (
        <div
          role="alert"
          style={{
            padding: "1rem 1.25rem",
            marginBottom: "1.5rem",
            borderRadius: "var(--radius)",
            background: "rgba(201, 77, 77, 0.08)",
            border: "1px solid rgba(201, 77, 77, 0.25)",
            color: "var(--danger)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <strong>Operational Error:</strong> {errorMessage}
          </div>
          <button
            type="button"
            className="secondary-button"
            style={{ padding: "0.35rem 0.75rem", fontSize: "0.8rem" }}
            onClick={() => void fetchDashboard(true)}
          >
            Retry
          </button>
        </div>
      )}

      {/* Pending Approvals Alert Banner */}
      {data && data.pending_approvals.length > 0 && (
        <section className="approval-alert" aria-label="Action required on pending approvals">
          <div className="approval-alert-text">
            <span className="approval-alert-icon">⚠️</span>
            <div>
              <strong>
                {data.pending_approvals.length} Workflow{data.pending_approvals.length > 1 ? "s" : ""} Awaiting Authorization
              </strong>
              <p>
                Sensitive operations require explicit confirmation before execution continues.
              </p>
            </div>
          </div>
          <Link href="/workflows" className="primary-button" style={{ textDecoration: "none" }}>
            Review Pending &rarr;
          </Link>
        </section>
      )}

      {/* Operational Metrics Cards */}
      <section className="dashboard-grid" aria-label="Key operational metrics">
        <article className="stat-card">
          <span>Active Tasks</span>
          <strong>{isLoading ? "—" : (data?.workflow_counts.running ?? 0)}</strong>
          <small style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            {data?.workflow_counts.running ? "Executing in engine" : "No workflows in-flight"}
          </small>
        </article>

        <article className="stat-card">
          <span>Needs Authorization</span>
          <strong style={{ color: (data?.workflow_counts.waiting_for_confirmation ?? 0) > 0 ? "var(--warning)" : "inherit" }}>
            {isLoading ? "—" : (data?.workflow_counts.waiting_for_confirmation ?? 0)}
          </strong>
          <small style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            {data?.workflow_counts.waiting_for_confirmation ? "Manual sign-off required" : "All gates cleared"}
          </small>
        </article>

        <article className="stat-card">
          <span>Completed</span>
          <strong>
            {isLoading
              ? "—"
              : ((data?.workflow_counts.completed ?? 0) + (data?.workflow_counts.partially_completed ?? 0))}
          </strong>
          <small style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            {data?.workflow_counts.partially_completed ? `${data.workflow_counts.partially_completed} partial completion` : "Fully verified"}
          </small>
        </article>

        <article className="stat-card">
          <span>Failed / Cancelled</span>
          <strong>
            {isLoading
              ? "—"
              : ((data?.workflow_counts.failed ?? 0) + (data?.workflow_counts.cancelled ?? 0))}
          </strong>
          <small style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            Total errors logged
          </small>
        </article>
      </section>

      {/* Split Dashboard Content */}
      <div className="dashboard-split">
        {/* Left Column: Operations & Live Workflows */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {/* Running Workflows Card */}
          <section className="setting-card">
            <div className="setting-card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <h3 style={{ margin: 0 }}>Running Workflows</h3>
                <p style={{ margin: "0.15rem 0 0 0" }}>Active pipelines currently processing steps</p>
              </div>
              <Link href="/workflows" style={{ fontSize: "0.85rem", color: "var(--primary)" }}>
                View all &rarr;
              </Link>
            </div>

            {isLoading ? (
              <div style={{ padding: "1.5rem 0", color: "var(--muted)", textAlign: "center" }}>
                Loading running pipelines...
              </div>
            ) : !data || data.running_workflows.length === 0 ? (
              <div style={{ padding: "1.5rem", textAlign: "center", background: "var(--panel-alt)", borderRadius: "8px" }}>
                <p style={{ margin: 0, color: "var(--muted)", fontSize: "0.85rem" }}>
                  No workflows currently running.
                </p>
                <Link
                  href="/workflows"
                  className="secondary-button"
                  style={{ display: "inline-block", marginTop: "0.6rem", fontSize: "0.8rem", textDecoration: "none" }}
                >
                  Create or Start Workflow
                </Link>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: "0.75rem" }}>
                {data.running_workflows.map((wf) => {
                  const progressPct = wf.step_count > 0 ? Math.round((wf.completed_step_count / wf.step_count) * 100) : 0;
                  return (
                    <div
                      key={wf.id}
                      style={{
                        padding: "0.85rem 1rem",
                        background: "var(--panel-alt)",
                        borderRadius: "8px",
                        border: "1px solid var(--border)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <strong>{wf.title}</strong>
                        <span className="status-badge running" style={{ fontSize: "0.7rem" }}>
                          Running
                        </span>
                      </div>
                      <p style={{ margin: "0.25rem 0 0 0", fontSize: "0.8rem", color: "var(--muted)" }}>
                        {wf.user_request}
                      </p>
                      <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${progressPct}%` }} />
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.35rem", fontSize: "0.75rem", color: "var(--muted)" }}>
                        <span>Progress: {wf.completed_step_count} of {wf.step_count} steps</span>
                        <Link href="/workflows" style={{ color: "var(--primary)" }}>Inspect &rarr;</Link>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* Recent Chronological Activity */}
          <section className="setting-card">
            <div className="setting-card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <h3 style={{ margin: 0 }}>Recent Activity</h3>
                <p style={{ margin: "0.15rem 0 0 0" }}>Chronological operational events and execution audit</p>
              </div>
              <Link href="/activity" style={{ fontSize: "0.85rem", color: "var(--primary)" }}>
                Full Log &rarr;
              </Link>
            </div>

            {isLoading ? (
              <div style={{ padding: "1.5rem 0", color: "var(--muted)", textAlign: "center" }}>
                Loading activity events...
              </div>
            ) : !data || data.recent_activity.length === 0 ? (
              <div style={{ padding: "1.5rem", textAlign: "center", background: "var(--panel-alt)", borderRadius: "8px" }}>
                <p style={{ margin: 0, color: "var(--muted)", fontSize: "0.85rem" }}>
                  No operational events recorded yet. Run a workflow or chat task to generate history.
                </p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {data.recent_activity.slice(0, 6).map((ev) => {
                  const { label, chipClass } = formatEventName(ev.event_type);
                  return (
                    <div key={ev.id} className="activity-event-row">
                      <div style={{ flexShrink: 0, width: "120px" }}>
                        <span className={`activity-chip ${chipClass}`}>{label}</span>
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                          <span style={{ fontWeight: 600, fontSize: "0.85rem" }}>
                            {ev.workflow_title ?? "Workflow Task"}
                          </span>
                          <time style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                            {new Date(ev.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </time>
                        </div>
                        {ev.step_id && (
                          <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.1rem" }}>
                            Step: <code>{ev.step_id}</code>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* Connected Integrations Card */}
          <section className="setting-card">
            <div className="setting-card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <h3 style={{ margin: 0 }}>Connected Integrations</h3>
                <p style={{ margin: "0.15rem 0 0 0" }}>External service authentication and runtime isolation</p>
              </div>
              <Link href="/connected-services" style={{ fontSize: "0.85rem", color: "var(--primary)" }}>
                Manage &rarr;
              </Link>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginTop: "0.75rem" }}>
              {data?.connected_services.map((svc) => (
                <div key={svc.id} className="service-card-item">
                  <div className="service-meta">
                    <h4>{svc.name}</h4>
                    <p>{svc.description}</p>
                    <small style={{ color: "var(--muted)", fontSize: "0.7rem", display: "block", marginTop: "0.15rem" }}>
                      🔒 Tool actions disabled (Phase 12A security boundary)
                    </small>
                  </div>
                  <span
                    className={`status-badge ${svc.status.toLowerCase()}`}
                    style={{ fontSize: "0.75rem" }}
                  >
                    {svc.status}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* Right Column: Assistant & Recent Conversations */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {/* Quick Assistant Chat */}
          <section className="setting-card" style={{ padding: "1.25rem" }}>
            <div style={{ marginBottom: "1rem" }}>
              <h3 style={{ margin: 0 }}>AI Assistant</h3>
              <p style={{ margin: "0.2rem 0 0 0", fontSize: "0.85rem", color: "var(--muted)" }}>
                Direct conversational interaction with grounded tools
              </p>
            </div>
            <ChatPanel />
          </section>

          {/* Recent Conversations */}
          <section className="setting-card">
            <div className="setting-card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <h3 style={{ margin: 0 }}>Recent Conversations</h3>
                <p style={{ margin: "0.15rem 0 0 0" }}>Persisted conversation sessions</p>
              </div>
            </div>

            {isLoading ? (
              <div style={{ padding: "1rem 0", color: "var(--muted)", textAlign: "center", fontSize: "0.85rem" }}>
                Loading conversation history...
              </div>
            ) : !data || data.recent_conversations.length === 0 ? (
              <div style={{ padding: "1rem", textAlign: "center", background: "var(--panel-alt)", borderRadius: "8px" }}>
                <p style={{ margin: 0, color: "var(--muted)", fontSize: "0.85rem" }}>
                  No conversations started yet.
                </p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginTop: "0.5rem" }}>
                {data.recent_conversations.map((c) => (
                  <div
                    key={c.id}
                    style={{
                      padding: "0.6rem 0.85rem",
                      background: "var(--panel-alt)",
                      borderRadius: "6px",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <span style={{ fontSize: "0.85rem", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "200px" }}>
                      {c.title}
                    </span>
                    <time style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                      {new Date(c.updated_at).toLocaleDateString([], { month: "short", day: "numeric" })}
                    </time>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
