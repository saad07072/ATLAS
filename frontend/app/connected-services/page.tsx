"use client";

import type { JSX } from "react";
import { useEffect, useState } from "react";

import {
  disconnectGoogleConnection,
  getGitHubConnectionStatus,
  getGoogleConnectionStatus,
  getGoogleOAuthStartUrl,
} from "@/services/api";
import type {
  GitHubConnectionStatus,
  GoogleConnectionStatus,
} from "@/services/api";
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
    status: "Disconnected",
    description: "Repository, issue, and pull-request information.",
  },
];

export default function ConnectedServicesPage(): JSX.Element {
  const [googleStatus, setGoogleStatus] = useState<GoogleConnectionStatus | null>(null);
  const [googleStatusUnavailable, setGoogleStatusUnavailable] = useState(false);
  const [googleActionPending, setGoogleActionPending] = useState(false);
  const [googleActionError, setGoogleActionError] = useState<string | null>(null);
  const [githubStatus, setGithubStatus] = useState<GitHubConnectionStatus | null>(null);
  const [githubStatusUnavailable, setGithubStatusUnavailable] = useState(false);

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

  useEffect(() => {
    let active = true;
    void getGitHubConnectionStatus()
      .then((status) => {
        if (active) {
          setGithubStatus(status);
        }
      })
      .catch(() => {
        if (active) {
          setGithubStatusUnavailable(true);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function connectGoogle(): Promise<void> {
    setGoogleActionPending(true);
    setGoogleActionError(null);
    try {
      const authorizationUrl = await getGoogleOAuthStartUrl();
      window.location.assign(authorizationUrl);
    } catch (error) {
      setGoogleActionError(
        error instanceof Error ? error.message : "Google could not be connected.",
      );
      setGoogleActionPending(false);
    }
  }

  async function disconnectGoogle(): Promise<void> {
    if (!window.confirm("Disconnect this Google account from ATLAS?")) {
      return;
    }
    setGoogleActionPending(true);
    setGoogleActionError(null);
    try {
      await disconnectGoogleConnection();
      setGoogleStatus((current) =>
        current ? { ...current, connected: false } : current,
      );
    } catch (error) {
      setGoogleActionError(
        error instanceof Error
          ? error.message
          : "Google could not be disconnected.",
      );
    } finally {
      setGoogleActionPending(false);
    }
  }

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
          const isGitHub = service.id === "github";
          const isConnected = googleStatus?.connected === true;
          const status = isGoogle
            ? googleStatus === null || googleStatusUnavailable
              ? "Unavailable"
              : isConnected
                ? "Connected"
                : googleStatus.actions_enabled
                  ? "Disconnected"
                  : "Unavailable"
            : isGitHub
              ? githubStatus === null || githubStatusUnavailable
                ? "Unavailable"
                : githubStatus.connected
                  ? "Connected"
                  : githubStatus.actions_enabled
                    ? "Disconnected"
                    : "Unavailable"
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
              {isGitHub && githubStatusUnavailable && (
                <p role="status">
                  GitHub connection status is unavailable. Check that the
                  backend is reachable.
                </p>
              )}
              {service.id === "google-calendar" ? (
                <button
                  type="button"
                  className="ghost-button"
                  disabled={
                    googleActionPending ||
                    googleStatus === null ||
                    googleStatusUnavailable ||
                    !googleStatus.configured
                  }
                  onClick={() => {
                    if (isConnected) {
                      void disconnectGoogle();
                    } else {
                      void connectGoogle();
                    }
                  }}
                >
                  {googleActionPending
                    ? "Working..."
                    : isConnected
                      ? "Disconnect Google"
                      : googleStatus?.configured
                        ? "Connect Google"
                        : "Google is not configured"}
                </button>
              ) : (
                <button type="button" className="ghost-button" disabled>
                  {service.id === "gmail"
                    ? isConnected
                      ? "Uses Google connection"
                      : "Per-user connection unavailable"
                    : githubStatus?.connected
                      ? "GitHub App configured"
                      : "Per-user connection unavailable"}
                </button>
              )}
              {service.id === "google-calendar" && isConnected && (
                <p>
                  Account connected. Google actions remain disabled until
                  user-bound tool authorization is available.
                </p>
              )}
              {service.id === "google-calendar" && googleActionError && (
                <p role="alert">{googleActionError}</p>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}
