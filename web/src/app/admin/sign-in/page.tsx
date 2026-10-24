"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, Field } from "@/components/ui";
import { useAdmin } from "@/lib/adminSession";

export default function AdminSignInPage() {
  const { signIn, admin } = useAdmin();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (admin) router.replace("/admin");
  }, [admin, router]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
      router.replace("/admin");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="card">
        <h1>Platform console</h1>
        <p className="sub">
          For the operator of this platform. A shop owner signs in on the{" "}
          <a href="/sign-in">main sign-in page</a> instead — this is a separate
          account.
        </p>

        <Alert>{error}</Alert>

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
          <Field label="Password">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
          <button type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
