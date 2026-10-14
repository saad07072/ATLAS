"use client";

import Link from "next/link";
import type { JSX } from "react";
import { useEffect, useState } from "react";

import { ConfirmationDialog } from "@/components/ui/confirmation-dialog";
import { listWorkflows } from "@/services/api";
import type { ActivityItem, WorkflowSummary } from "@/types";

const fallbackActivityItems: ActivityItem[] = [
  {
    id: "act-1",
    timestamp: "2026-10-14 10:15",
    userRequest: "Daily task extraction & schedule check",
    workflowId: "wf-sample-1",
    tool: "Planner",
    action: "Extract parameters",
    status: "Completed",
    riskLevel: "Low",
    confirmation: "Not Required",
    result: "Successfully extracted parameters",
  },
  {
    id: "act-2",
    timestamp: "2026-10-14 11:40",
    userRequest: "System verification & environment audit",
    workflowId: "wf-sample-2",
    tool: "Verifier",
    action: "Verify condition",
    status: "Completed",
    riskLevel: "Low",
    confirmation: "Not Required",
    result: "Criteria verified",
  },
];

export default function ActivityPage(): JSX.Element {
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);

  useEffect(() => {
    let isCurrent = true;
    async function load(): Promise<void> {
      try {
        const res = await listWorkflows(20, 0);
        if (isCurrent) {
          setWorkflows(res.items);
        }
      } catch {
        // Fallback silently if API unavailable
      }
    }
    void load();
    return () => {
      isCurrent = false;
    };
  }, []);

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

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Activity</p>
          <h2>Operations &amp; Audit Log</h2>
        </div>
        <Link href="/workflows" className="primary-button" style={{ textDecoration: "none" }}>
          View Workflow Engine
        </Link>
      </header>

      <section className="stats-grid" aria-label="Activity overview">
        <article className="stat-card">
          <span>Pending / Approval</span>
          <strong>{workflows.length > 0 ? pendingCount : 1}</strong>
        </article>
        <article className="stat-card">
          <span>Running</span>
          <strong>{workflows.length > 0 ? runningCount : 0}</strong>
        </article>
        <article className="stat-card">
          <span>Completed</span>
          <strong>{workflows.length > 0 ? completedCount : 2}</strong>
        </article>
        <article className="stat-card">
          <span>Failed / Cancelled</span>
          <strong>{workflows.length > 0 ? failedCount : 0}</strong>
        </article>
      </section>

      <section className="section-card">
        <div className="table-wrapper">
          <table className="activity-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Request / Title</th>
                <th>Workflow ID</th>
                <th>Status</th>
                <th>Steps Progress</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {workflows.length > 0
                ? workflows.map((w) => (
                    <tr key={w.id}>
                      <td>{new Date(w.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
                      <td>
                        <strong>{w.title}</strong>
                        <br />
                        <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{w.user_request}</span>
                      </td>
                      <td>
                        <code>{w.id.slice(0, 8)}...</code>
                      </td>
                      <td>
                        <span className={`status-badge ${w.status.replace(/_/g, "-")}`}>
                          {w.status.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td>
                        {w.completed_step_count} / {w.step_count}
                      </td>
                      <td>
                        <Link href="/workflows" style={{ color: "var(--primary)", textDecoration: "none" }}>
                          Inspect &rarr;
                        </Link>
                      </td>
                    </tr>
                  ))
                : fallbackActivityItems.map((item) => (
                    <tr key={item.id}>
                      <td>{item.timestamp}</td>
                      <td>{item.userRequest}</td>
                      <td>{item.workflowId}</td>
                      <td>
                        <span className="status-badge connected">{item.status}</span>
                      </td>
                      <td>1 / 1</td>
                      <td>
                        <span style={{ color: "var(--muted)" }}>Logged</span>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      </section>

      <ConfirmationDialog
        isOpen={confirmDialogOpen}
        title="Approve this activity action"
        description="This is a confirmation flow for a workflow or tool operation."
        confirmLabel="Approve"
        cancelLabel="Dismiss"
        onConfirm={() => setConfirmDialogOpen(false)}
        onCancel={() => setConfirmDialogOpen(false)}
      />
    </div>
  );
}
