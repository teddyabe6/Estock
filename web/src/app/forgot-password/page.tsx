"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert, Field } from "@/components/ui";
import { api } from "@/lib/api";
import { describeError } from "@/lib/session";

/** Account recovery, step one (PRD 20). The reply never reveals whether an address exists. */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.requestPasswordReset(email);
      setDone(`${result.message} ${result.detail ?? ""}`.trim());
    } catch (cause) {
      setError(describeError(cause, "Could not send the reset link"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="card">
        <h1>Forgot your password?</h1>
        <p className="sub">Enter your email and we will send a link to choose a new one.</p>
        <Alert>{error}</Alert>
        {done ? (
          <Alert kind="ok">{done}</Alert>
        ) : (
          <form onSubmit={onSubmit}>
            <Field label="Email">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </Field>
            <button type="submit" disabled={busy} style={{ width: "100%" }}>
              {busy ? "Sending…" : "Send reset link"}
            </button>
          </form>
        )}
        <p className="sub" style={{ marginTop: 16, marginBottom: 0 }}>
          <Link href="/sign-in">Back to sign in</Link>
        </p>
      </div>
    </div>
  );
}
