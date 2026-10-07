import type { JSX } from "react";

interface ConfirmationDialogProps {
  isOpen: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isLoading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmationDialog({
  isOpen,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  isLoading = false,
  onConfirm,
  onCancel,
}: ConfirmationDialogProps): JSX.Element | null {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="dialog-backdrop" aria-modal="true" role="dialog">
      <div className="dialog-card">
        <div className="dialog-header">
          <h3>{title}</h3>
        </div>
        <p>{description}</p>
        <div className="dialog-actions">
          <button type="button" className="ghost-button" onClick={onCancel} disabled={isLoading}>
            {cancelLabel}
          </button>
          <button type="button" className="primary-button" onClick={onConfirm} disabled={isLoading}>
            {isLoading ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
