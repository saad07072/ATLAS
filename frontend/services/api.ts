import type {
  ApiHealthResponse,
  ConversationDetailResponse,
  ConversationListResponse,
  ConversationSummary,
  MemoryItem,
  MemoryListResponse,
} from "@/types";
import { getSupabaseAccessToken } from "@/services/supabase";

const CANDIDATE_API_BASE_URLS = Array.from(
  new Set([
    process.env.NEXT_PUBLIC_API_BASE_URL,
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
    "http://localhost:8000",
    "http://localhost:8001",
  ].filter(Boolean) as string[])
);

let activeApiBaseUrl: string =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ActionRecord {
  tool: string;
  target?: string | null;
  status: "requested" | "in_progress" | "success" | "failed";
  message: string;
  timestamp?: string | null;
  verified?: boolean;
}

export interface ChatApiResponse {
  intent:
    | "conversation"
    | "capability_question"
    | "task_request"
    | "clarification"
    | "unsupported";
  message: string;
  requires_clarification: boolean;
  conversation_id: string;
  actions?: ActionRecord[];
}

export interface GoogleConnectionStatus {
  configured: boolean;
  connected: boolean;
  actions_enabled: boolean;
}

export interface GitHubConnectionStatus {
  configured: boolean;
  connected: boolean;
  actions_enabled: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter?: number;

  constructor(
    status: number,
    message: string,
    code = "api_error",
    retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

export const apiBaseUrl = activeApiBaseUrl;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const accessToken = (await getSupabaseAccessToken()) || "atlas-dev-bearer-token";
  const headers = {
    Accept: "application/json",
    ...(init?.headers ?? {}),
    Authorization: `Bearer ${accessToken}`,
  };

  const candidateUrls = [
    activeApiBaseUrl,
    ...CANDIDATE_API_BASE_URLS.filter((u) => u !== activeApiBaseUrl),
  ];

  let response: Response | null = null;
  for (const candidate of candidateUrls) {
    try {
      response = await fetch(`${candidate}${path}`, {
        ...init,
        headers,
      });
      activeApiBaseUrl = candidate;
      break;
    } catch {
      // Port unreachable or refused, try next candidate port
      continue;
    }
  }

  if (!response) {
    throw new ApiError(
      0,
      "The ATLAS neural backend appears to be offline or unreachable on ports 8000 and 8001, sir. Please start the backend service via 'run_backend.ps1' or 'python -m uvicorn backend.app.main:app'.",
      "network_error",
    );
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { error?: { message?: string; code?: string } }
      | null;

    const retryAfterHeader = response.headers.get("Retry-After");
    const retryAfter = retryAfterHeader ? parseInt(retryAfterHeader, 10) : undefined;
    const code = body?.error?.code ?? (response.status === 429 ? "rate_limit_exceeded" : "api_error");

    let message = body?.error?.message;
    if (!message) {
      if (response.status === 429) {
        message = retryAfter && !isNaN(retryAfter)
          ? `Rate limit reached. Please wait ${retryAfter} seconds before trying again.`
          : "Too many requests. Please wait a moment before trying again.";
      } else if (response.status === 401) {
        message = "Authentication is required to perform this action.";
      } else if (response.status === 403) {
        message = "You do not have permission to perform this action.";
      } else if (response.status === 413) {
        message = "Request payload exceeds maximum allowed size.";
      } else {
        message = "The ATLAS backend is unavailable right now.";
      }
    }

    throw new ApiError(
      response.status,
      message,
      code,
      retryAfter && !isNaN(retryAfter) ? retryAfter : undefined,
    );
  }

  return (await response.json()) as T;
}

export async function getHealth(): Promise<ApiHealthResponse> {
  return request<ApiHealthResponse>("/api/v1/health");
}

export async function sendChatMessage(
  message: string,
  history: ChatHistoryMessage[] = [],
  conversationId?: string,
  signal?: AbortSignal,
  imageData?: string | null,
): Promise<ChatApiResponse> {
  return request<ChatApiResponse>("/api/v1/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    signal,
    body: JSON.stringify({
      message,
      ...(conversationId ? { conversation_id: conversationId } : { history }),
      ...(imageData ? { image_data: imageData } : {}),
    }),
  });
}

