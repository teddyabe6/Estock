"use client";

/** Customers and suppliers: lightweight records with history and balances (PRD 12). */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Drawer, Empty, Field, PageHead, Tabs } from "@/components/ui";
import { api, type Customer, type CustomerHistory, type Supplier } from "@/lib/api";
import { dateTime, dueLabel, money } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

type Tab = "customers" | "suppliers";

export default function ContactsPage() {
  return (
    <AppShell>
      <Contacts />
    </AppShell>
  );
}

function Contacts() {
  const { can } = useSession();
  const tabs = [
    { value: "customers" as const, label: "Customers", show: can("customer:view") },
    { value: "suppliers" as const, label: "Suppliers", show: can("supplier:view") },
  ].filter((t) => t.show);
  const [tab, setTab] = useState<Tab>(tabs[0]?.value ?? "customers");

  return (
    <>
      <PageHead title="Customers & suppliers" subtitle="Who you sell to and who you buy from" />
      <Tabs value={tab} options={tabs} onChange={setTab} />
      {tab === "customers" && <Customers />}
      {tab === "suppliers" && <Suppliers />}
    </>
  );
}

function Customers() {
  const { session, can, canWrite } = useSession();
  const currency = session?.currency ?? "ETB";
  const [items, setItems] = useState<Customer[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Customer | "new" | null>(null);
  const [history, setHistory] = useState<CustomerHistory | null>(null);
  const manage = canWrite && can("customer:manage");

  const load = useCallback(async (q: string) => {
    try {
      setItems((await api.customers({ q: q || undefined, limit: 200 })).items);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load customers"));
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void load(search), 250);
    return () => clearTimeout(timer);
  }, [search, load]);

  async function openHistory(customer: Customer) {
    try {
      setHistory(await api.customerHistory(customer.id));
    } catch (cause) {
      setError(describeError(cause, "Could not load the history"));
    }
  }

  return (
    <>
      <Alert>{error}</Alert>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <Field label="Search" hint="name, phone or company">
              <input value={search} onChange={(e) => setSearch(e.target.value)} />
            </Field>
          </div>
          {manage && (
            <button type="button" onClick={() => setEditing("new")}>
              New customer
            </button>
          )}
        </div>
        {items.length === 0 ? (
          <Empty title="No customers yet">
            <p>A walk-in sale needs no customer; credit does. Add them here or from the sale screen.</p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Phone</th>
                  {can("credit:view") && <th className="num">Owes ({currency})</th>}
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((customer) => (
                  <tr key={customer.id}>
                    <td>
                      <button type="button" className="link" onClick={() => void openHistory(customer)}>
                        {customer.name}
                      </button>
                      {customer.company && <div className="muted" style={{ fontSize: "0.82rem" }}>{customer.company}</div>}
                    </td>
                    <td className="muted nowrap">{customer.phone ?? "—"}</td>
                    {can("credit:view") && (
                      <td className="num">
                        {Number(customer.outstanding_balance ?? 0) > 0 ? <strong>{money(customer.outstanding_balance, currency)}</strong> : <span className="muted">—</span>}
                      </td>
                    )}
                    <td className="num">
                      {manage && (
                        <button type="button" className="link" onClick={() => setEditing(customer)}>
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && (
        <CustomerForm
          customer={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load(search);
          }}
        />
      )}

      {history && (
        <Drawer title={history.customer.name} onClose={() => setHistory(null)}>
          <p className="muted">
            {[history.customer.phone, history.customer.email, history.customer.address].filter(Boolean).join(" · ") || "No contact details"}
          </p>
          {history.outstanding_balance !== null && (
            <div className="stat" style={{ marginBottom: 14 }}>
              <div className="label">Outstanding balance</div>
              <div className="value">{money(history.outstanding_balance, currency)}</div>
              {history.customer.credit_limit && (
                <div className="note">
                  Credit limit {money(history.customer.credit_limit, currency)} · {history.customer.credit_limit_behaviour ?? "warn"}
                </div>
              )}
            </div>
          )}
          <div className="card">
            <div className="card-title">Credit</div>
            {history.credit_transactions.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>No credit history.</p>
            ) : (
              <ul className="checklist">
                {history.credit_transactions.map((t) => (
                  <li key={t.id}>
                    <div style={{ width: "100%" }} className="row">
                      <span style={{ flex: 1 }}>
                        <Link href={`/credit?open=${t.id}`}>{t.reference}</Link>{" "}
                        <span className="muted">{dueLabel(t.due_date, t.is_overdue, t.days_overdue)}</span>
                      </span>
                      <span>{money(t.balance, currency)}</span>
                      <Badge status={t.status} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="card">
            <div className="card-title">Sales</div>
            {history.sales.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>No sales yet.</p>
            ) : (
              <ul className="checklist">
                {history.sales.map((sale) => (
                  <li key={sale.id}>
                    <div style={{ width: "100%" }} className="row">
                      <span style={{ flex: 1 }}>
                        <Link href={`/sales/${sale.id}`}>{sale.number}</Link>{" "}
                        <span className="muted">{dateTime(sale.sold_at)}</span>
                      </span>
                      <span>{money(sale.total_amount, currency)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Drawer>
      )}
    </>
  );
}

function CustomerForm({ customer, onClose, onSaved }: { customer: Customer | null; onClose: () => void; onSaved: () => void }) {
  const { can } = useSession();
  const [form, setForm] = useState({
    name: customer?.name ?? "",
    phone: customer?.phone ?? "",
    telegram_username: customer?.telegram_username ?? "",
    email: customer?.email ?? "",
    address: customer?.address ?? "",
    company: customer?.company ?? "",
    notes: customer?.notes ?? "",
    credit_limit: customer?.credit_limit ?? "",
    credit_limit_behaviour: customer?.credit_limit_behaviour ?? "warn",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canLimit = can("credit:limit_override");

  function update(key: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm((prev) => ({ ...prev, [key]: event.target.value }));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {
      name: form.name,
      phone: form.phone || null,
      telegram_username: form.telegram_username || null,
      email: form.email || null,
      address: form.address || null,
      company: form.company || null,
      notes: form.notes || null,
    };
    if (canLimit) {
      body.credit_limit = form.credit_limit || null;
      body.credit_limit_behaviour = form.credit_limit ? form.credit_limit_behaviour : null;
    }
    try {
      if (customer) await api.updateCustomer(customer.id, body);
      else await api.createCustomer(body);
      onSaved();
    } catch (cause) {
      setError(describeError(cause, "Could not save the customer"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer title={customer ? customer.name : "New customer"} onClose={onClose}>
      <Alert>{error}</Alert>
      <form onSubmit={save}>
        <Field label="Name">
          <input value={form.name} onChange={update("name")} required autoFocus />
        </Field>
        <div className="grid">
          <Field label="Phone" hint="optional">
            <input value={form.phone} onChange={update("phone")} inputMode="tel" placeholder="0911234567" />
          </Field>
          <Field label="Telegram" hint="optional">
            <input value={form.telegram_username} onChange={update("telegram_username")} />
          </Field>
          <Field label="Email" hint="optional">
            <input type="email" value={form.email} onChange={update("email")} />
          </Field>
          <Field label="Company" hint="optional">
            <input value={form.company} onChange={update("company")} />
          </Field>
        </div>
        <Field label="Address" hint="optional">
          <input value={form.address} onChange={update("address")} />
        </Field>
        <Field label="Notes" hint="optional">
          <textarea rows={2} value={form.notes} onChange={update("notes")} />
        </Field>
        {canLimit && (
          <div className="card">
            <div className="card-title">Credit limit</div>
            <div className="grid">
              <Field label="Limit" hint="blank for none">
                <input value={form.credit_limit} onChange={update("credit_limit")} inputMode="decimal" />
              </Field>
              <Field label="When exceeded">
                <select value={form.credit_limit_behaviour} onChange={update("credit_limit_behaviour")}>
                  <option value="warn">Warn but allow</option>
                  <option value="require_approval">Need an approver&apos;s explicit override</option>
                  <option value="block">Block the sale</option>
                </select>
              </Field>
            </div>
          </div>
        )}
        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Drawer>
  );
}

function Suppliers() {
  const { session, can, canWrite } = useSession();
  const currency = session?.currency ?? "ETB";
  const [items, setItems] = useState<Supplier[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Supplier | "new" | null>(null);
  const manage = canWrite && can("supplier:manage");

  const load = useCallback(async () => {
    try {
      setItems((await api.suppliers({ limit: 200 })).items);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load suppliers"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <Alert>{error}</Alert>
      <div className="card">
        {manage && (
          <p style={{ marginTop: 0 }}>
            <button type="button" onClick={() => setEditing("new")}>
              New supplier
            </button>
          </p>
        )}
        {items.length === 0 ? (
          <Empty title="No suppliers yet">
            <p>Suppliers are recorded when you receive stock, so payables can be tracked.</p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Contact</th>
                  {can("purchase:view") && can("credit:view") && <th className="num">You owe ({currency})</th>}
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((supplier) => (
                  <tr key={supplier.id}>
                    <td>{supplier.name}</td>
                    <td className="muted">{[supplier.contact_person, supplier.phone].filter(Boolean).join(" · ") || "—"}</td>
                    {can("purchase:view") && can("credit:view") && (
                      <td className="num">
                        {Number(supplier.outstanding_balance ?? 0) > 0 ? (
                          <Link href="/credit?kind=payable"><strong>{money(supplier.outstanding_balance, currency)}</strong></Link>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    )}
                    <td className="num">
                      {manage && (
                        <button type="button" className="link" onClick={() => setEditing(supplier)}>
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {editing && (
        <SupplierForm
          supplier={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
    </>
  );
}

function SupplierForm({ supplier, onClose, onSaved }: { supplier: Supplier | null; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    name: supplier?.name ?? "",
    contact_person: supplier?.contact_person ?? "",
    phone: supplier?.phone ?? "",
    email: supplier?.email ?? "",
    address: supplier?.address ?? "",
    tin: supplier?.tin ?? "",
    notes: supplier?.notes ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function update(key: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [key]: event.target.value }));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      name: form.name,
      contact_person: form.contact_person || null,
      phone: form.phone || null,
      email: form.email || null,
      address: form.address || null,
      tin: form.tin || null,
      notes: form.notes || null,
    };
    try {
      if (supplier) await api.updateSupplier(supplier.id, body);
      else await api.createSupplier(body);
      onSaved();
    } catch (cause) {
      setError(describeError(cause, "Could not save the supplier"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer title={supplier ? supplier.name : "New supplier"} onClose={onClose}>
      <Alert>{error}</Alert>
      <form onSubmit={save}>
        <Field label="Name">
          <input value={form.name} onChange={update("name")} required autoFocus />
        </Field>
        <div className="grid">
          <Field label="Contact person" hint="optional">
            <input value={form.contact_person} onChange={update("contact_person")} />
          </Field>
          <Field label="Phone" hint="optional">
            <input value={form.phone} onChange={update("phone")} inputMode="tel" />
          </Field>
          <Field label="Email" hint="optional">
            <input type="email" value={form.email} onChange={update("email")} />
          </Field>
          <Field label="TIN" hint="optional">
            <input value={form.tin} onChange={update("tin")} />
          </Field>
        </div>
        <Field label="Address" hint="optional">
          <input value={form.address} onChange={update("address")} />
        </Field>
        <Field label="Notes" hint="optional">
          <textarea rows={2} value={form.notes} onChange={update("notes")} />
        </Field>
        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Drawer>
  );
}
