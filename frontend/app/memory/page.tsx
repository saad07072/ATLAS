import type { JSX } from "react";

import type { MemoryItem } from "@/types";

const memoryItems: MemoryItem[] = [
  {
    id: "mem-1",
    title: "Project priorities",
    summary: "High-level goals for the current planning cycle and key deadlines.",
    category: "Planning",
    updatedAt: "Today, 09:14",
    status: "Active",
  },
  {
    id: "mem-2",
    title: "Personal routines",
    summary: "Recurring work patterns and meeting blocks that should be respected.",
    category: "Lifestyle",
    updatedAt: "Yesterday",
    status: "Draft",
  },
  {
    id: "mem-3",
    title: "Tool usage history",
    summary: "Recent tasks, integrations, and system interactions queued for future review.",
    category: "System",
    updatedAt: "2 days ago",
    status: "Needs Review",
  },
];

export default function MemoryPage(): JSX.Element {
  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Memory</p>
          <h2>Context and knowledge foundation</h2>
        </div>
        <button type="button" className="ghost-button">Add memory</button>
      </header>

      <section className="memory-list" aria-label="Memory items">
        {memoryItems.map((item) => (
          <article key={item.id} className="memory-card">
            <div className="memory-card-header">
              <span className="memory-category">{item.category}</span>
              <span className={`status-badge ${item.status.toLowerCase().replace(/\s+/g, "-")}`}>
                {item.status}
              </span>
            </div>
            <h3>{item.title}</h3>
            <p>{item.summary}</p>
            <div className="meta-row">
              <span>Updated {item.updatedAt}</span>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}
