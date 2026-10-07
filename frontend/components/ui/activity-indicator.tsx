import type { JSX } from "react";

export type ActivityIndicatorState =
  | "processing"
  | "executing"
  | "waiting"
  | "success"
  | "error";

interface ActivityIndicatorProps {
  state: ActivityIndicatorState;
  label?: string;
}

const stateLabels: Record<ActivityIndicatorState, string> = {
  processing: "Processing",
  executing: "Executing",
  waiting: "Waiting",
  success: "Success",
  error: "Error",
};

export function ActivityIndicator({
  state,
  label,
}: ActivityIndicatorProps): JSX.Element {
  return (
    <div className={`activity-indicator indicator-${state}`} role="status" aria-live="polite">
      <span className="indicator-dot" aria-hidden="true" />
      <span>{label ?? stateLabels[state]}</span>
    </div>
  );
}
