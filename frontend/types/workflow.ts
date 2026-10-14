export type WorkflowStatus =
  | "draft"
  | "ready"
  | "running"
  | "waiting_for_confirmation"
  | "completed"
  | "partially_completed"
  | "failed"
  | "cancelled";

export type StepStatus =
  | "pending"
  | "ready"
  | "running"
  | "waiting_for_confirmation"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled";

export type StepVerificationStatus = "unverified" | "verified" | "failed";

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface WorkflowStepDefinition {
  step_id: string;
  title: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  dependencies?: string[];
  max_retries?: number;
  requires_verification?: boolean;
}

export interface WorkflowDefinition {
  title: string;
  user_request: string;
  conversation_id?: string | null;
  steps: WorkflowStepDefinition[];
}

export interface WorkflowStepRecord {
  id: string;
  workflow_id: string;
  step_id: string;
  step_order: number;
  title: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  dependencies: string[];
  status: StepStatus;
  attempt_count: number;
  max_retries: number;
  risk_level: RiskLevel;
  permission_required: boolean;
  permission_decision?: string | null;
  confirmation_state: "not_requested" | "pending" | "confirmed";
  confirmation_hash?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  result_data?: Record<string, unknown> | null;
  error_info?: { code?: string; message?: string } | null;
  verification_status: StepVerificationStatus;
  verification_details?: string | null;
}

export interface WorkflowRecord {
  id: string;
  user_id: string;
  conversation_id?: string | null;
  title: string;
  user_request: string;
  status: WorkflowStatus;
  current_step_id?: string | null;
  step_count: number;
  completed_step_count: number;
  result_summary?: string | null;
  error_summary?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  version: number;
  steps: WorkflowStepRecord[];
}

export interface WorkflowSummary {
  id: string;
  conversation_id?: string | null;
  title: string;
  user_request: string;
  status: WorkflowStatus;
  step_count: number;
  completed_step_count: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface WorkflowListResponse {
  items: WorkflowSummary[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface WorkflowEventRecord {
  id: string;
  workflow_id: string;
  step_id?: string | null;
  event_type: string;
  details: Record<string, unknown>;
  created_at: string;
}

