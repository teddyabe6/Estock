"use client";

/** The plans shops can be put on: what each costs and what it allows. */

import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "@/components/AdminShell";
import { Alert, Empty, Field, PageHead } from "@/components/ui";
import { adminApi, type Plan } from "@/lib/admin";
import { useAdmin, useAdminCall } from "@/lib/adminSession";
import { money } from "@/lib/format";

export default function AdminPlansPage() {
  const { admin, signOut } = useAdmin();
  const describe = useAdminCall(signOut);

  const [plans, setPlans] = useState<Plan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setPlans(await adminApi.plans());
      setError(null);
    } catch (cause) {
      setError(describe(cause, "Could not load the plans"));
    }
  }, [describe]);

  useEffect(() => {
    if (admin) void load();
  }, [admin, load]);

  return (
    <AdminShell>
      <PageHead
        title="Plans"
        subtitle="What a shop pays, and what it is allowed"
        actions={
          <button type="button" className="secondary" onClick={() => setAdding(!adding)}>
            {adding ? "Cancel" : "New plan"}
          </button>
        }
      />

      <Alert>{error}</Alert>
      {notice && <Alert kind="ok">{notice}</Alert>}

      {adding && (
        <NewPlan
          busy={busy}
          onCreate={async (body) => {
            setBusy(true);
            setError(null);
            try {
              const created = await adminApi.createPlan(body);
              setNotice(`Created ${created.code}.`);
              setAdding(false);
              await load();
            } catch (cause) {
              setError(describe(cause, "Could not create the plan"));
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      <p className="muted">
        A blank ceiling means unlimited. A shop already over a ceiling keeps everything
        it has — only its next addition is refused, so moving someone to a smaller plan
        never takes their data away.
      </p>

      {plans.length === 0 ? (
        <Empty title="No plans yet">
          Create one, then put shops on it so they have a price to be billed.
        </Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Plan</th>
              <th>Code</th>
              <th className="num">Per month</th>
              <th className="num">Branches</th>
              <th className="num">Users</th>
              <th className="num">Products</th>
              <th>Offered</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((plan) => (
              <tr key={plan.id}>
                <td>{plan.name}</td>
                <td className="muted">{plan.code}</td>
                <td className="num">{money(plan.monthly_price, plan.currency)}</td>
                <td className="num">{plan.max_branches ?? "any"}</td>
                <td className="num">{plan.max_users ?? "any"}</td>
                <td className="num">{plan.max_products ?? "any"}</td>
                <td>
                  <span className={plan.is_active ? "badge ok" : "badge muted"}>
                    {plan.is_active ? "yes" : "no"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AdminShell>
  );
}

function NewPlan({
  busy,
  onCreate,
}: {
  busy: boolean;
  onCreate: (body: Record<string, unknown>) => void;
}) {
  const [form, setForm] = useState({
    code: "",
    name: "",
    description: "",
    monthly_price: "0",
    max_branches: "",
    max_users: "",
    max_products: "",
  });

  const set = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: event.target.value });

  const ceiling = (value: string) => (value.trim() === "" ? null : Number(value));

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        onCreate({
          code: form.code.trim(),
          name: form.name.trim(),
          description: form.description || undefined,
          monthly_price: Number(form.monthly_price),
          max_branches: ceiling(form.max_branches),
          max_users: ceiling(form.max_users),
          max_products: ceiling(form.max_products),
        });
      }}
    >
      <div className="card-title">New plan</div>
      <div className="grid">
        <Field label="Name">
          <input value={form.name} onChange={set("name")} required minLength={2} />
        </Field>
        <Field label="Code" hint="short, lowercase, never changes">
          <input value={form.code} onChange={set("code")} required minLength={2} />
        </Field>
        <Field label="Price per month">
          <input value={form.monthly_price} onChange={set("monthly_price")} inputMode="decimal" required />
        </Field>
      </div>
      <Field label="Description">
        <input value={form.description} onChange={set("description")} />
      </Field>
      <div className="grid">
        <Field label="Max branches" hint="blank for unlimited">
          <input value={form.max_branches} onChange={set("max_branches")} inputMode="numeric" />
        </Field>
        <Field label="Max users" hint="blank for unlimited">
          <input value={form.max_users} onChange={set("max_users")} inputMode="numeric" />
        </Field>
        <Field label="Max products" hint="blank for unlimited">
          <input value={form.max_products} onChange={set("max_products")} inputMode="numeric" />
        </Field>
      </div>
      <button type="submit" disabled={busy}>
        {busy ? "Creating…" : "Create plan"}
      </button>
    </form>
  );
}
