"use client";

import type { JSX } from "react";
import { useMemo, useState } from "react";

import { ActivityIndicator } from "@/components/ui/activity-indicator";
import type { ChatMessage } from "@/types";

import { ChatMessageItem } from "./chat-message";

const defaultMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "Hello. I am ATLAS, your task and life assistant foundation. Ask for a task, a plan, or a quick status update.",
    timestamp: "Now",
  },
  {
    id: "intro",
    role: "user",
    content: "Summarize my day and help me prioritize the most important task.",
    timestamp: "Just now",
  },
];

interface ChatPanelProps {
  initialMessages?: ChatMessage[];
}

export function ChatPanel({ initialMessages = defaultMessages }: ChatPanelProps): JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [draft, setDraft] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEmptyConversation = useMemo(() => messages.length === 0, [messages]);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
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

    window.setTimeout(() => {
      const response = {
        id: `assistant-${Date.now()}`,
        role: "assistant" as const,
        content: `ATLAS has received your request: “${trimmed}”. This message is being prepared for the next phase when the real agent and tool layer are connected.`,
        timestamp: "Just now",
      };

      setMessages((currentMessages) => [...currentMessages, response]);
      setIsProcessing(false);
    }, 650);
  }

  return (
    <section className="chat-panel" aria-label="ATLAS chat interface">
      <div className="chat-header">
        <div>
          <p className="eyebrow">Assistant</p>
          <h2>ATLAS Conversation</h2>
        </div>
        <button type="button" className="ghost-button" aria-label="Start a new chat">
          New chat
        </button>
      </div>

      {error ? <div className="inline-error">{error}</div> : null}

      {isEmptyConversation ? (
        <div className="chat-empty-state">
          <h3>No messages yet</h3>
          <p>Ask ATLAS to capture a task, summarize context, or outline the next action.</p>
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
