import type { JSX } from "react";

import type { SettingGroup } from "@/types";

const settingGroups: SettingGroup[] = [
  {
    id: "account",
    title: "Account",
    description: "Identity and profile information for future user management.",
    state: "Placeholder",
  },
  {
    id: "preferences",
    title: "Preferences",
    description: "Daily workflow, task conventions, and interface choices.",
    state: "Configuration",
  },
  {
    id: "appearance",
    title: "Appearance",
    description: "Theme and display preferences for a calm, focused experience.",
    state: "Theme ready",
  },
  {
    id: "notifications",
    title: "Notifications",
    description: "Delivery preferences for reminders, approvals, and summaries.",
    state: "Planned",
  },
  {
    id: "privacy",
    title: "Privacy",
    description: "Data handling boundaries and consent controls for future phases.",
    state: "Draft",
  },
  {
    id: "integrations",
    title: "Connected services",
    description: "Status and configuration for external platforms linked later.",
    state: "Not connected",
  },
];

export default function SettingsPage(): JSX.Element {
  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h2>System preferences</h2>
        </div>
      </header>

      <section className="settings-grid" aria-label="Settings categories">
        {settingGroups.map((setting) => (
          <article key={setting.id} className="setting-card">
            <div className="setting-card-header">
              <h3>{setting.title}</h3>
              <span className="meta-pill">{setting.state}</span>
            </div>
            <p>{setting.description}</p>
          </article>
        ))}
      </section>
    </div>
  );
}
