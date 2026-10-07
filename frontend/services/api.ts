import type { ApiHealthResponse } from "@/types";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

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
