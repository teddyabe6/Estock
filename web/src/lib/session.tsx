"use client";

/** Session context: who is signed in, and what they may see. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";

import { ApiError, api, getToken, setToken, type Session } from "./api";

type SessionState = {
  session: Session | null;
  loading: boolean;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  refresh: () => Promise<void>;
  /** Permission check mirroring the server's; the server still decides. */
  can: (permission: string) => boolean;
};

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setSession(null);
      setLoading(false);
      return;
    }
    try {
      setSession(await api.session());
      setError(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.isAuthError) {
        setToken(null);
        setSession(null);
      } else {
        setError(cause instanceof Error ? cause.message : "Something went wrong");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const result = await api.login(email, password);
      setToken(result.access_token);
      setSession(await api.session());
      setError(null);
    },
    [],
  );

  const signOut = useCallback(() => {
    setToken(null);
    setSession(null);
    router.push("/sign-in");
  }, [router]);

  const can = useCallback(
    (permission: string) => session?.permissions.includes(permission) ?? false,
    [session],
  );

  const value = useMemo(
    () => ({ session, loading, error, signIn, signOut, refresh, can }),
    [session, loading, error, signIn, signOut, refresh, can],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used inside a SessionProvider");
  }
  return context;
}
