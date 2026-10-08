import type { ApiHealthResponse } from "@/types";

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
}

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    throw new Error("The ATLAS backend is unavailable right now.");
  }

  return (await response.json()) as T;
}

export async function getHealth(): Promise<ApiHealthResponse> {
  return request<ApiHealthResponse>("/api/v1/health");
}

export async function sendChatMessage(
  message: string,
  history: ChatHistoryMessage[],
): Promise<ChatApiResponse> {
  return request<ChatApiResponse>("/api/v1/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message, history }),
  });
}
