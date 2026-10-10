"use client";

import type { Session } from "@supabase/supabase-js";
import type { JSX, ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  getSupabaseBrowserClient,
  isSupabaseConfigured,
} from "@/services/supabase";

export type AuthStatus =
  | "loading"
  | "authenticated"
  | "unauthenticated"
  | "error";

interface AuthContextValue {
  status: AuthStatus;
  email: string | null;
  error: string | null;
  signInWithMagicLink: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function toSafeAuthError(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Authentication is temporarily unavailable.";
}

function applySession(
  session: Session | null,
  setStatus: (status: AuthStatus) => void,
  setEmail: (email: string | null) => void,
): void {
  setStatus(session ? "authenticated" : "unauthenticated");
  setEmail(session?.user.email ?? null);
}

export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [status, setStatus] = useState<AuthStatus>(() =>
    isSupabaseConfigured() ? "loading" : "error",
  );
  const [email, setEmail] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(() =>
    isSupabaseConfigured() ? null : "Supabase authentication is not configured.",
  );

  const refreshSession = useCallback(async (): Promise<void> => {
    if (!isSupabaseConfigured()) {
      setStatus("error");
      setError("Supabase authentication is not configured.");
      return;
    }
    try {
      const { data, error: sessionError } =
        await getSupabaseBrowserClient().auth.getSession();
      if (sessionError) {
        throw sessionError;
      }
      applySession(data.session, setStatus, setEmail);
      setError(null);
    } catch (sessionError) {
      setStatus("error");
      setEmail(null);
      setError(toSafeAuthError(sessionError));
    }
  }, []);

  useEffect(() => {
    if (!isSupabaseConfigured()) {
      return;
    }

    let active = true;
    let subscription: { unsubscribe: () => void } | null = null;
    void Promise.resolve()
      .then(() => {
        const client = getSupabaseBrowserClient();
        const authState = client.auth.onAuthStateChange((_event, session) => {
          applySession(session, setStatus, setEmail);
          setError(null);
        });
        subscription = authState.data.subscription;
        return client.auth.getSession();
      })
      .then(({ data, error: sessionError }) => {
        if (!active) {
          return;
        }
        if (sessionError) {
          setStatus("error");
          setError(toSafeAuthError(sessionError));
          return;
        }
        applySession(data.session, setStatus, setEmail);
        setError(null);
      })
      .catch((sessionError: unknown) => {
        if (active) {
          setStatus("error");
          setError(toSafeAuthError(sessionError));
        }
      });
    return () => {
      active = false;
      subscription?.unsubscribe();
    };
  }, []);

  const signInWithMagicLink = useCallback(async (address: string): Promise<void> => {
    const { error: signInError } = await getSupabaseBrowserClient().auth.signInWithOtp({
      email: address,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });
    if (signInError) {
      throw new Error(signInError.message);
    }
  }, []);

  const signOut = useCallback(async (): Promise<void> => {
    const { error: signOutError } = await getSupabaseBrowserClient().auth.signOut();
    if (signOutError) {
      throw new Error("Could not sign out. Please try again.");
    }
    setEmail(null);
    setStatus("unauthenticated");
  }, []);

  const value = useMemo(
    () => ({
      status,
      email,
      error,
      signInWithMagicLink,
      signOut,
      refreshSession,
    }),
    [status, email, error, signInWithMagicLink, signOut, refreshSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return context;
}
