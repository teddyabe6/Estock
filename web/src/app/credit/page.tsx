"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Drawer, Empty, Field, PageHead, Stat, Tabs } from "@/components/ui";
import {
  api,
  type CreditSummary,
  type CreditTransaction,
  type FollowUp,
  type Payment,
} from "@/lib/api";
import { amount, dateTime, dueLabel, money, shortDate } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

const VIEWS = [
  { value: "outstanding", label: "Outstanding" },
  { value: "due_today", label: "Due today" },
  { value: "due_soon", label: "Due soon" },
  { value: "overdue", label: "Overdue" },
  { value: "partially_paid", label: "Part paid" },
  { value: "paid", label: "Paid" },
  { value: "all", label: "All" },
] as const;

type View = (typeof VIEWS)[number]["value"];
type Kind = "receivable" | "payable";

const PAYMENT_METHODS = [
  ["cash", "Cash"],
  ["telebirr", "Telebirr"],
  ["cbe_birr", "CBE Birr"],
  ["bank_transfer", "Bank transfer"],
  ["cheque", "Cheque"],
  ["mobile_money", "Mobile money"],
  ["other", "Other"],
] as const;

export default function CreditPage() {
  return (
    <AppShell>
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <Credit />
      </Suspense>
    </AppShell>
  );
}

function Credit() {
  const { session, can } = useSession();
  const params = useSearchParams();
  const currency = session?.currency ?? "ETB";
  const canSeePayables = can("purchase:view");

  const [kind, setKind] = useState<Kind>(
    params.get("kind") === "payable" && canSeePayables ? "payable" : "receivable",
  );
  const [view, setView] = useState<View>("outstanding");
  const [summary, setSummary] = useState<CreditSummary | null>(null);
  const [items, setItems] = useState<CreditTransaction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(params.get("open"));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryResult, page] = await Promise.all([
        api.creditSummary(kind),
        api.creditTransactions({ kind, view, limit: 200 }),
      ]);
      setSummary(summaryResult);
      setItems(page.items);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load credit"));
    } finally {
      setLoading(false);
    }
  }, [kind, view]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHead
        title="Credit"
        subtitle={kind === "receivable" ? "What customers owe you" : "What you owe suppliers"}
        actions={
          <>
            {canSeePayables && (
              <Tabs
                value={kind}
                options={[
                  { value: "receivable", label: "Receivables" },
                  { value: "payable", label: "Payables" },
                ]}
                onChange={setKind}
              />
            )}
            {can("report:credit") && (
              <button
                type="button"
                className="secondary"
                onClick={() => api.exportCredit(kind, view).catch((c) => setError(describeError(c)))}
              >
                Export CSV
              </button>
            )}
          </>
        }
      />

      <Alert>{error}</Alert>

      {summary && (
        <div className="grid">
          <Stat
            label="Total outstanding"
            value={money(summary.total_outstanding, currency)}
            note={`${summary.transaction_count} balance(s)`}
          />
          <Stat
            label="Due today"
            value={money(summary.due_today, currency)}
            tone={Number(summary.due_today) > 0 ? "warn" : "muted"}
          />
          <Stat
            label="Due within 7 days"
            value={money(summary.due_within_7_days, currency)}
            tone={Number(summary.due_within_7_days) > 0 ? "warn" : "muted"}
          />
          <Stat
            label="Overdue"
            value={money(summary.overdue, currency)}
            tone={Number(summary.overdue) > 0 ? "danger" : "muted"}
          />
          <Stat
            label="No due date"
            value={money(summary.no_due_date, currency)}
            note="Outstanding, but never marked overdue"
          />
        </div>
      )}

      <div className="card" style={{ marginTop: 14 }}>
        <Tabs value={view} options={VIEWS} onChange={setView} />

        {items.length === 0 && !loading ? (
          <Empty title="Nothing here">
            <p>No balances match this view.</p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Reference</th>
                  <th>{kind === "receivable" ? "Customer" : "Supplier"}</th>
                  <th>Due</th>
                  <th className="num">Total ({currency})</th>
                  <th className="num">Paid</th>
                  <th className="num">Balance</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id}>
                    <td className="nowrap">
                      <button type="button" className="link" onClick={() => setOpenId(row.id)}>
                        {row.reference}
                      </button>
                    </td>
                    <td>{row.counterparty_name ?? <span className="muted">Not named</span>}</td>
                    <td className={row.is_overdue ? "nowrap" : "muted nowrap"}>
                      {dueLabel(row.due_date, row.is_overdue, row.days_overdue)}
                    </td>
                    <td className="num">{amount(row.original_amount)}</td>
                    <td className="num muted">{amount(row.amount_paid)}</td>
                    <td className="num">
                      <strong>{amount(row.balance)}</strong>
                    </td>
                    <td className="nowrap">
                      <Badge status={row.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openId && (
        <TransactionDrawer
          id={openId}
          currency={currency}
          onClose={() => setOpenId(null)}
          onChanged={() => void load()}
        />
      )}
    </>
  );
}

/**
 * Everything about one balance: payments (with reversal), follow-up activity,
 * due-date changes and cancellation — each behind its own permission
 * (PRD 11.3, 11.6, 11.7).
 */
