"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, setToken } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Alert, Field } from "@/components/ui";

/**
 * Registration collects only what is needed to start: the business, the owner
 * and a password. The first branch is created automatically (PRD 6).
 */
export default function RegisterPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [form, setForm] = useState({
    business_name: "",
    full_name: "",
    email: "",
    password: "",
    phone: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function update(key: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((prev) => ({ ...prev, [key]: event.target.value }));
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.register({
        ...form,
        phone: form.phone || undefined,
      });
      setToken(result.access_token);
      await refresh();
      router.replace("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="card">
        <h1>Create your business</h1>
        <p className="sub">
          Takes a minute. Your first branch is set up for you — you can rename it
          and add more later.
        </p>

        <Alert>{error}</Alert>

        <form onSubmit={onSubmit}>
          <Field label="Business name">
            <input value={form.business_name} onChange={update("business_name")} required />
          </Field>
          <Field label="Your name">
            <input value={form.full_name} onChange={update("full_name")} required />
          </Field>
          <Field label="Email">
            <input
              type="email"
              value={form.email}
              onChange={update("email")}
              autoComplete="email"
              required
            />
          </Field>
          <Field label="Phone" hint="optional">
            <input
              value={form.phone}
              onChange={update("phone")}
              placeholder="0911234567"
              inputMode="tel"
            />
          </Field>
          <Field label="Password" hint="at least 8 characters">
            <input
              type="password"
              value={form.password}
              onChange={update("password")}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </Field>
          <button type="submit" disabled={busy} style={{ width: "100%" }}>
            {busy ? "Creating…" : "Create business"}
          </button>
        </form>

        <p className="sub" style={{ marginTop: 16, marginBottom: 0 }}>
          Already registered? <Link href="/sign-in">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
