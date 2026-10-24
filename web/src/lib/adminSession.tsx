"use client";

/**
 * Who is signed in to the platform console.
 *
 * Deliberately not the shop's `SessionProvider`. The operator and a shop user
 * are different identities against different tables, and keeping the two
 * contexts apart is what stops one signing the other in or out (PRD 5.2).
 */

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError } from "@/lib/api";
import { adminApi, getAdminToken, setAdminToken, type AdminUser } from "@/lib/admin";

const STORED_ADMIN = "estock.admin.who";

type AdminState = {
  admin: AdminUser | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
};

const AdminContext = createContext<AdminState | null>(null);

function readStored(): AdminUser | null {
  try {
    const raw = window.localStorage.getItem(STORED_ADMIN);
    return raw ? (JSON.parse(raw) as AdminUser) : null;
  } catch {
    return null;
  }
}

function writeStored(admin: AdminUser | null): void {
  try {
    if (admin) window.localStorage.setItem(STORED_ADMIN, JSON.stringify(admin));
    else window.localStorage.removeItem(STORED_ADMIN);
  } catch {
    // Private mode: the console works, it just forgets the name on reload.
  }
}

export function AdminProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [admin, setAdmin] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(true);

  // There is no "who am I" endpoint for an operator, so the name is kept
  // beside the token and the token is what actually proves anything — every
  // call below re-checks it with the server.
  useEffect(() => {
    if (!getAdminToken()) {
      setAdmin(null);
      setLoading(false);
      return;
    }
    setAdmin(readStored());
    setLoading(false);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await adminApi.signIn(email, password);
    setAdminToken(result.access_token);
    writeStored(result.admin);
    setAdmin(result.admin);
  }, []);

  const signOut = useCallback(() => {
    setAdminToken(null);
    writeStored(null);
    setAdmin(null);
    router.push("/admin/sign-in");
  }, [router]);

  const value = useMemo(
    () => ({ admin, loading, signIn, signOut }),
    [admin, loading, signIn, signOut],
  );
  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
}

export function useAdmin(): AdminState {
  const value = useContext(AdminContext);
  if (!value) throw new Error("useAdmin must be used inside AdminProvider");
  return value;
}

/**
 * Turn an expired or missing operator token into a sign-in, and anything else
 * into a message. A 401 here means the console session lapsed, not that the
 * operator lacks permission.
 */
export function useAdminCall(signOut: () => void) {
  return useCallback(
    (cause: unknown, fallback: string): string => {
      if (cause instanceof ApiError && cause.isAuthError) {
        signOut();
        return "Your console session expired. Sign in again.";
      }
      return cause instanceof Error ? cause.message : fallback;
    },
    [signOut],
  );
}
