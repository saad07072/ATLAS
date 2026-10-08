"use client";

import type { JSX } from "react";
import { useEffect, useState } from "react";

import { apiBaseUrl, getGoogleConnectionStatus } from "@/services/api";
import type { GoogleConnectionStatus } from "@/services/api";
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
  const [googleStatus, setGoogleStatus] = useState<GoogleConnectionStatus | null>(null);
  const [googleStatusUnavailable, setGoogleStatusUnavailable] = useState(false);

  useEffect(() => {
    let active = true;
    void getGoogleConnectionStatus()
      .then((status) => {
        if (active) {
          setGoogleStatus(status);
        }
      })
      .catch(() => {
        if (active) {
          setGoogleStatusUnavailable(true);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Connected services</p>
          <h2>Connect Google services</h2>
        </div>
      </header>

      <section className="service-grid" aria-label="Connected services list">
        {services.map((service) => {
          const isGoogle =
            service.id === "google-calendar" || service.id === "gmail";
          const isConnected = googleStatus?.connected === true;
          const status = isGoogle
            ? googleStatus === null || googleStatusUnavailable
              ? "Unavailable"
              : isConnected
                ? "Connected"
                : "Disconnected"
            : service.status;

          return (
            <article key={service.id} className="service-card">
              <div className="service-card-header">
                <h3>{service.name}</h3>
                <span className={`status-badge ${status.toLowerCase()}`}>
                  {status}
                </span>
              </div>
              <p>{service.description}</p>
              {service.id === "google-calendar" &&
                googleStatusUnavailable && (
                  <p role="status">
                    Google connection status is unavailable. Check that the
                    backend is reachable.
                  </p>
                )}
              {service.id === "google-calendar" ? (
                googleStatus?.configured && !isConnected ? (
                  <a
                    className="ghost-button"
                    href={`${apiBaseUrl}/api/v1/google/oauth/start`}
                  >
                    Connect Google
                  </a>
                ) : (
                  <button type="button" className="ghost-button" disabled>
                    {isConnected ? "Google connected" : "Connect unavailable"}
                  </button>
                )
              ) : (
                <button type="button" className="ghost-button" disabled>
                  {service.id === "gmail" && isConnected
                    ? "Uses Google connection"
                    : "Connect unavailable"}
                </button>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}
