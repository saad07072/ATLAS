import type { JSX } from "react";

import type { ChatMessage } from "@/types";

interface ChatMessageItemProps {
  message: ChatMessage;
}

export function ChatMessageItem({ message }: ChatMessageItemProps): JSX.Element {
  return (
    <div className={`chat-message ${message.role}`}>
      <div className="chat-message-meta">
        <span>{message.role === "user" ? "You" : "ATLAS"}</span>
        <time>{message.timestamp}</time>
      </div>
      <div className="chat-bubble">
        <p>{message.content}</p>
      </div>
    </div>
  );
}