export async function getConversations(
  limit = 100,
  offset = 0,
): Promise<ConversationListResponse> {
  return request<ConversationListResponse>(
    `/api/v1/conversations?limit=${limit}&offset=${offset}`,
  );
}

export async function createConversation(
  title?: string,
): Promise<ConversationSummary> {
  return request<ConversationSummary>("/api/v1/conversations", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(title ? { title } : {}),
  });
}

export async function getConversation(
  conversationId: string,
  limit = 100,
  offset = 0,
): Promise<ConversationDetailResponse> {
  return request<ConversationDetailResponse>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}?limit=${limit}&offset=${offset}`,
  );
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<ConversationSummary> {
  return request<ConversationSummary>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ title }),
    },
  );
}

export async function deleteConversation(
  conversationId: string,
): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" },
  );
}

export async function getGoogleConnectionStatus(): Promise<GoogleConnectionStatus> {
  return request<GoogleConnectionStatus>("/api/v1/google/status");
}

export async function getGoogleOAuthStartUrl(): Promise<string> {
  const response = await request<{ authorization_url: string }>(
    "/api/v1/google/oauth/start",
    { credentials: "include" },
  );
  return response.authorization_url;
}

export async function disconnectGoogleConnection(): Promise<void> {
  await request<{ status: string; message: string }>("/api/v1/google/connection", {
    method: "DELETE",
  });
}

export async function getGitHubConnectionStatus(): Promise<GitHubConnectionStatus> {
  return request<GitHubConnectionStatus>("/api/v1/github/status");
}

export async function getMemories(): Promise<MemoryItem[]> {
  const response = await request<MemoryListResponse>("/api/v1/memory");
  return response.memories;
}

export async function deleteMemory(memoryId: string): Promise<void> {
  await request<{ deleted: boolean }>(`/api/v1/memory/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
  });
}

// Workflows API
export async function createWorkflow(
  definition: import("@/types").WorkflowDefinition,
): Promise<import("@/types").WorkflowRecord> {
  return request<import("@/types").WorkflowRecord>("/api/v1/workflows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(definition),
  });
}

export async function listWorkflows(
  limit = 50,
  offset = 0,
  status?: string,
): Promise<import("@/types").WorkflowListResponse> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    ...(status ? { status } : {}),
  });
  return request<import("@/types").WorkflowListResponse>(
    `/api/v1/workflows?${query.toString()}`,
  );
}

export async function getWorkflow(
  workflowId: string,
): Promise<import("@/types").WorkflowRecord> {
  return request<import("@/types").WorkflowRecord>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
  );
}

export async function startWorkflow(
  workflowId: string,
): Promise<import("@/types").WorkflowRecord> {
  return request<import("@/types").WorkflowRecord>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/start`,
    { method: "POST" },
  );
}

export async function resumeWorkflow(
  workflowId: string,
): Promise<import("@/types").WorkflowRecord> {
  return request<import("@/types").WorkflowRecord>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/resume`,
    { method: "POST" },
  );
}

export async function cancelWorkflow(
  workflowId: string,
): Promise<import("@/types").WorkflowRecord> {
  return request<import("@/types").WorkflowRecord>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/cancel`,
    { method: "POST" },
  );
}

export async function confirmWorkflowStep(
  workflowId: string,
  stepId: string,
  decision: "confirm" | "reject",
  reason?: string,
): Promise<import("@/types").WorkflowRecord> {
  return request<import("@/types").WorkflowRecord>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/steps/${encodeURIComponent(stepId)}/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reason }),
    },
  );
}

export async function getWorkflowEvents(
  workflowId: string,
): Promise<import("@/types").WorkflowEventRecord[]> {
  return request<import("@/types").WorkflowEventRecord[]>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/events`,
  );
}

export async function getUserEvents(
  limit = 50,
  offset = 0,
): Promise<import("@/types").WorkflowEventListResponse> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return request<import("@/types").WorkflowEventListResponse>(
    `/api/v1/workflows/events?${query.toString()}`,
  );
}

export async function getDashboardSummary(): Promise<import("@/types").DashboardResponse> {
  return request<import("@/types").DashboardResponse>("/api/v1/dashboard");
}
