import type {
  ApiHealthResponse,
  ConversationDetailResponse,
  ConversationListResponse,
  ConversationSummary,
  MemoryItem,
  MemoryListResponse,
} from "@/types";
import { getSupabaseAccessToken } from "@/services/supabase";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8001";

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
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

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const accessToken = await getSupabaseAccessToken();
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { error?: { message?: string } }
      | null;
    throw new Error(
      body?.error?.message ?? "The ATLAS backend is unavailable right now.",
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
): Promise<ChatApiResponse> {
  return request<ChatApiResponse>("/api/v1/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      ...(conversationId ? { conversation_id: conversationId } : { history }),
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
