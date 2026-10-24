"use client";

/**
 * One shop, and every lever the operator has over it.
 *
 * The levers are grouped by what they do rather than by which endpoint they
 * call: access, what it pays, and looking inside. Each destructive one says
 * what it will do to a real business before it does it.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AdminShell, InvoiceStatus, ShopStatus } from "@/components/AdminShell";
import { Alert, Empty, Field, PageHead, Stat, Toggle } from "@/components/ui";
import {
  adminApi,
  methodLabel,
  PAYMENT_METHODS,
  SHOP_STATUS_NOTE,
  SHOP_STATUSES,
  type Invoice,
  type Plan,
  type TenantBilling,
  type TenantSwitch,
} from "@/lib/admin";
import { useAdmin, useAdminCall } from "@/lib/adminSession";
import { money, shortDate } from "@/lib/format";

export default function AdminShopPage() {
  const params = useParams<{ tenantId: string }>();
  const tenantId = params.tenantId;
  const { admin, signOut } = useAdmin();
  const describe = useAdminCall(signOut);

  const [billing, setBilling] = useState<TenantBilling | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [switches, setSwitches] = useState<TenantSwitch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [payingFor, setPayingFor] = useState<Invoice | null>(null);

  const load = useCallback(async () => {
    try {
      const [bill, planList, shopSwitches] = await Promise.all([
        adminApi.tenantBilling(tenantId),
        adminApi.plans(),
        adminApi.tenantSettings(tenantId),
      ]);
      setBilling(bill);
      setPlans(planList);
      setSwitches(shopSwitches.settings);
      setError(null);
    } catch (cause) {
      setError(describe(cause, "Could not load this shop"));
    }
  }, [tenantId, describe]);

  useEffect(() => {
    if (admin) void load();
  }, [admin, load]);

  const act = useCallback(
    async (what: () => Promise<string>) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        setNotice(await what());
        await load();
      } catch (cause) {
        setError(describe(cause, "That did not work"));
      } finally {
        setBusy(false);
      }
    },
    [describe, load],
  );

  if (!billing) {
    return (
      <AdminShell>
        <Alert>{error}</Alert>
        {!error && <p className="muted">Loading…</p>}
      </AdminShell>
    );
  }

  const currency = billing.currency || "ETB";

  return (
    <AdminShell>
      <div className="crumbs">
        <Link href="/admin/shops">Shops</Link> · {billing.tenant_name}
      </div>
      <PageHead
        title={billing.tenant_name}
        subtitle={
          <>
            <ShopStatus
              status={billing.tenant_status}
              note={SHOP_STATUS_NOTE[billing.tenant_status]}
            />{" "}
            {SHOP_STATUS_NOTE[billing.tenant_status]}
          </>
        }
      />

      <Alert>{error}</Alert>
      {notice && <Alert kind="ok">{notice}</Alert>}

      <div className="grid">
        <Stat
          label="Owing now"
          value={money(billing.balance_due, currency)}
          note={`${billing.unpaid_count} unpaid invoice(s)`}
          tone={Number(billing.balance_due) > 0 ? "warn" : "muted"}
        />
        <Stat label="Served until" value={shortDate(billing.paid_until) || "—"} />
        <Stat label="Users" value={billing.usage.users} />
        <Stat label="Products" value={billing.usage.products} />
        <Stat label="Sales recorded" value={billing.usage.sales} />
      </div>

      {/* ------------------------------------------------------------------ */}
      <section className="card">
        <div className="card-title">Access</div>
        <p className="muted" style={{ marginTop: 0 }}>
          Changing this never deletes or alters the shop&apos;s data. Read-only means
          they can still see everything and cannot post anything new.
        </p>
        <StatusControl
          current={billing.tenant_status}
          busy={busy}
          onChange={(status, reason) =>
            act(async () => {
              await adminApi.setShopStatus(tenantId, status, reason);
              return `${billing.tenant_name} is now ${status}.`;
            })
          }
        />
      </section>

      {/* ------------------------------------------------------------------ */}
      <section className="grid">
        <TrialCard
          endsOn={billing.trial_ends_on}
          busy={busy}
          onSet={(days, reason) =>
            act(async () => {
              const result = await adminApi.setTrial(tenantId, days, reason);
              return `Trial now ends ${result.trial_ends_on}.`;
            })
          }
        />
        <PlanCard
          plans={plans}
          current={billing.plan}
          busy={busy}
          onSet={(planId, reason) =>
            act(async () => {
              const result = await adminApi.setPlan(tenantId, planId, reason);
              return `Moved to ${result.plan.name} at ${result.plan.monthly_price} ${result.plan.currency} a month.`;
            })
          }
        />
      </section>

      {/* ------------------------------------------------------------------ */}
      <section className="card">
        <div className="card-title">Marketplace</div>
        <p className="muted" style={{ marginTop: 0 }}>
          Your switch over this shop, separate from the shop&apos;s own decision to be
          listed. Turning it off stops its products appearing and stops it receiving
          requests — the shop&apos;s own setting is left alone and takes effect again
          the moment you turn this back on.
        </p>
        {switches.length === 0 ? (
          <p className="muted">Loading…</p>
        ) : (
          switches.map((item) => (
            <div key={item.key}>
              <Toggle
                label={
                  item.key === "marketplace_listed"
                    ? "Taking part in the marketplace"
                    : item.key.replace(/_/g, " ")
                }
                // The card above already explains it; the switch's own
                // description is written for the platform-wide screen and
                // would just say the same thing again here.
                hint={item.enabled ? "buyers can see it and ask it for prices" : "paused"}
                checked={item.enabled}
                onChange={(value) =>
                  act(async () => {
                    await adminApi.setSwitch(item.key, value, { tenant_id: tenantId });
                    return value
                      ? `${billing.tenant_name} is back on the marketplace.`
                      : `${billing.tenant_name} is paused: buyers will not see it or be able to ask it for prices.`;
                  })
                }
              />
              {!item.set_for_shop && (
                <p className="muted" style={{ margin: "0 0 8px", fontSize: "0.85rem" }}>
                  Following the platform setting ({item.platform_default ? "on" : "off"}).
                </p>
              )}
            </div>
          ))
        )}
      </section>

      {/* ------------------------------------------------------------------ */}
      <section className="card">
        <div className="card-title">Billing</div>
        <div className="row" style={{ marginBottom: 12 }}>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() =>
              act(async () => {
                const invoice = await adminApi.raiseInvoice({ tenant_id: tenantId });
                return `Raised ${invoice.number} for ${money(invoice.amount, invoice.currency)}, due ${invoice.due_on ?? "—"}.`;
              })
            }
          >
            Raise the next invoice
          </button>
          <span className="muted">
            Uses the shop&apos;s plan price and the period after the one it has paid for.
          </span>
        </div>

        {billing.invoices.length === 0 ? (
          <Empty title="Nothing billed yet">
            Put the shop on a plan, then raise its first invoice.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Period</th>
                <th>Due</th>
                <th className="num">Amount</th>
                <th className="num">Paid</th>
                <th className="num">Owing</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {billing.invoices.map((invoice) => (
                <tr key={invoice.id}>
                  <td>
                    {invoice.number} <InvoiceStatus status={invoice.status} />
                    {invoice.payments && invoice.payments.length > 0 && (
                      <div className="muted" style={{ fontSize: "0.85rem" }}>
                        {invoice.payments.map((payment) => (
                          <div key={payment.id}>
                            {methodLabel(payment.method)} {money(payment.amount, currency)}
                            {payment.reference ? ` · ${payment.reference}` : ""}
                            {payment.is_reversed ? " · reversed" : ""}
                            {!payment.is_reversed && (
                              <>
                                {" · "}
                                <button
                                  type="button"
                                  className="link"
                                  disabled={busy}
                                  onClick={() => {
                                    const reason = window.prompt(
                                      "Why is this payment being reversed? The row is kept either way.",
                                    );
                                    if (!reason) return;
                                    void act(async () => {
                                      await adminApi.reversePayment(payment.id, reason);
                                      return "Payment reversed. The invoice is owing again.";
                                    });
                                  }}
                                >
                                  reverse
                                </button>
                              </>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>
                    {shortDate(invoice.period_start)} – {shortDate(invoice.period_end)}
                  </td>
                  <td>{shortDate(invoice.due_on) || "—"}</td>
                  <td className="num">{money(invoice.amount, invoice.currency)}</td>
                  <td className="num">{money(invoice.amount_paid, invoice.currency)}</td>
                  <td className="num">{money(invoice.balance_due, invoice.currency)}</td>
                  <td className="num">
                    {invoice.status === "draft" && (
                      <button
                        type="button"
                        className="link"
                        disabled={busy}
                        onClick={() =>
                          act(async () => {
                            await adminApi.issueInvoice(invoice.id);
                            return `${invoice.number} issued.`;
                          })
                        }
                      >
                        Issue
                      </button>
                    )}
                    {Number(invoice.balance_due) > 0 && invoice.status !== "draft" && (
                      <button type="button" className="link" onClick={() => setPayingFor(invoice)}>
                        Record payment
                      </button>
                    )}
                    {Number(invoice.amount_paid) === 0 && invoice.status !== "void" && (
                      <>
                        {" · "}
                        <button
                          type="button"
                          className="link"
                          disabled={busy}
                          onClick={() => {
                            const reason = window.prompt("Why is this invoice being voided?");
                            if (!reason) return;
                            void act(async () => {
                              await adminApi.voidInvoice(invoice.id, reason);
                              return `${invoice.number} voided. It is kept, not deleted.`;
                            });
                          }}
                        >
                          Void
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {payingFor && (
        <PaymentForm
          invoice={payingFor}
          busy={busy}
          onCancel={() => setPayingFor(null)}
          onSubmit={(body) =>
            act(async () => {
              const result = await adminApi.recordPayment(payingFor.id, body);
              setPayingFor(null);
              const parts = [
                `Recorded ${money(result.payment.amount, result.invoice.currency)}.`,
                `${result.invoice.number} is now ${result.invoice.status.replace(/_/g, " ")}.`,
              ];
              if (result.renewed) parts.push("Service renewed.");
              if (result.tenant_status) parts.push(`The shop is now ${result.tenant_status}.`);
              return [...parts, ...result.warnings].join(" ");
            })
          }
        />
      )}

      {/* ------------------------------------------------------------------ */}
      <section className="card">
        <div className="card-title">Look inside this shop</div>
        <p className="muted" style={{ marginTop: 0 }}>
          Support access opens a read-only session as this shop. It is time-limited,
          it cannot change anything, and the shop sees it in its own audit log —
          which is why it needs a reason.
        </p>
        <SupportAccess
          busy={busy}
          onGrant={(reason, minutes) =>
            act(async () => {
              const grant = await adminApi.supportAccess(tenantId, reason, minutes);
              return `${grant.notice} The token lasts ${grant.expires_in_minutes} minutes and is in this response only.`;
            })
          }
        />
      </section>

      <p className="muted" style={{ marginTop: 16 }}>
        <Link href={`/admin/audit?tenant_id=${tenantId}`}>
          See everything recorded about this shop →
        </Link>
      </p>
    </AdminShell>
  );
}

// --------------------------------------------------------------------------- //

function StatusControl({
  current,
  busy,
  onChange,
}: {
  current: string;
  busy: boolean;
  onChange: (status: string, reason: string) => void;
}) {
  const [status, setStatus] = useState(current);
  const [reason, setReason] = useState("");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (status === current) return;
        if (
          status === "suspended" &&
          !window.confirm(
            "Suspending shuts this business out of the system. Paying an invoice will not lift it — only you can. Continue?",
          )
        ) {
          return;
        }
        onChange(status, reason);
        setReason("");
      }}
    >
      <div className="grid">
        <Field label="Status" hint="what the shop may do">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {SHOP_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value === "restricted" ? "restricted (read-only)" : value}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Reason" hint="recorded in the shop's audit log">
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {SHOP_STATUS_NOTE[status]}
      </p>
      <button type="submit" disabled={busy || status === current}>
        {status === current ? "No change" : `Set to ${status}`}
      </button>
    </form>
  );
}

function TrialCard({
  endsOn,
  busy,
  onSet,
}: {
  endsOn: string | null;
  busy: boolean;
  onSet: (days: number, reason: string) => void;
}) {
  const [days, setDays] = useState("30");
  const [reason, setReason] = useState("");
  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        onSet(Number(days), reason);
        setReason("");
      }}
    >
      <div className="card-title">Trial</div>
      <p className="muted" style={{ marginTop: 0 }}>
        {endsOn ? `Currently ends ${shortDate(endsOn)}.` : "No trial end on record."} Days
        are counted from the day the trial started.
      </p>
      <Field label="Trial length in days">
        <input
          value={days}
          onChange={(e) => setDays(e.target.value)}
          inputMode="numeric"
          required
        />
      </Field>
      <Field label="Reason">
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <button type="submit" disabled={busy}>
        Set trial
      </button>
    </form>
  );
}

function PlanCard({
  plans,
  current,
  busy,
  onSet,
}: {
  plans: Plan[];
  current: Plan | null;
  busy: boolean;
  onSet: (planId: string, reason: string) => void;
}) {
  const [planId, setPlanId] = useState("");
  const [reason, setReason] = useState("");
  const chosen = plans.find((plan) => plan.id === planId);

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        if (!planId) return;
        onSet(planId, reason);
        setReason("");
      }}
    >
      <div className="card-title">Plan</div>
      {current ? (
        <p style={{ marginTop: 0 }}>
          On <strong>{current.name}</strong> at {money(current.monthly_price, current.currency)}{" "}
          a month.
        </p>
      ) : (
        <div className="alert warn" role="status">
          On no plan, so there is no price to bill it. Put it on one before raising an
          invoice.
        </div>
      )}
      <p className="muted" style={{ marginTop: 0 }}>
        The plan sets the price it is billed and the ceilings it is held to. Moving to a
        smaller plan never deletes anything — it only refuses the next addition.
      </p>
      <Field label="Plan">
        <select value={planId} onChange={(e) => setPlanId(e.target.value)} required>
          <option value="">{current ? "Move to another plan…" : "Choose a plan…"}</option>
          {plans.map((plan) => (
            <option key={plan.id} value={plan.id}>
              {plan.name} — {plan.monthly_price} {plan.currency}/month
            </option>
          ))}
        </select>
      </Field>
      {chosen && (
        <p className="muted" style={{ marginTop: 0 }}>
          Allows {chosen.max_branches ?? "any"} branch(es), {chosen.max_users ?? "any"}{" "}
          user(s), {chosen.max_products ?? "any"} product(s).
        </p>
      )}
      <Field label="Reason">
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <button type="submit" disabled={busy || !planId}>
        Set plan
      </button>
    </form>
  );
}

function PaymentForm({
  invoice,
  busy,
  onCancel,
  onSubmit,
}: {
  invoice: Invoice;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const [amount, setAmount] = useState(invoice.balance_due);
  const [method, setMethod] = useState<string>("telebirr");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          amount,
          method,
          reference: reference || undefined,
          paid_on: paidOn,
          note: note || undefined,
          // So a double submit on a slow connection records one payment.
          idempotency_key: `${invoice.id}:${paidOn}:${amount}:${reference}`,
        });
      }}
    >
      <div className="card-title">Record a payment against {invoice.number}</div>
      <p className="muted" style={{ marginTop: 0 }}>
        Owing {money(invoice.balance_due, invoice.currency)}. Part payment is fine; only
        paying in full renews the service.
      </p>
      <div className="grid">
        <Field label="Amount">
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" required />
        </Field>
        <Field label="How it arrived">
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            {PAYMENT_METHODS.map((value) => (
              <option key={value} value={value}>
                {methodLabel(value)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Reference" hint="transaction number, bank slip">
          <input value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
        <Field label="Date paid">
          <input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} required />
        </Field>
      </div>
      <Field label="Note">
        <input value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy}>
          {busy ? "Recording…" : "Record payment"}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function SupportAccess({
  busy,
  onGrant,
}: {
  busy: boolean;
  onGrant: (reason: string, minutes: number) => void;
}) {
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState("60");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onGrant(reason, Number(minutes));
        setReason("");
      }}
    >
      <div className="grid">
        <Field label="Why you need to look" hint="at least 10 characters; the shop sees this">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            minLength={10}
            required
            placeholder="e.g. Owner reported stock figures look wrong"
          />
        </Field>
        <Field label="For how long, in minutes">
          <input value={minutes} onChange={(e) => setMinutes(e.target.value)} inputMode="numeric" />
        </Field>
      </div>
      <button type="submit" className="secondary" disabled={busy}>
        Grant myself read-only access
      </button>
    </form>
  );
}
