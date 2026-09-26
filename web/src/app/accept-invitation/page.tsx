"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Alert, Field } from "@/components/ui";
import { api, setToken } from "@/lib/api";
import { describeError, useSession } from "@/lib/session";

/**
 * Where a staff invitation lands (PRD 6). Someone who already has an Estock
 * account keeps their password; a new person chooses one here.
 */
export default function AcceptInvitationPage() {
  return (
    <Suspense fallback={<div className="auth"><p className="muted">Loading…</p></div>}>
      <AcceptInvitation />
    </Suspense>
  );
}

function AcceptInvitation() {
  const params = useSearchParams();
  const router = useRouter();
  const { refresh } = useSession();
  const token = params.get("token") ?? "";
  const [existing, setExisting] = useState(false);
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.acceptInvitation({
        token,
        password: existing ? undefined : password,
        full_name: fullName || undefined,
      });
      setToken(result.access_token);
      await refresh();
      router.replace("/");
    } catch (cause) {
      setError(describeError(cause, "Could not accept the invitation"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="card">
        <h1>Join the team</h1>
        <p className="sub">You have been invited to work in a business on Estock.</p>
        <Alert>{!token ? "This link is missing its token." : error}</Alert>
        <form onSubmit={onSubmit}>
          <label className="toggle">
            <input type="checkbox" checked={existing} onChange={(e) => setExisting(e.target.checked)} />
            <span>I already have an Estock account with this email</span>
          </label>
          {!existing && (
            <>
              <Field label="Your name" hint="optional">
                <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
              </Field>
              <Field label="Choose a password" hint="at least 8 characters">
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
              </Field>
            </>
          )}
          <button type="submit" disabled={busy || !token} style={{ width: "100%" }}>
            {busy ? "Joining…" : "Accept invitation"}
          </button>
        </form>
        <p className="sub" style={{ marginTop: 16, marginBottom: 0 }}>
          <Link href="/sign-in">Sign in instead</Link>
        </p>
      </div>
    </div>
  );
}
