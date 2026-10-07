"use client";

import type { JSX } from "react";
import { useState } from "react";

import { ConfirmationDialog } from "@/components/ui/confirmation-dialog";
import type { ActivityItem } from "@/types";

const activityItems: ActivityItem[] = [
  {
    id: "act-1",
    timestamp: "2026-10-07 08:15",
    userRequest: "Review schedule for the week",
    workflowId: "wf-1024",
    tool: "Planner",
    action: "Collect tasks",
    status: "Pending",
    riskLevel: "Low",
    confirmation: "Required",
    result: "Waiting for approval",
  },
  {
    id: "act-2",
    timestamp: "2026-10-07 09:40",
    userRequest: "Draft daily brief",
    workflowId: "wf-1045",
    tool: "Assistant",
    action: "Summarize updates",
    status: "Running",
    riskLevel: "Medium",
    confirmation: "Pending",
    result: "Gathering current context",
  },
  {
    id: "act-3",
    timestamp: "2026-10-07 11:05",
    userRequest: "Check on the current sprint progress",
    workflowId: "wf-1087",
    tool: "Reporting",
    action: "Publish status",
    status: "Completed",
    riskLevel: "Low",
    confirmation: "Not Required",
    result: "Updated and shared",
  },
];

export default function ActivityPage(): JSX.Element {
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Activity</p>
          <h2>Recent operations</h2>
        </div>
        <button type="button" className="primary-button" onClick={() => setConfirmDialogOpen(true)}>
          Review request
        </button>
      </header>

      <section className="stats-grid" aria-label="Activity overview">
        <article className="stat-card">
          <span>Pending</span>
          <strong>4</strong>
        </article>
        <article className="stat-card">
          <span>Running</span>
          <strong>2</strong>
        </article>
        <article className="stat-card">
          <span>Completed</span>
          <strong>19</strong>
        </article>
        <article className="stat-card">
          <span>Failed</span>
          <strong>1</strong>
        </article>
      </section>

      <section className="section-card">
        <div className="table-wrapper">
          <table className="activity-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Request</th>
                <th>Workflow ID</th>
                <th>Tool</th>
                <th>Action</th>
                <th>Status</th>
                <th>Risk</th>
                <th>Confirmation</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {activityItems.map((item) => (
                <tr key={item.id}>
                  <td>{item.timestamp}</td>
                  <td>{item.userRequest}</td>
                  <td>{item.workflowId}</td>
                  <td>{item.tool}</td>
                  <td>{item.action}</td>
                  <td>
                    <span className={`status-badge ${item.status.toLowerCase().replace(/\s+/g, "-")}`}>
                      {item.status}
                    </span>
                  </td>
                  <td>{item.riskLevel}</td>
                  <td>{item.confirmation}</td>
                  <td>{item.result}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <ConfirmationDialog
        isOpen={confirmDialogOpen}
        title="Approve this activity action"
        description="This is a placeholder confirmation flow for a future workflow or tool operation."
        confirmLabel="Approve"
        cancelLabel="Dismiss"
        onConfirm={() => setConfirmDialogOpen(false)}
        onCancel={() => setConfirmDialogOpen(false)}
      />
    </div>
  );
}
