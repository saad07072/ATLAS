"use client";

import type { JSX } from "react";
import { useMemo, useState } from "react";

import { ActivityIndicator } from "@/components/ui/activity-indicator";
import { sendChatMessage } from "@/services/api";
import type { ChatMessage } from "@/types";

import { ChatMessageItem } from "./chat-message";

interface ChatPanelProps {
  initialMessages?: ChatMessage[];
}

export function ChatPanel({ initialMessages = [] }: ChatPanelProps): JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [draft, setDraft] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEmptyConversation = useMemo(() => messages.length === 0, [messages]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const trimmed = draft.trim();

    if (!trimmed || isProcessing) {
      return;
    }

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      timestamp: "Now",
    };

    setMessages((currentMessages) => [...currentMessages, userMessage]);
    setDraft("");
    setError(null);
    setIsProcessing(true);

    try {
      const response = await sendChatMessage(
        trimmed,
        messages.slice(-12).map(({ role, content }) => ({ role, content })),
      );
      setMessages((currentMessages) => [
        ...currentMessages,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: response.message,
          timestamp: "Just now",
        },
      ]);
    } catch {
      setError("ATLAS could not complete this response. Please try again.");
    } finally {
      setIsProcessing(false);
    }
  }

  return (
    <section className="chat-panel" aria-label="ATLAS chat interface">
      <div className="chat-header">
        <div>
          <p className="eyebrow">Assistant</p>
          <h2>ATLAS Conversation</h2>
        </div>
        <button
          type="button"
          className="ghost-button"
          aria-label="Start a new chat"
          onClick={() => {
            setMessages([]);
            setError(null);
          }}
        >
          New chat
        </button>
      </div>

      {error ? <div className="inline-error">{error}</div> : null}

      {isEmptyConversation ? (
        <div className="chat-empty-state">
          <h3>No messages yet</h3>
          <p>Ask ATLAS a question or get help planning, drafting, or summarizing.</p>
        </div>
      ) : (
        <div className="chat-message-list" aria-live="polite">
          {messages.map((message) => (
            <ChatMessageItem key={message.id} message={message} />
          ))}
        </div>
      )}

      {isProcessing ? (
        <div className="chat-status-inline">
          <ActivityIndicator state="processing" label="ATLAS is preparing a response..." />
        </div>
      ) : null}

      <form className="chat-composer" onSubmit={handleSubmit}>
        <label htmlFor="atlas-message" className="visually-hidden">
          Message ATLAS
        </label>

        <div className="chat-input-row">
          <button type="button" className="voice-button" aria-label="Voice input placeholder">
            Voice
          </button>

          <input
            id="atlas-message"
            type="text"
            maxLength={4000}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask ATLAS anything..."
            disabled={isProcessing}
            aria-label="Type your message to ATLAS"
          />

          <button type="submit" className="send-button" disabled={isProcessing || draft.trim().length === 0}>
            Send
          </button>
        </div>
      </form>
    </section>
  );
}
