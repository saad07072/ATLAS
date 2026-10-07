import type { JSX } from "react";

import { ChatPanel } from "@/components/chat/chat-panel";

export default function HomePage(): JSX.Element {
  return (
    <div className="page-shell">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Welcome back</p>
          <h2>What can ATLAS help you do today?</h2>
        </div>
        <div className="hero-actions">
          <button type="button" className="primary-button">
            Create task
          </button>
          <button type="button" className="ghost-button">
            Review agenda
          </button>
        </div>
      </section>

      <ChatPanel />
    </div>
  );
}
