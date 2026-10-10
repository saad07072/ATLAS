"use client";

import { useCallback, useEffect, useState } from "react";
import type { JSX } from "react";

import { ConfirmationDialog } from "@/components/ui/confirmation-dialog";
import { deleteMemory, getMemories } from "@/services/api";
import type { MemoryItem } from "@/types";

type LoadState = "loading" | "loaded" | "error";

function formatType(value: MemoryItem["type"]): string {
  return value.replaceAll("_", " ");
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

export default function MemoryPage(): JSX.Element {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [selectedMemory, setSelectedMemory] = useState<MemoryItem | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoadState("loading");
    setLoadError(null);
    try {
      setMemories(await getMemories());
      setLoadState("loaded");
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : "Could not load saved memories.",
      );
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    getMemories()
      .then((result) => {
        if (cancelled) {
          return;
        }
        setMemories(result);
        setLoadState("loaded");
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        setLoadError(
          error instanceof Error
            ? error.message
            : "Could not load saved memories.",
        );
        setLoadState("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function confirmDelete(): Promise<void> {
    if (!selectedMemory) {
      return;
    }
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteMemory(selectedMemory.id);
      setMemories((current) =>
        current.filter((memory) => memory.id !== selectedMemory.id),
      );
      setSuccessMessage("Memory deleted.");
      setSelectedMemory(null);
    } catch (error) {
      setDeleteError(
        error instanceof Error ? error.message : "Could not delete this memory.",
      );
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Memory</p>
          <h2>Context and knowledge foundation</h2>
          <p>Review and remove information ATLAS has explicitly saved.</p>
        </div>
      </header>

      {successMessage && (
        <p className="memory-success" role="status">
          {successMessage}
        </p>
      )}

      {loadState === "loading" && (
        <p role="status">Loading saved memories…</p>
      )}

      {loadState === "error" && (
        <div className="inline-error" role="alert">
          <p>{loadError}</p>
          <button type="button" className="ghost-button" onClick={() => void load()}>
            Try again
          </button>
        </div>
      )}

      {loadState === "loaded" && memories.length === 0 && (
        <section className="chat-empty-state" aria-label="No saved memories">
          <p>No saved memories yet. ATLAS only keeps information you explicitly save.</p>
        </section>
      )}

      {loadState === "loaded" && memories.length > 0 && (
        <section className="memory-list" aria-label="Memory items">
          {memories.map((memory) => (
            <article key={memory.id} className="memory-card">
              <div className="memory-card-header">
                <span className="memory-category">{formatType(memory.type)}</span>
                <span className="meta-pill">{memory.source.replaceAll("_", " ")}</span>
              </div>
              <h3>{memory.memory_key.replaceAll(/[._-]/g, " ")}</h3>
              <p>{memory.content}</p>
              <div className="meta-row">
                <span>Updated {formatDate(memory.updated_at)}</span>
                <button
                  type="button"
                  className="ghost-button memory-delete-button"
                  onClick={() => {
                    setDeleteError(null);
                    setSelectedMemory(memory);
                  }}
                >
                  Delete
                </button>
              </div>
            </article>
          ))}
        </section>
      )}

      {deleteError && (
        <p className="inline-error" role="alert">
          {deleteError}
        </p>
      )}

      <ConfirmationDialog
        isOpen={selectedMemory !== null}
        title="Delete this memory?"
        description="This permanently removes the saved memory and it will no longer be used as context."
        confirmLabel="Delete memory"
        isLoading={isDeleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setSelectedMemory(null)}
      />
    </div>
  );
}
