import type { JSX } from "react";

import type { ChatMessage } from "@/types";

interface ChatMessageItemProps {
  message: ChatMessage;
  isSpeaking?: boolean;
  onSpeak?: () => void;
  onStopSpeaking?: () => void;
}

export function ChatMessageItem({
  message,
  isSpeaking = false,
  onSpeak,
  onStopSpeaking,
}: ChatMessageItemProps): JSX.Element {
  const isAssistant = message.role === "assistant";

  return (
    <div className={`chat-message ${message.role}`}>
      <div className="chat-message-meta">
        <span>{isAssistant ? "ATLAS" : "You"}</span>
        <time>{message.timestamp}</time>
        {isAssistant && onSpeak && (
          <button
            type="button"
            className="message-speak-button"
            onClick={isSpeaking ? onStopSpeaking : onSpeak}
            aria-label={
              isSpeaking
                ? "Stop reading response aloud"
                : "Read response aloud"
            }
            title={isSpeaking ? "Stop" : "Read aloud"}
          >
            {isSpeaking ? (
              <>
                <span className="speak-icon stop-icon" aria-hidden="true">■</span>
                <span>Stop</span>
              </>
            ) : (
              <>
                <span className="speak-icon" aria-hidden="true">🔊</span>
                <span>Listen</span>
              </>
            )}
          </button>
        )}
      </div>
      <div className="chat-bubble">
        <p>{message.content}</p>
      </div>
    </div>
  );
}