function TransactionDrawer({
  id,
  currency,
  onClose,
  onChanged,
}: {
  id: string;
  currency: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { can, canWrite } = useSession();
  const [transaction, setTransaction] = useState<CreditTransaction | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [activities, setActivities] = useState<FollowUp[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<"none" | "pay" | "followup" | "due">("none");

  const load = useCallback(async () => {
    try {
      const [t, p, a] = await Promise.all([
        api.creditTransaction(id),
        api.creditPayments(id),
        api.creditActivities(id),
      ]);
      setTransaction(t);
      setPayments(p);
      setActivities(a);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load this balance"));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, fallback: string) {
    try {
      await action();
      setPanel("none");
      await load();
      onChanged();
    } catch (cause) {
      setError(describeError(cause, fallback));
    }
  }

  const open =
    transaction && transaction.status !== "cancelled" && Number(transaction.balance) > 0;

  return (
    <Drawer title={transaction ? transaction.reference : "Loading…"} onClose={onClose}>
      <Alert>{error}</Alert>
      {transaction && (
        <>
          <div className="grid">
            <Stat
              label="Balance"
              value={money(transaction.balance, currency)}
              tone={transaction.is_overdue ? "danger" : "muted"}
            />
            <Stat
              label="Due"
              value={dueLabel(transaction.due_date, transaction.is_overdue, transaction.days_overdue)}
              note={transaction.due_date ? shortDate(transaction.due_date) : "Outstanding, never overdue"}
            />
          </div>
          <p className="muted" style={{ fontSize: "0.9rem" }}>
            {transaction.counterparty_name ?? "Not named"} · issued {shortDate(transaction.issued_on)} ·{" "}
            {money(transaction.original_amount, currency)} total,{" "}
            {money(transaction.amount_paid, currency)} paid · <Badge status={transaction.status} />
          </p>
          {transaction.agreement_note && (
            <p className="muted" style={{ fontSize: "0.9rem" }}>
              Agreement: {transaction.agreement_note}
            </p>
          )}
          {transaction.status === "cancelled" && (
            <Alert kind="warn">
              Cancelled{transaction.cancel_reason ? `: ${transaction.cancel_reason}` : ""}. The
              record is kept.
            </Alert>
          )}

          {canWrite && open && (
            <div className="row" style={{ marginBottom: 14 }}>
              {can("credit:payment") && (
                <button type="button" onClick={() => setPanel("pay")}>
                  Record payment
                </button>
              )}
              {can("credit:followup") && (
                <button type="button" className="secondary" onClick={() => setPanel("followup")}>
                  Log follow-up
                </button>
              )}
              {can("credit:duedate") && (
                <button type="button" className="secondary" onClick={() => setPanel("due")}>
                  Change due date
                </button>
              )}
              {can("credit:cancel") && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    const reason = window.prompt(
                      "Why cancel this balance? It stays on record as cancelled.",
                    );
                    if (reason && reason.trim().length >= 3) {
                      void run(() => api.cancelCredit(id, reason.trim()), "Could not cancel");
                    }
                  }}
                >
                  Cancel balance
                </button>
              )}
            </div>
          )}

          {panel === "pay" && (
            <PaymentForm
              balance={transaction.balance}
              currency={currency}
              onSubmit={(body) =>
                run(() => api.recordCreditPayment(id, body), "Could not record the payment")
              }
              onCancel={() => setPanel("none")}
            />
          )}
          {panel === "followup" && (
            <FollowUpForm
              onSubmit={(body) => run(() => api.addFollowUp(id, body), "Could not log the follow-up")}
              onCancel={() => setPanel("none")}
            />
          )}
          {panel === "due" && (
            <DueDateForm
              current={transaction.due_date}
              onSubmit={(body) =>
                run(() => api.changeDueDate(id, body), "Could not change the due date")
              }
              onCancel={() => setPanel("none")}
            />
          )}

          <div className="card">
            <div className="card-title">Payments</div>
            {payments.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                No payments yet.
              </p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Method</th>
                      <th className="num">Amount</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {payments.map((payment) => (
                      <tr key={payment.id} style={payment.is_reversed ? { opacity: 0.6 } : undefined}>
                        <td className="nowrap">{dateTime(payment.paid_at)}</td>
                        <td>
                          {payment.method.replace(/_/g, " ")}
                          {payment.reference ? <span className="muted"> · {payment.reference}</span> : null}
                          {payment.is_reversed && (
                            <div className="muted" style={{ fontSize: "0.8rem" }}>
                              reversed{payment.reversal_reason ? `: ${payment.reversal_reason}` : ""}
                            </div>
                          )}
                        </td>
                        <td
                          className="num"
                          style={payment.is_reversed ? { textDecoration: "line-through" } : undefined}
                        >
                          {amount(payment.amount)}
                        </td>
                        <td className="num">
                          {canWrite &&
                            can("credit:payment") &&
                            !payment.is_reversed &&
                            transaction.status !== "cancelled" && (
                              <button
                                type="button"
                                className="link"
                                onClick={() => {
                                  const reason = window.prompt(
                                    "Why reverse this payment? The original row is kept.",
                                  );
                                  if (reason && reason.trim().length >= 3) {
                                    void run(
                                      () => api.reversePayment(payment.id, reason.trim()),
                                      "Could not reverse",
                                    );
                                  }
                                }}
                              >
                                Reverse
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

          <div className="card">
            <div className="card-title">Follow-up</div>
            <p className="muted" style={{ fontSize: "0.85rem", marginTop: 0 }}>
              A logged call or promise never changes the balance; only a payment does.
            </p>
            {activities.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                Nothing logged yet.
              </p>
            ) : (
              <ul className="checklist">
                {activities.map((activity) => (
                  <li key={activity.id}>
                    <div>
                      <strong>{activity.kind.replace(/_/g, " ")}</strong>{" "}
                      <span className="muted" style={{ fontSize: "0.85rem" }}>
                        {dateTime(activity.occurred_at)}
                      </span>
                      {activity.promised_amount && (
                        <div className="muted" style={{ fontSize: "0.9rem" }}>
                          Promised {money(activity.promised_amount, currency)}
                          {activity.promised_date ? ` by ${shortDate(activity.promised_date)}` : ""}
                        </div>
                      )}
                      {activity.note && <div style={{ fontSize: "0.9rem" }}>{activity.note}</div>}
                      {activity.outcome && (
                        <div className="muted" style={{ fontSize: "0.85rem" }}>
                          Outcome: {activity.outcome}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </Drawer>
  );
}

function PaymentForm({
  balance,
  currency,
  onSubmit,
  onCancel,
}: {
  balance: string;
  currency: string;
  onSubmit: (body: { amount: string; method: string; reference?: string; note?: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const [amountValue, setAmountValue] = useState(balance);
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        void onSubmit({
          amount: amountValue,
          method,
          reference: reference || undefined,
          note: note || undefined,
        }).finally(() => setBusy(false));
      }}
    >
      <div className="card-title">Record a payment</div>
      <p className="muted" style={{ marginTop: 0 }}>
        Outstanding: {money(balance, currency)}. Partial payments are fine; more than the balance is
        refused.
      </p>
      <div className="grid">
        <Field label="Amount">
          <input value={amountValue} onChange={(e) => setAmountValue(e.target.value)} inputMode="decimal" required />
        </Field>
        <Field label="Method">
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            {PAYMENT_METHODS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Reference" hint="optional">
          <input value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
        <Field label="Note" hint="optional">
          <input value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
      <div className="row">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Record payment"}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function FollowUpForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (body: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}) {
  const [kind, setKind] = useState("called");
  const [note, setNote] = useState("");
  const [promisedAmount, setPromisedAmount] = useState("");
  const [promisedDate, setPromisedDate] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        void onSubmit({
          kind,
          note: note || undefined,
          promised_amount: kind === "promise_to_pay" && promisedAmount ? promisedAmount : undefined,
          promised_date: kind === "promise_to_pay" && promisedDate ? promisedDate : undefined,
        }).finally(() => setBusy(false));
      }}
    >
      <div className="card-title">Log a follow-up</div>
      <div className="grid">
        <Field label="What happened">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="called">Called</option>
            <option value="message_sent">Message sent</option>
            <option value="promise_to_pay">Promise to pay</option>
            <option value="arrangement">Arrangement discussed</option>
            <option value="note">Note</option>
          </select>
        </Field>
        {kind === "promise_to_pay" && (
          <>
            <Field label="Promised amount" hint="optional">
              <input value={promisedAmount} onChange={(e) => setPromisedAmount(e.target.value)} inputMode="decimal" />
            </Field>
            <Field label="Promised by" hint="optional">
              <input type="date" value={promisedDate} onChange={(e) => setPromisedDate(e.target.value)} />
            </Field>
          </>
        )}
      </div>
      <Field label="Note" hint="optional">
        <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Log it"}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function DueDateForm({
  current,
  onSubmit,
  onCancel,
}: {
  current: string | null;
  onSubmit: (body: { due_date?: string | null; due_date_preset?: string; note?: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const [choice, setChoice] = useState<string>(current ? "custom" : "none");
  const [date, setDate] = useState(current ?? "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        const body =
          choice === "none"
            ? { due_date: null, note: note || undefined }
            : choice === "custom"
              ? { due_date: date, note: note || undefined }
              : { due_date_preset: choice, note: note || undefined };
        void onSubmit(body).finally(() => setBusy(false));
      }}
    >
      <div className="card-title">Change the due date</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Reminders are rescheduled and the overdue state recomputed. The change is audited.
      </p>
      <div className="grid">
        <Field label="Due">
          <select value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="none">No due date</option>
            <option value="today">Today</option>
            <option value="tomorrow">Tomorrow</option>
            <option value="7_days">In 7 days</option>
            <option value="15_days">In 15 days</option>
            <option value="30_days">In 30 days</option>
            <option value="custom">A specific date</option>
          </select>
        </Field>
        {choice === "custom" && (
          <Field label="Date">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
        )}
      </div>
      <Field label="Why" hint="optional">
        <input value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save due date"}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
