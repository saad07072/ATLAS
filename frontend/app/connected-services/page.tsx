import type { JSX } from "react";

import type { ServiceStatus } from "@/types";

const services: ServiceStatus[] = [
  {
    id: "google-calendar",
    name: "Google Calendar",
    status: "Disconnected",
    description: "Upcoming events, meeting availability, and scheduling context.",
  },
  {
    id: "gmail",
    name: "Gmail",
    status: "Unavailable",
    description: "Email summaries, follow-up tasks, and communication triage.",
  },
  {
    id: "github",
    name: "GitHub",
    status: "Connected",
    description: "Repository activity, pull requests, and issue awareness.",
  },
];

export default function ConnectedServicesPage(): JSX.Element {
  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Connected services</p>
          <h2>Integrations ready for future phases</h2>
        </div>
      </header>

      <section className="service-grid" aria-label="Connected services list">
        {services.map((service) => (
          <article key={service.id} className="service-card">
            <div className="service-card-header">
              <h3>{service.name}</h3>
              <span className={`status-badge ${service.status.toLowerCase()}`}>
                {service.status}
              </span>
            </div>
            <p>{service.description}</p>
            <button type="button" className="ghost-button" disabled>
              Connect unavailable
            </button>
          </article>
        ))}
      </section>
    </div>
  );
}
