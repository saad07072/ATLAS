"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { FormEvent, JSX } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { isSupabaseConfigured } from "@/services/supabase";

function SignInForm(): JSX.Element {
  const {
    status,
    error: authError,
    signInWithMagicLink,
    refreshSession,
  } = useAuth();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const callbackError =
    useSearchParams().get("error") === "auth_callback";
  const supabaseConfigured = isSupabaseConfigured();

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError(null);
    setMessage(null);
    try {
      await signInWithMagicLink(email.trim());
      setMessage(
        "If this address can sign in, a secure link has been sent. Check your inbox.",
      );
    } catch (submitError) {
      setFormError(
        submitError instanceof Error
          ? submitError.message
          : "Could not send a sign-in link.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="sign-in-title">
        <p className="eyebrow">ATLAS account</p>
        <h1 id="sign-in-title">Sign in</h1>
        <p>We’ll email you a secure sign-in link.</p>

        {status === "loading" && (
          <p role="status">Checking authentication configuration…</p>
        )}
        {(authError || callbackError) && (
          <p className="inline-error" role="alert">
            {callbackError
              ? "That sign-in link could not be verified. Request a new one."
              : authError}
          </p>
        )}
        {status === "error" && supabaseConfigured && (
          <button
            type="button"
            className="ghost-button"
            onClick={() => void refreshSession()}
          >
            Retry session check
          </button>
        )}
        {message && <p className="auth-success" role="status">{message}</p>}
        {formError && <p className="inline-error" role="alert">{formError}</p>}

        <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
          <label htmlFor="sign-in-email">Email address</label>
          <input
            id="sign-in-email"
            type="email"
            autoComplete="email"
            maxLength={254}
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isSubmitting || !supabaseConfigured}
          />
          <button
            type="submit"
            className="primary-button"
            disabled={isSubmitting || !supabaseConfigured}
          >
            {isSubmitting ? "Sending link…" : "Email me a sign-in link"}
          </button>
        </form>
        <Link className="auth-back-link" href="/">
          Return to ATLAS
        </Link>
      </section>
    </main>
  );
}

export default function SignInPage(): JSX.Element {
  return (
    <Suspense
      fallback={
        <main className="auth-state" role="status">
          Preparing sign-in…
        </main>
      }
    >
      <SignInForm />
    </Suspense>
  );
}
