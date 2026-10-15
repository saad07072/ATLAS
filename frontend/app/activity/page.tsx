"use client";

import Link from "next/link";
import type { JSX } from "react";
import { useCallback, useEffect, useState } from "react";

import { getUserEvents, listWorkflows } from "@/services/api";
import type { WorkflowEventRecord, WorkflowSummary } from "@/types";

const PAGE_SIZE = 25;

export default function ActivityPage(): JSX.Element {
  const [events, setEvents] = useState<WorkflowEventRecord[]>([]);
  const [totalEvents, setTotalEvents] = useState(0);
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [currentPage, setCurrentPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedFilter, setSelectedFilter] = useState<"all" | "approvals" | "failures" | "completions">("all");

  const loadData = useCallback(async (page: number): Promise<void> => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const [eventsRes, workflowsRes] = await Promise.all([
        getUserEvents(PAGE_SIZE, page * PAGE_SIZE),
        listWorkflows(100, 0),
      ]);
      setEvents(eventsRes.items);
      setTotalEvents(eventsRes.total);
      setHasMore(eventsRes.has_more);
      setWorkflows(workflowsRes.items);
    } catch (err) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Failed to load operational activity history.",
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let isCurrent = true;
    async function init(): Promise<void> {
      try {
        const [eventsRes, workflowsRes] = await Promise.all([
          getUserEvents(PAGE_SIZE, 0),
          listWorkflows(100, 0),
        ]);
        if (isCurrent) {
          setEvents(eventsRes.items);
          setTotalEvents(eventsRes.total);
          setHasMore(eventsRes.has_more);
          setWorkflows(workflowsRes.items);
        }
      } catch (err) {
        if (isCurrent) {
          setErrorMessage(
            err instanceof Error
              ? err.message
              : "Unable to retrieve activity history.",
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

  const handlePageChange = async (newPage: number): Promise<void> => {
    setCurrentPage(newPage);
    await loadData(newPage);
  };

  // Real deterministic calculations from live workflow data
  const pendingCount = workflows.filter((w) =>
    ["draft", "ready", "waiting_for_confirmation"].includes(w.status),
  ).length;
  const runningCount = workflows.filter((w) => w.status === "running").length;
  const completedCount = workflows.filter((w) =>
    ["completed", "partially_completed"].includes(w.status),
  ).length;
  const failedCount = workflows.filter((w) =>
    ["failed", "cancelled"].includes(w.status),
  ).length;

  const filteredEvents = events.filter((ev) => {
    if (selectedFilter === "approvals") {
      return ["confirmation_required", "confirmation_approved", "confirmation_rejected"].includes(ev.event_type);
    }
    if (selectedFilter === "failures") {
      return ["step_failed", "workflow_failed", "step_denied"].includes(ev.event_type);
    }
    if (selectedFilter === "completions") {
      return ["workflow_completed", "step_completed", "workflow_partially_completed"].includes(ev.event_type);
    }
    return true;
  });

  const getEventBadge = (eventType: string): { label: string; chipClass: string } => {
    switch (eventType) {
      case "workflow_started":
        return { label: "Workflow Started", chipClass: "start" };
      case "step_started":
        return { label: "Step Started", chipClass: "start" };
      case "step_completed":
        return { label: "Step Completed", chipClass: "success" };
      case "workflow_completed":
        return { label: "Workflow Completed", chipClass: "success" };
      case "confirmation_required":
        return { label: "Confirmation Required", chipClass: "warning" };
      case "confirmation_approved":
        return { label: "Approved by User", chipClass: "success" };
      case "confirmation_rejected":
        return { label: "Rejected by User", chipClass: "danger" };
      case "step_failed":
        return { label: "Step Failed", chipClass: "danger" };
      case "workflow_failed":
        return { label: "Workflow Failed", chipClass: "danger" };
      case "step_denied":
        return { label: "Action Denied", chipClass: "danger" };
      case "step_skipped":
        return { label: "Step Skipped", chipClass: "warning" };
      case "workflow_partially_completed":
        return { label: "Partially Completed", chipClass: "warning" };
      case "workflow_paused":
        return { label: "Execution Paused", chipClass: "warning" };
      default:
        return { label: eventType.replace(/_/g, " "), chipClass: "start" };
    }
  };

  const getEventSummary = (ev: WorkflowEventRecord): string => {
    const details = ev.details || {};
    if (ev.event_type === "confirmation_required") {
      return details.reason ? `Authorization required: ${String(details.reason)}` : "Sensitive step requires explicit confirmation.";
    }
    if (ev.event_type === "confirmation_approved") {
      return details.reason ? `Approved by user: ${String(details.reason)}` : "User approved step execution.";
    }
    if (ev.event_type === "confirmation_rejected") {
      return details.reason ? `Rejected by user: ${String(details.reason)}` : "User rejected authorization for this operation.";
    }
    if (ev.event_type === "step_failed") {
      const err = details.error as Record<string, unknown> | undefined;
      return err?.message ? String(err.message) : "Step execution failed.";
    }
    if (ev.event_type === "step_skipped") {
      return details.reason ? String(details.reason) : "Prerequisite failed or skipped.";
    }
    if (ev.event_type === "workflow_completed") {
      return `All ${details.total_steps ?? "steps"} completed successfully.`;
    }
    if (ev.event_type === "workflow_partially_completed") {
      return `Finished with partial outcomes: ${details.completed ?? 0} succeeded, ${details.failed ?? 0} failed, ${details.skipped ?? 0} skipped.`;
    }
    if (ev.event_type === "step_completed") {
      return details.verification_status ? `Verified: ${String(details.verification_status)}` : "Tool finished execution.";
    }
    return JSON.stringify(details);
  };

  const totalPages = Math.ceil(totalEvents / PAGE_SIZE) || 1;

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Operations &amp; Audit Log</p>
          <h2>Activity Feed</h2>
        </div>
        <div style={{ display: "flex", gap: "0.6rem" }}>
          <button
            type="button"
            className="ghost-button"
            onClick={() => void loadData(currentPage)}
            disabled={isLoading}
            title="Refresh event log"
          >
            ↻ Refresh
          </button>
          <Link href="/workflows" className="primary-button" style={{ textDecoration: "none" }}>
            Workflow Engine &rarr;
          </Link>
        </div>
      </header>

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
            <strong>Activity Error:</strong> {errorMessage}
          </div>
          <button
            type="button"
            className="secondary-button"
            style={{ padding: "0.35rem 0.75rem", fontSize: "0.8rem" }}
            onClick={() => void loadData(currentPage)}
          >
            Retry
          </button>
        </div>
      )}

      {/* Honest Operational Metrics */}
      <section className="stats-grid" aria-label="Activity overview">
        <article className="stat-card">
          <span>Pending / Approval</span>
          <strong>{isLoading ? "—" : pendingCount}</strong>
          <small style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            Awaiting execution or review
          </small>
        </article>
        <article className="stat-card">
          <span>Running</span>
          <strong>{isLoading ? "—" : runningCount}</strong>
          <small style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            In-flight pipelines
          </small>
        </article>
        <article className="stat-card">
          <span>Completed</span>
          <strong>{isLoading ? "—" : completedCount}</strong>
          <small style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            Verified executions
          </small>
        </article>
        <article className="stat-card">
          <span>Failed / Cancelled</span>
          <strong>{isLoading ? "—" : failedCount}</strong>
          <small style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.25rem" }}>
            Logged errors or halts
          </small>
        </article>
      </section>

      {/* Filter Tabs */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        {[
          { id: "all", label: "All Events" },
          { id: "approvals", label: "Approvals & Gates" },
          { id: "failures", label: "Failures & Halts" },
          { id: "completions", label: "Completions" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`ghost-button ${selectedFilter === tab.id ? "active-filter" : ""}`}
            style={{
              padding: "0.4rem 0.85rem",
              borderRadius: "4px",
              background: selectedFilter === tab.id ? "var(--accent)" : "transparent",
              color: selectedFilter === tab.id ? "var(--foreground-strong)" : "var(--muted)",
              fontSize: "0.85rem",
            }}
            onClick={() => setSelectedFilter(tab.id as typeof selectedFilter)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Events Feed Table */}
      <section className="section-card">
        <div className="table-wrapper">
          <table className="activity-table">
            <thead>
              <tr>
                <th style={{ width: "160px" }}>Timestamp</th>
                <th style={{ width: "180px" }}>Event</th>
                <th>Workflow / Step</th>
                <th>Summary &amp; Details</th>
                <th style={{ width: "110px", textAlign: "right" }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", padding: "2.5rem 0", color: "var(--muted)" }}>
                    Loading operational event history...
                  </td>
                </tr>
              ) : filteredEvents.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", padding: "2.5rem 0" }}>
                    <p style={{ margin: 0, color: "var(--muted)", fontSize: "0.9rem" }}>
                      No operational activity recorded yet.
                    </p>
                    <Link
                      href="/workflows"
                      className="secondary-button"
                      style={{ display: "inline-block", marginTop: "0.75rem", fontSize: "0.8rem", textDecoration: "none" }}
                    >
                      Start a Workflow
                    </Link>
                  </td>
                </tr>
              ) : (
                filteredEvents.map((ev) => {
                  const { label, chipClass } = getEventBadge(ev.event_type);
                  const summary = getEventSummary(ev);
                  return (
                    <tr key={ev.id}>
                      <td style={{ fontSize: "0.8rem", color: "var(--muted)", whiteSpace: "nowrap" }}>
                        {new Date(ev.created_at).toLocaleString([], {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </td>
                      <td>
                        <span className={`activity-chip ${chipClass}`}>{label}</span>
                      </td>
                      <td>
                        <strong>{ev.workflow_title ?? "Workflow Execution"}</strong>
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.15rem" }}>
                          ID: <code>{ev.workflow_id.slice(0, 8)}...</code>
                          {ev.step_id && (
                            <> &middot; Step: <code>{ev.step_id}</code></>
                          )}
                        </div>
                      </td>
                      <td style={{ fontSize: "0.85rem", maxWidth: "340px" }}>
                        <span style={{ color: "var(--text)" }}>{summary}</span>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <Link
                          href="/workflows"
                          style={{ color: "var(--primary)", textDecoration: "none", fontSize: "0.85rem", fontWeight: 500 }}
                        >
                          Inspect &rarr;
                        </Link>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Bounded Pagination Controls */}
        {totalEvents > 0 && (
          <div className="pagination-controls">
            <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
              Showing {currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, totalEvents)} of {totalEvents} events
            </span>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                type="button"
                className="secondary-button"
                disabled={currentPage === 0 || isLoading}
                onClick={() => void handlePageChange(currentPage - 1)}
                style={{ padding: "0.35rem 0.75rem", fontSize: "0.8rem" }}
              >
                &larr; Previous
              </button>
              <span style={{ display: "flex", alignItems: "center", fontSize: "0.8rem", color: "var(--muted)", padding: "0 0.5rem" }}>
                Page {currentPage + 1} of {totalPages}
              </span>
              <button
                type="button"
                className="secondary-button"
                disabled={!hasMore || isLoading}
                onClick={() => void handlePageChange(currentPage + 1)}
                style={{ padding: "0.35rem 0.75rem", fontSize: "0.8rem" }}
              >
                Next &rarr;
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
