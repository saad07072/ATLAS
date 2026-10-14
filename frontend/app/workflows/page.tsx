"use client";

import type { JSX } from "react";
import { useCallback, useEffect, useState } from "react";

import {
  cancelWorkflow,
  confirmWorkflowStep,
  createWorkflow,
  getWorkflow,
  getWorkflowEvents,
  listWorkflows,
  resumeWorkflow,
  startWorkflow,
} from "@/services/api";
import type {
  WorkflowDefinition,
  WorkflowEventRecord,
  WorkflowRecord,
  WorkflowStatus,
  WorkflowSummary,
} from "@/types";

export default function WorkflowsPage(): JSX.Element {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowRecord | null>(null);
  const [events, setEvents] = useState<WorkflowEventRecord[]>([]);
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isDetailLoading, setIsDetailLoading] = useState<boolean>(false);
  const [isActionPending, setIsActionPending] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [confirmReason, setConfirmReason] = useState<string>("");
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);

  // New workflow modal state
  const [newTitle, setNewTitle] = useState("");
  const [newUserRequest, setNewUserRequest] = useState("");
  const [isSensitiveWorkflow, setIsSensitiveWorkflow] = useState(false);

  const fetchWorkflows = useCallback(async (statusFilter?: string): Promise<void> => {
    try {
      const statusParam = statusFilter && statusFilter !== "all" ? statusFilter : undefined;
      const res = await listWorkflows(50, 0, statusParam);
      setWorkflows(res.items);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to load workflows.");
    }
  }, []);

  useEffect(() => {
    let isCurrent = true;
    async function loadWorkflows(): Promise<void> {
      try {
        const statusParam = filterStatus && filterStatus !== "all" ? filterStatus : undefined;
        const res = await listWorkflows(50, 0, statusParam);
        if (isCurrent) {
          setWorkflows(res.items);
          if (res.items.length > 0) {
            if (!selectedWorkflowId || !res.items.some((item) => item.id === selectedWorkflowId)) {
              setSelectedWorkflowId(res.items[0].id);
            }
          } else {
            setSelectedWorkflowId(null);
            setSelectedWorkflow(null);
            setEvents([]);
          }
        }
      } catch (err) {
        if (isCurrent) {
          setErrorMessage(err instanceof Error ? err.message : "Failed to load workflows.");
        }
      } finally {
        if (isCurrent) {
          setIsLoading(false);
        }
      }
    }
    void loadWorkflows();
    return () => {
      isCurrent = false;
    };
  }, [filterStatus, selectedWorkflowId]);

  useEffect(() => {
    if (!selectedWorkflowId) {
      return;
    }
    const targetId = selectedWorkflowId;
    let isCurrent = true;
    async function loadWorkflowDetail(): Promise<void> {
      try {
        const [wf, evs] = await Promise.all([
          getWorkflow(targetId),
          getWorkflowEvents(targetId).catch(() => []),
        ]);
        if (isCurrent) {
          setSelectedWorkflow(wf);
          setEvents(evs);
        }
      } catch (err) {
        if (isCurrent) {
          setErrorMessage(err instanceof Error ? err.message : "Failed to load workflow details.");
        }
      } finally {
        if (isCurrent) {
          setIsDetailLoading(false);
        }
      }
    }
    void loadWorkflowDetail();
    return () => {
      isCurrent = false;
    };
  }, [selectedWorkflowId]);

  const handleStart = async (id: string): Promise<void> => {
    setIsActionPending(true);
    setErrorMessage(null);
    try {
      const updated = await startWorkflow(id);
      setSelectedWorkflow(updated);
      await fetchWorkflows(filterStatus);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Could not start workflow.");
    } finally {
      setIsActionPending(false);
    }
  };

  const handleResume = async (id: string): Promise<void> => {
    setIsActionPending(true);
    setErrorMessage(null);
    try {
      const updated = await resumeWorkflow(id);
      setSelectedWorkflow(updated);
      await fetchWorkflows(filterStatus);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Could not resume workflow.");
    } finally {
      setIsActionPending(false);
    }
  };

  const handleCancel = async (id: string): Promise<void> => {
    if (!window.confirm("Are you sure you want to cancel this workflow?")) {
      return;
    }
    setIsActionPending(true);
    setErrorMessage(null);
    try {
      const updated = await cancelWorkflow(id);
      setSelectedWorkflow(updated);
      await fetchWorkflows(filterStatus);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Could not cancel workflow.");
    } finally {
      setIsActionPending(false);
    }
  };

  const handleConfirmation = async (
    stepId: string,
    decision: "confirm" | "reject",
  ): Promise<void> => {
    if (!selectedWorkflow) return;
    setIsActionPending(true);
    setErrorMessage(null);
    try {
      const updated = await confirmWorkflowStep(
        selectedWorkflow.id,
        stepId,
        decision,
        confirmReason.trim() || undefined,
      );
      setSelectedWorkflow(updated);
      setConfirmReason("");
      await fetchWorkflows(filterStatus);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Confirmation failed.");
    } finally {
      setIsActionPending(false);
    }
  };

  const handleCreateSampleWorkflow = async (includeHighRisk = false): Promise<void> => {
    setIsActionPending(true);
    setErrorMessage(null);
    try {
      const sampleDef: WorkflowDefinition = includeHighRisk
        ? {
            title: "Data Audit and High-Risk Action",
            user_request: "Extract audit parameters, verify environment condition, and request user authorization for high-risk update.",
            steps: [
              {
                step_id: "step-1-extract",
                title: "Extract parameters",
                tool_name: "planner.extract",
                arguments: { text: "Server maintenance window 2026-10-14", field_name: "maintenance_time" },
                dependencies: [],
              },
              {
                step_id: "step-2-verify",
                title: "Verify maintenance condition",
                tool_name: "system.verify",
                arguments: {
                  item: "maintenance_flag",
                  expected_value: "active",
                  actual_value: "active",
                },
                dependencies: ["step-1-extract"],
              },
              {
                step_id: "step-3-sensitive-action",
                title: "Perform sensitive update",
                tool_name: "test.action.high_risk",
                arguments: { action_name: "apply_security_patch", parameters: { target: "core" } },
                dependencies: ["step-2-verify"],
              },
              {
                step_id: "step-4-echo-report",
                title: "Emit completion summary",
                tool_name: "system.echo",
                arguments: { message: "Workflow finished and verified." },
                dependencies: ["step-3-sensitive-action"],
              },
            ],
          }
        : {
            title: "Multi-step Data Verification Task",
            user_request: "Extract parameters, verify match, and echo final report.",
            steps: [
              {
                step_id: "step-1-extract",
                title: "Extract task parameters",
                tool_name: "planner.extract",
                arguments: { text: "Quarterly review data", field_name: "review_type" },
                dependencies: [],
              },
              {
                step_id: "step-2-verify",
                title: "Verify criteria match",
                tool_name: "system.verify",
                arguments: {
                  item: "status",
                  expected_value: "ready",
                  actual_value: "ready",
                },
                dependencies: ["step-1-extract"],
              },
              {
                step_id: "step-3-report",
                title: "Generate report summary",
                tool_name: "system.echo",
                arguments: { message: "Task verification succeeded." },
                dependencies: ["step-2-verify"],
              },
            ],
          };

      const created = await createWorkflow(sampleDef);
      setShowCreateModal(false);
      await fetchWorkflows(filterStatus);
      setSelectedWorkflowId(created.id);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to create workflow.");
    } finally {
      setIsActionPending(false);
    }
  };

  const getStatusBadgeClass = (status: WorkflowStatus | string): string => {
    switch (status) {
      case "completed":
        return "status-badge connected";
      case "running":
      case "ready":
        return "status-badge in-progress";
      case "waiting_for_confirmation":
        return "status-badge waiting";
      case "partially_completed":
        return "status-badge warning";
      case "failed":
      case "cancelled":
        return "status-badge disconnected";
      default:
        return "status-badge";
    }
  };

  const waitingStep = selectedWorkflow?.steps.find(
    (s) => s.status === "waiting_for_confirmation",
  );

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Execution Engine</p>
          <h2>Workflow Management</h2>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            type="button"
            className="secondary-button"
            onClick={() => void handleCreateSampleWorkflow(false)}
            disabled={isActionPending}
          >
            + Quick Sample Plan
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={() => setShowCreateModal(true)}
            disabled={isActionPending}
          >
            + Create Workflow
          </button>
        </div>
      </header>

      {errorMessage && (
        <div className="inline-error" role="alert" style={{ marginBottom: "1rem" }}>
          <p>{errorMessage}</p>
          <button
            type="button"
            className="ghost-button"
            onClick={() => setErrorMessage(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="workflow-filters" style={{ marginBottom: "1rem", display: "flex", gap: "0.5rem" }}>
        {["all", "running", "waiting_for_confirmation", "completed", "partially_completed", "cancelled"].map((st) => (
          <button
            key={st}
            type="button"
            className={`ghost-button ${filterStatus === st ? "active-filter" : ""}`}
            style={{
              padding: "0.4rem 0.8rem",
              borderRadius: "4px",
              background: filterStatus === st ? "var(--accent)" : "transparent",
              color: filterStatus === st ? "var(--foreground-strong)" : "var(--muted)",
            }}
            onClick={() => setFilterStatus(st)}
          >
            {st.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
          </button>
        ))}
      </div>

      <div className="workflow-layout" style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: "1.5rem" }}>
        {/* Workflows List */}
        <section className="workflow-list-panel" aria-label="Workflows list">
          {isLoading ? (
            <div className="empty-card"><p>Loading workflows...</p></div>
          ) : workflows.length === 0 ? (
            <div className="empty-card">
              <p>No workflows found.</p>
              <button
                type="button"
                className="secondary-button"
                style={{ marginTop: "0.5rem" }}
                onClick={() => void handleCreateSampleWorkflow(true)}
              >
                Create High-Risk Demo
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {workflows.map((wf) => (
                <div
                  key={wf.id}
                  className={`setting-card workflow-item-card ${selectedWorkflowId === wf.id ? "active-item" : ""}`}
                  style={{
                    padding: "0.85rem",
                    cursor: "pointer",
                    border: selectedWorkflowId === wf.id ? "1px solid var(--accent-border, #4a72b2)" : "1px solid var(--border)",
                  }}
                  onClick={() => setSelectedWorkflowId(wf.id)}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.25rem" }}>
                    <h4 style={{ margin: 0, fontSize: "0.95rem" }}>{wf.title}</h4>
                    <span className={getStatusBadgeClass(wf.status)}>
                      {wf.status.replace(/_/g, " ")}
                    </span>
                  </div>
                  <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)" }}>
                    Steps: {wf.completed_step_count}/{wf.step_count}
                  </p>
                  <p style={{ margin: "0.2rem 0 0 0", fontSize: "0.75rem", color: "var(--muted)" }}>
                    Updated: {new Date(wf.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Workflow Detail View */}
        <section className="workflow-detail-panel" aria-label="Workflow details">
          {isDetailLoading ? (
            <div className="empty-card"><p>Loading workflow details...</p></div>
          ) : !selectedWorkflow ? (
            <div className="empty-card"><p>Select a workflow from the list to view its execution graph.</p></div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
              {/* Overview Header */}
              <article className="setting-card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: "1.2rem" }}>{selectedWorkflow.title}</h3>
                    <p style={{ margin: "0.25rem 0 0 0", color: "var(--muted)", fontSize: "0.9rem" }}>
                      &ldquo;{selectedWorkflow.user_request}&rdquo;
                    </p>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    <span className={getStatusBadgeClass(selectedWorkflow.status)}>
                      {selectedWorkflow.status.replace(/_/g, " ")}
                    </span>
                    {selectedWorkflow.status === "draft" || selectedWorkflow.status === "ready" ? (
                      <button
                        type="button"
                        className="primary-button"
                        disabled={isActionPending}
                        onClick={() => void handleStart(selectedWorkflow.id)}
                      >
                        Start Execution
                      </button>
                    ) : null}
                    {selectedWorkflow.status === "waiting_for_confirmation" && !waitingStep ? (
                      <button
                        type="button"
                        className="primary-button"
                        disabled={isActionPending}
                        onClick={() => void handleResume(selectedWorkflow.id)}
                      >
                        Resume
                      </button>
                    ) : null}
                    {["ready", "running", "waiting_for_confirmation"].includes(selectedWorkflow.status) ? (
                      <button
                        type="button"
                        className="ghost-button"
                        disabled={isActionPending}
                        onClick={() => void handleCancel(selectedWorkflow.id)}
                      >
                        Cancel
                      </button>
                    ) : null}
                  </div>
                </div>

                {/* Progress Bar */}
                <div style={{ background: "var(--surface)", height: "8px", borderRadius: "4px", overflow: "hidden", marginBottom: "0.5rem" }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${(selectedWorkflow.completed_step_count / Math.max(selectedWorkflow.step_count, 1)) * 100}%`,
                      background: selectedWorkflow.status === "partially_completed" ? "var(--warning, #e6a23c)" : "var(--accent)",
                      transition: "width 0.3s ease",
                    }}
                  />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "var(--muted)" }}>
                  <span>Completed: {selectedWorkflow.completed_step_count} of {selectedWorkflow.step_count} steps</span>
                  {selectedWorkflow.result_summary && (
                    <span style={{ fontWeight: 500, color: "var(--foreground)" }}>{selectedWorkflow.result_summary}</span>
                  )}
                  {selectedWorkflow.error_summary && (
                    <span style={{ color: "var(--danger, #f56c6c)" }}>{selectedWorkflow.error_summary}</span>
                  )}
                </div>
              </article>

              {/* Waiting for Confirmation Action Card */}
              {waitingStep && (
                <article
                  className="setting-card confirmation-card"
                  style={{
                    border: "2px solid var(--warning, #e6a23c)",
                    background: "rgba(230, 162, 60, 0.08)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
                    <span style={{ fontSize: "1.2rem" }}>⚠️</span>
                    <h4 style={{ margin: 0, color: "var(--warning-text, #e6a23c)" }}>
                      Authorization Required
                    </h4>
                    <span className="status-badge" style={{ background: "#f56c6c", color: "#fff", marginLeft: "auto" }}>
                      Risk: {waitingStep.risk_level.toUpperCase()}
                    </span>
                  </div>
                  <p style={{ margin: "0.25rem 0 0.75rem 0", fontSize: "0.9rem" }}>
                    Step <strong>&ldquo;{waitingStep.title}&rdquo;</strong> requires your explicit confirmation before calling tool <code>{waitingStep.tool_name}</code>.
                  </p>
                  <div style={{ background: "var(--surface)", padding: "0.6rem", borderRadius: "4px", marginBottom: "0.75rem", fontSize: "0.85rem", overflowX: "auto" }}>
                    <strong>Parameters:</strong>
                    <pre style={{ margin: "0.25rem 0 0 0" }}>{JSON.stringify(waitingStep.arguments, null, 2)}</pre>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    <input
                      type="text"
                      placeholder="Optional reason or operator note"
                      value={confirmReason}
                      onChange={(e) => setConfirmReason(e.target.value)}
                      style={{ flex: 1, padding: "0.4rem 0.6rem", fontSize: "0.85rem" }}
                      disabled={isActionPending}
                    />
                    <button
                      type="button"
                      className="primary-button"
                      disabled={isActionPending}
                      onClick={() => void handleConfirmation(waitingStep.step_id, "confirm")}
                    >
                      Authorize &amp; Proceed
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      style={{ color: "var(--danger, #f56c6c)" }}
                      disabled={isActionPending}
                      onClick={() => void handleConfirmation(waitingStep.step_id, "reject")}
                    >
                      Reject Action
                    </button>
                  </div>
                </article>
              )}

              {/* Step DAG / Execution Flow */}
              <article className="setting-card">
                <h4 style={{ margin: "0 0 1rem 0" }}>Execution Pipeline</h4>
                <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                  {selectedWorkflow.steps.map((step, idx) => (
                    <div
                      key={step.step_id}
                      style={{
                        padding: "0.85rem",
                        border: "1px solid var(--border)",
                        borderRadius: "6px",
                        background: step.status === "running" ? "rgba(74, 114, 178, 0.08)" : "var(--surface)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                          <span style={{ fontWeight: 600, fontSize: "0.85rem", color: "var(--muted)" }}>#{idx + 1}</span>
                          <strong style={{ fontSize: "0.95rem" }}>{step.title}</strong>
                          <code style={{ fontSize: "0.8rem", color: "var(--muted)" }}>({step.tool_name})</code>
                        </div>
                        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                          {step.verification_status === "verified" && (
                            <span className="status-badge connected" title="Output Verified">✓ Verified</span>
                          )}
                          {step.verification_status === "failed" && (
                            <span className="status-badge disconnected" title="Verification Mismatch">✗ Verification Failed</span>
                          )}
                          <span className={getStatusBadgeClass(step.status)}>
                            {step.status.replace(/_/g, " ")}
                          </span>
                        </div>
                      </div>

                      {step.dependencies.length > 0 && (
                        <p style={{ margin: "0 0 0.4rem 0", fontSize: "0.75rem", color: "var(--muted)" }}>
                          Prerequisites: {step.dependencies.join(", ")}
                        </p>
                      )}

                      {step.result_data && (
                        <div style={{ marginTop: "0.4rem", fontSize: "0.8rem", background: "rgba(0,0,0,0.15)", padding: "0.4rem 0.6rem", borderRadius: "4px" }}>
                          <span style={{ color: "var(--muted)" }}>Result: </span>
                          <span>{JSON.stringify(step.result_data)}</span>
                        </div>
                      )}

                      {step.error_info && (
                        <div style={{ marginTop: "0.4rem", fontSize: "0.8rem", color: "var(--danger, #f56c6c)" }}>
                          Error: {step.error_info.message || step.error_info.code}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </article>

              {/* Audit Events */}
              {events.length > 0 && (
                <article className="setting-card">
                  <h4 style={{ margin: "0 0 0.75rem 0" }}>Audit Trail ({events.length} events)</h4>
                  <div style={{ maxHeight: "200px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                    {events.map((ev) => (
                      <div key={ev.id} style={{ fontSize: "0.75rem", color: "var(--muted)", display: "flex", gap: "0.5rem" }}>
                        <time>{new Date(ev.created_at).toLocaleTimeString()}</time>
                        <span style={{ fontWeight: 600, color: "var(--foreground)" }}>{ev.event_type}</span>
                        {ev.step_id && <span>[{ev.step_id}]</span>}
                        <span>{JSON.stringify(ev.details)}</span>
                      </div>
                    ))}
                  </div>
                </article>
              )}
            </div>
          )}
        </section>
      </div>

      {/* Create Workflow Modal */}
      {showCreateModal && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div className="setting-card" style={{ width: "480px", maxWidth: "90vw", background: "var(--background, #12141a)" }}>
            <h3>Create Workflow Task</h3>
            <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: "0.25rem 0 1rem 0" }}>
              Define a multi-step task with dependency validation and execution policies.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              <div>
                <label style={{ display: "block", fontSize: "0.8rem", marginBottom: "0.25rem" }}>Workflow Title</label>
                <input
                  type="text"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="e.g. Schedule and verify briefing"
                  style={{ width: "100%", padding: "0.5rem" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "0.8rem", marginBottom: "0.25rem" }}>User Request</label>
                <textarea
                  value={newUserRequest}
                  onChange={(e) => setNewUserRequest(e.target.value)}
                  placeholder="e.g. Extract task parameters, verify constraints, and execute."
                  rows={3}
                  style={{ width: "100%", padding: "0.5rem" }}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <input
                  id="include-sensitive"
                  type="checkbox"
                  checked={isSensitiveWorkflow}
                  onChange={(e) => setIsSensitiveWorkflow(e.target.checked)}
                />
                <label htmlFor="include-sensitive" style={{ fontSize: "0.85rem" }}>
                  Include high-risk step requiring mandatory authorization
                </label>
              </div>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1.25rem" }}>
              <button
                type="button"
                className="ghost-button"
                onClick={() => setShowCreateModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={!newTitle.trim() || !newUserRequest.trim() || isActionPending}
                onClick={async () => {
                  await handleCreateSampleWorkflow(isSensitiveWorkflow);
                }}
              >
                Create &amp; Plan
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

