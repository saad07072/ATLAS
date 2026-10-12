"use client";

import type { FormEvent, JSX } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ActivityIndicator } from "@/components/ui/activity-indicator";
import { ConfirmationDialog } from "@/components/ui/confirmation-dialog";
import { useVoice } from "@/hooks/use-voice";
import {
  createConversation,
  deleteConversation,
  getConversation,
  getConversations,
  renameConversation,
  sendChatMessage,
} from "@/services/api";
import type { ChatMessage, ConversationSummary } from "@/types";

import { ChatMessageItem } from "./chat-message";

export function ChatPanel(): JSX.Element {
  const {
    isRecognitionSupported,
    isSynthesisSupported,
    recognitionState,
    interimTranscript,
    recognitionError,
    startListening,
    stopListening,
    cancelListening,
    clearRecognitionError,
    isSpeaking,
    speakingMessageId,
    settings: voiceSettings,
    speak,
    stopSpeaking,
    toggleAutoSpeak,
  } = useVoice();

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMoreConversations, setHasMoreConversations] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isLoadingEarlier, setIsLoadingEarlier] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSavingConversation, setIsSavingConversation] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [olderConversationsError, setOlderConversationsError] = useState<string | null>(null);
  const [messageError, setMessageError] = useState<string | null>(null);
  const [messageRetryKey, setMessageRetryKey] = useState(0);
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [messageOffset, setMessageOffset] = useState(0);
  const [olderMessagesError, setOlderMessagesError] = useState<string | null>(null);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [editedTitle, setEditedTitle] = useState("");
  const [conversationToDelete, setConversationToDelete] =
    useState<ConversationSummary | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const loadSequence = useRef(0);

  const loadConversations = useCallback(async (): Promise<void> => {
    try {
      const response = await getConversations();
      setConversations(response.conversations);
      setHasMoreConversations(response.has_more);
      setListError(null);
    } catch {
      setListError("Could not load your conversations.");
    } finally {
      setIsLoadingList(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void getConversations()
      .then((response) => {
        if (active) {
          setConversations(response.conversations);
          setHasMoreConversations(response.has_more);
          setListError(null);
        }
      })
      .catch(() => {
        if (active) {
          setListError("Could not load your conversations.");
        }
      })
      .finally(() => {
        if (active) {
          setIsLoadingList(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const requestSequence = ++loadSequence.current;
    if (!selectedConversationId) {
      return;
    }

    void getConversation(selectedConversationId)
      .then((detail) => {
        if (requestSequence === loadSequence.current) {
          setMessages(
            detail.messages.map((message) => ({
              id: message.id,
              role: message.role,
              content: message.content,
              timestamp: new Date(message.created_at).toLocaleString(),
            })),
          );
          setHasMoreMessages(detail.has_more);
          setMessageOffset(detail.messages.length);
        }
      })
      .catch(() => {
        if (requestSequence === loadSequence.current) {
          setMessageError("Could not load this conversation.");
          setMessages([]);
        }
      })
      .finally(() => {
        if (requestSequence === loadSequence.current) {
          setIsLoadingMessages(false);
        }
      });
  }, [selectedConversationId, messageRetryKey]);

  const selectedConversation = conversations.find(
    (conversation) => conversation.id === selectedConversationId,
  );
  const isBusy =
    isProcessing ||
    isLoadingMessages ||
    isSavingConversation ||
    isDeleting ||
    isLoadingMore ||
    isLoadingEarlier;

  function selectConversation(conversationId: string | null): void {
    if (isSpeaking) {
      stopSpeaking();
    }
    if (recognitionState === "listening") {
      cancelListening();
    }
    loadSequence.current += 1;
    setMessageError(null);
    setOlderMessagesError(null);
    setHasMoreMessages(false);
    setMessageOffset(0);
    setIsLoadingMessages(conversationId !== null);
    if (!conversationId) {
      setMessages([]);
    }
    setSelectedConversationId(conversationId);
  }

  function handleRetryConversationList(): void {
    setListError(null);
    setIsLoadingList(true);
    void loadConversations();
  }

  async function handleStartConversation(): Promise<void> {
    if (isSpeaking) {
      stopSpeaking();
    }
    if (recognitionState === "listening") {
      cancelListening();
    }
    setConversationError(null);
    setIsSavingConversation(true);
    try {
      const conversation = await createConversation();
      setListError(null);
      setHasMoreConversations((current) => current || conversations.length >= 100);
      setConversations((current) => [conversation, ...current].slice(0, 100));
      selectConversation(conversation.id);
      setMessages([]);
      setDraft("");
    } catch {
      setConversationError("Could not start a new conversation. Please retry.");
    } finally {
      setIsSavingConversation(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed || !selectedConversationId || isBusy) {
      return;
    }

    if (isSpeaking) {
      stopSpeaking();
    }
    if (recognitionState === "listening") {
      stopListening();
    }

    const conversationId = selectedConversationId;
    setMessages((current) => [
      ...current,
      {
        id: `pending-${Date.now()}`,
        role: "user",
        content: trimmed,
        timestamp: "Now",
      },
    ]);
    setDraft("");
    setMessageError(null);
    setIsProcessing(true);

    try {
      const response = await sendChatMessage(trimmed, [], conversationId);
      if (response.conversation_id !== conversationId) {
        throw new Error("The response conversation did not match the request.");
      }
      const assistantMessageId = `assistant-${Date.now()}`;
      setMessages((current) => [
        ...current,
        {
          id: assistantMessageId,
          role: "assistant",
          content: response.message,
          timestamp: "Just now",
        },
      ]);
      if (voiceSettings.autoSpeak && isSynthesisSupported) {
        speak(response.message, assistantMessageId);
      }
      try {
        const detail = await getConversation(conversationId, 1);
        setConversations((current) =>
          [
            detail.conversation,
            ...current.filter((conversation) => conversation.id !== conversationId),
          ].sort((first, second) =>
            second.updated_at.localeCompare(first.updated_at),
          ),
        );
      } catch {
        await loadConversations();
      }
    } catch {
      setMessageError("ATLAS could not complete this response. Please retry.");
      setDraft(trimmed);
      try {
        const detail = await getConversation(conversationId);
        setMessages(
          detail.messages.map((message) => ({
            id: message.id,
            role: message.role,
            content: message.content,
            timestamp: new Date(message.created_at).toLocaleString(),
          })),
        );
        setHasMoreMessages(detail.has_more);
        setMessageOffset(detail.messages.length);
      } catch {
        setMessageError(
          "ATLAS could not complete this response, and the saved conversation could not be refreshed.",
        );
      }
    } finally {
      setIsProcessing(false);
    }
  }

  async function handleRename(conversationId: string): Promise<void> {
    const title = editedTitle.trim();
    if (!title || isBusy) {
      return;
    }
    setConversationError(null);
    setIsSavingConversation(true);
    try {
      const updated = await renameConversation(conversationId, title);
      setConversations((current) =>
        [updated, ...current.filter((conversation) => conversation.id !== conversationId)],
      );
      setEditingConversationId(null);
    } catch {
      setConversationError("Could not rename this conversation. Please retry.");
    } finally {
      setIsSavingConversation(false);
    }
  }

  async function handleDelete(): Promise<void> {
    if (!conversationToDelete || isBusy) {
      return;
    }

    const deletedId = conversationToDelete.id;
    setIsDeleting(true);
    setConversationError(null);
    try {
      await deleteConversation(deletedId);
      const remaining = conversations.filter(
        (conversation) => conversation.id !== deletedId,
      );
      setConversations(remaining);
      if (selectedConversationId === deletedId) {
        selectConversation(remaining[0]?.id ?? null);
      }
      setConversationToDelete(null);
    } catch {
      setConversationError("Could not delete this conversation. Please retry.");
    } finally {
      setIsDeleting(false);
    }
  }

  async function handleLoadMore(): Promise<void> {
    if (isLoadingMore) {
      return;
    }
    setIsLoadingMore(true);
    setOlderConversationsError(null);
    try {
      const response = await getConversations(100, conversations.length);
      setConversations((current) => {
        const existingIds = new Set(current.map((conversation) => conversation.id));
        return [
          ...current,
          ...response.conversations.filter(
            (conversation) => !existingIds.has(conversation.id),
          ),
        ];
      });
      setHasMoreConversations(response.has_more);
    } catch {
      setOlderConversationsError("Could not load older conversations.");
    } finally {
      setIsLoadingMore(false);
    }
  }

  async function handleLoadEarlierMessages(): Promise<void> {
    if (!selectedConversationId || isBusy || !hasMoreMessages) {
      return;
    }
    const conversationId = selectedConversationId;
    const offset = messageOffset;
    setOlderMessagesError(null);
    setIsLoadingEarlier(true);
    try {
      const detail = await getConversation(conversationId, 100, offset);
      const earlierMessages = detail.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        timestamp: new Date(message.created_at).toLocaleString(),
      }));
      setMessages((current) => {
        const currentIds = new Set(current.map((message) => message.id));
        return [
          ...earlierMessages.filter((message) => !currentIds.has(message.id)),
          ...current,
        ];
      });
      setMessageOffset(offset + detail.messages.length);
      setHasMoreMessages(detail.has_more);
    } catch {
      setOlderMessagesError("Could not load earlier messages.");
    } finally {
      setIsLoadingEarlier(false);
    }
  }

  return (
    <section className="conversation-workspace" aria-label="ATLAS conversations">
      <aside className="conversation-sidebar" aria-label="Conversation history">
        <div className="conversation-sidebar-header">
          <div>
            <p className="eyebrow">History</p>
            <h2>Conversations</h2>
          </div>
          <button
            type="button"
            className="primary-button conversation-new-button"
            onClick={() => void handleStartConversation()}
            disabled={isBusy || isLoadingList}
          >
            New chat
          </button>
        </div>

        {conversationError ? (
          <p className="inline-error" role="alert">{conversationError}</p>
        ) : null}

        {isLoadingList ? (
          <div className="conversation-list-state" role="status">
            <ActivityIndicator state="processing" label="Loading conversations..." />
          </div>
        ) : listError ? (
          <div className="conversation-list-state" role="alert">
            <p>{listError}</p>
            <button
              type="button"
              className="ghost-button"
              onClick={handleRetryConversationList}
            >
              Retry
            </button>
          </div>
        ) : conversations.length === 0 ? (
          <div className="conversation-list-state">
            <p>No conversations yet.</p>
            <button
              type="button"
              className="ghost-button"
              onClick={() => void handleStartConversation()}
              disabled={isBusy}
            >
              Start your first conversation
            </button>
          </div>
        ) : (
          <ul className="conversation-list">
            {conversations.map((conversation) => (
              <li
                key={conversation.id}
                className={`conversation-list-item${
                  conversation.id === selectedConversationId ? " selected" : ""
                }`}
              >
                {editingConversationId === conversation.id ? (
                  <form
                    className="conversation-rename-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void handleRename(conversation.id);
                    }}
                  >
                    <label
                      className="visually-hidden"
                      htmlFor={`conversation-title-${conversation.id}`}
                    >
                      Conversation title
                    </label>
                    <input
                      id={`conversation-title-${conversation.id}`}
                      maxLength={120}
                      value={editedTitle}
                      onChange={(event) => setEditedTitle(event.target.value)}
                      disabled={isBusy}
                    />
                    <div className="conversation-item-actions">
                      <button type="submit" disabled={isBusy || !editedTitle.trim()}>
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingConversationId(null)}
                        disabled={isBusy}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <button
                      type="button"
                      className="conversation-select"
                      aria-current={
                        conversation.id === selectedConversationId ? "true" : undefined
                      }
                      onClick={() => {
                        if (conversation.id !== selectedConversationId) {
                          setDraft("");
                          selectConversation(conversation.id);
                        }
                      }}
                      disabled={isBusy}
                    >
                      <span>{conversation.title}</span>
                      <time dateTime={conversation.updated_at}>
                        {new Date(conversation.updated_at).toLocaleDateString()}
                      </time>
                    </button>
                    <div className="conversation-item-actions">
                      <button
                        type="button"
                        onClick={() => {
                          setEditedTitle(conversation.title);
                          setEditingConversationId(conversation.id);
                        }}
                        aria-label={`Rename ${conversation.title}`}
                        disabled={isBusy}
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        onClick={() => setConversationToDelete(conversation)}
                        aria-label={`Delete ${conversation.title}`}
                        disabled={isBusy}
                      >
                        Delete
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        {hasMoreConversations && !listError ? (
          <button
            type="button"
            className="ghost-button conversation-load-more"
            onClick={() => void handleLoadMore()}
            disabled={isBusy || isLoadingMore}
          >
            {isLoadingMore ? "Loading..." : "Load older conversations"}
          </button>
        ) : null}
        {olderConversationsError ? (
          <div className="conversation-list-state" role="alert">
            <p>{olderConversationsError}</p>
            <button
              type="button"
              className="ghost-button"
              onClick={() => void handleLoadMore()}
              disabled={isBusy}
            >
              Retry
            </button>
          </div>
        ) : null}
      </aside>

      <section className="chat-panel" aria-label="ATLAS chat interface">
        <div className="chat-header">
          <div>
            <p className="eyebrow">Assistant</p>
            <h2>{selectedConversation?.title ?? "ATLAS Conversation"}</h2>
          </div>
          {isSynthesisSupported ? (
            <div className="chat-header-actions">
              {isSpeaking ? (
                <div className="speaking-indicator" role="status">
                  <span aria-hidden="true">🔊</span>
                  <span>Speaking...</span>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => stopSpeaking()}
                    aria-label="Stop speaking response"
                  >
                    Stop
                  </button>
                </div>
              ) : null}
              <button
                type="button"
                className={`ghost-button speech-toggle ${voiceSettings.autoSpeak ? "active" : ""}`}
                onClick={() => toggleAutoSpeak()}
                aria-pressed={voiceSettings.autoSpeak}
                title={
                  voiceSettings.autoSpeak
                    ? "Voice responses are ON. Click to mute."
                    : "Voice responses are OFF. Click to hear responses."
                }
              >
                {voiceSettings.autoSpeak ? "🔊 Voice: ON" : "🔈 Voice: OFF"}
              </button>
            </div>
          ) : null}
        </div>

        {messageError ? (
          <div className="inline-error" role="alert">
            <p>{messageError}</p>
            {selectedConversationId ? (
              <button
                type="button"
                className="ghost-button"
                onClick={() => {
                  setMessageError(null);
                  setMessageRetryKey((current) => current + 1);
                }}
                disabled={isBusy}
              >
                Retry loading
              </button>
            ) : null}
          </div>
        ) : null}

        {isLoadingMessages ? (
          <div className="chat-empty-state" role="status">
            <ActivityIndicator state="processing" label="Loading messages..." />
          </div>
        ) : messages.length === 0 ? (
          <div className="chat-empty-state">
            <h3>{selectedConversationId ? "No messages yet" : "Start a conversation"}</h3>
            <p>
              {selectedConversationId
                ? "Ask ATLAS a question or get help planning, drafting, or summarizing."
                : "Choose a conversation from your history or start a new chat."}
            </p>
          </div>
        ) : (
          <div className="chat-message-list" aria-live="polite">
            {hasMoreMessages || olderMessagesError ? (
              <div className="chat-history-actions">
                {olderMessagesError ? (
                  <p role="alert">{olderMessagesError}</p>
                ) : null}
                {hasMoreMessages ? (
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => void handleLoadEarlierMessages()}
                    disabled={isBusy}
                  >
                    {isLoadingEarlier ? "Loading earlier messages..." : "Load earlier messages"}
                  </button>
                ) : null}
                {olderMessagesError ? (
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => void handleLoadEarlierMessages()}
                    disabled={isBusy}
                  >
                    Retry
                  </button>
                ) : null}
              </div>
            ) : null}
            {messages.map((message) => (
              <ChatMessageItem
                key={message.id}
                message={message}
                isSpeaking={isSpeaking && speakingMessageId === message.id}
                onSpeak={
                  isSynthesisSupported
                    ? () => speak(message.content, message.id)
                    : undefined
                }
                onStopSpeaking={
                  isSynthesisSupported ? () => stopSpeaking() : undefined
                }
              />
            ))}
          </div>
        )}

        {isProcessing ? (
          <div className="chat-status-inline">
            <ActivityIndicator state="processing" label="ATLAS is preparing a response..." />
          </div>
        ) : null}

        <form className="chat-composer" onSubmit={(event) => void handleSubmit(event)}>
          <label htmlFor="atlas-message" className="visually-hidden">
            Message ATLAS
          </label>

          {recognitionError ? (
            <div className="inline-error" role="alert">
              <p>{recognitionError}</p>
              <button
                type="button"
                className="ghost-button"
                onClick={() => clearRecognitionError()}
              >
                Dismiss
              </button>
            </div>
          ) : null}

          {recognitionState === "listening" ? (
            <div className="voice-status-panel" role="status" aria-live="polite">
              <div className="voice-status-indicator">
                <span className="recording-dot" aria-hidden="true" />
                <span>Listening... Speak your message</span>
              </div>
              {interimTranscript ? (
                <p className="voice-interim-text">
                  &ldquo;{interimTranscript}&rdquo;
                </p>
              ) : (
                <p className="voice-interim-text" style={{ color: "var(--muted)" }}>
                  Waiting for speech...
                </p>
              )}
              <div className="voice-status-actions">
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => stopListening()}
                >
                  Done speaking
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => cancelListening()}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}

          <div className="chat-input-row">
            <button
              type="button"
              className={`voice-button ${recognitionState === "listening" ? "recording" : ""}`}
              onClick={() => {
                if (recognitionState === "listening") {
                  stopListening();
                } else {
                  clearRecognitionError();
                  startListening((transcript) => {
                    setDraft((prev) => (prev ? `${prev} ${transcript}` : transcript));
                  });
                }
              }}
              disabled={
                isBusy ||
                !selectedConversationId ||
                !isRecognitionSupported
              }
              aria-label={
                !isRecognitionSupported
                  ? "Voice input not supported in this browser"
                  : recognitionState === "listening"
                    ? "Stop voice input"
                    : "Start voice input"
              }
              title={
                !isRecognitionSupported
                  ? "Voice input not supported in this browser"
                  : recognitionState === "listening"
                    ? "Click to stop listening"
                    : "Click to speak"
              }
            >
              {recognitionState === "listening" ? "🔴" : "🎙"}
            </button>
            <input
              id="atlas-message"
              type="text"
              maxLength={4000}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={
                recognitionState === "listening"
                  ? "Listening to your voice..."
                  : "Ask ATLAS anything..."
              }
              disabled={isBusy || !selectedConversationId}
              aria-label="Type your message to ATLAS"
            />
            <button
              type="submit"
              className="send-button"
              disabled={
                isBusy ||
                !selectedConversationId ||
                draft.trim().length === 0
              }
            >
              Send
            </button>
          </div>
        </form>
      </section>

      <ConfirmationDialog
        isOpen={conversationToDelete !== null}
        title="Delete conversation?"
        description="This permanently deletes the conversation and its messages."
        confirmLabel="Delete conversation"
        isLoading={isDeleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setConversationToDelete(null)}
      />
    </section>
  );
}
