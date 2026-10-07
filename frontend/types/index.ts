export type ActivityStatus =
  | "Pending"
  | "Running"
  | "Waiting for Confirmation"
  | "Completed"
  | "Failed"
  | "Cancelled";

export type RiskLevel = "Low" | "Medium" | "High";
export type ConfirmationState = "Required" | "Not Required" | "Pending";

export interface ApiHealthResponse {
  status: string;
  service: string;
  version: string;
  timestamp: string;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  timestamp: string;
}

export interface ActivityItem {
  id: string;
  timestamp: string;
  userRequest: string;
  workflowId: string;
  tool: string;
  action: string;
  status: ActivityStatus;
  riskLevel: RiskLevel;
  confirmation: ConfirmationState;
  result: string;
  error?: string;
}

export interface MemoryItem {
  id: string;
  title: string;
  summary: string;
  category: string;
  updatedAt: string;
  status: "Active" | "Draft" | "Needs Review";
}

export interface ServiceStatus {
  id: string;
  name: string;
  status: "Connected" | "Disconnected" | "Unavailable";
  description: string;
}

export interface SettingGroup {
  id: string;
  title: string;
  description: string;
  state: string;
}
