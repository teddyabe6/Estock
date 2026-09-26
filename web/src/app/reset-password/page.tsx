"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Alert, Field } from "@/components/ui";
import { api } from "@/lib/api";
import { describeError } from "@/lib/session";

/** Account recovery, step two: the link from the email lands here. */
export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="auth"><p className="muted">Loading…</p></div>}>
      <ResetPassword />
    </Suspense>
  );
}

function ResetPassword() {
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.confirmPasswordReset(token, password);
      setDone(result.message);
    } catch (cause) {
      setError(describeError(cause, "Could not change the password"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="card">
        <h1>Choose a new password</h1>
        <Alert>{!token ? "This link is missing its token. Request a new one." : error}</Alert>
        {done ? (
          <>
            <Alert kind="ok">{done}</Alert>
            <Link href="/sign-in">
              <button type="button" style={{ width: "100%" }}>
                Sign in
              </button>
            </Link>
          </>
        ) : (
          <form onSubmit={onSubmit}>
            <Field label="New password" hint="at least 8 characters">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </Field>
            <Field label="Repeat it">
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </Field>
            <button type="submit" disabled={busy || !token} style={{ width: "100%" }}>
              {busy ? "Saving…" : "Change password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
