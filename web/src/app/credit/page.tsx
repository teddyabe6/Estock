"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Empty, Field, PageHead, Stat } from "@/components/ui";
import { api, type CreditSummary, type CreditTransaction } from "@/lib/api";
import { amount, dueLabel, money } from "@/lib/format";
import { useSession } from "@/lib/session";

const VIEWS = [
  { value: "outstanding", label: "Outstanding" },
  { value: "due_today", label: "Due today" },
  { value: "due_soon", label: "Due soon" },
  { value: "overdue", label: "Overdue" },
  { value: "partially_paid", label: "Part paid" },
  { value: "paid", label: "Paid" },
  { value: "all", label: "All" },
];

export default function CreditPage() {
  return (
    <AppShell>
      <Credit />
    </AppShell>
  );
}

function Credit() {
  const { session, can } = useSession();
  const currency = session?.currency ?? "ETB";

  const [kind, setKind] = useState<"receivable" | "payable">("receivable");
  const [view, setView] = useState("outstanding");
  const [summary, setSummary] = useState<CreditSummary | null>(null);
  const [items, setItems] = useState<CreditTransaction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState<CreditTransaction | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryResult, page] = await Promise.all([
        api.creditSummary(kind),
        api.creditTransactions({ kind, view, limit: 100 }),
      ]);
      setSummary(summaryResult);
      setItems(page.items);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load credit");
    } finally {
      setLoading(false);
    }
  }, [kind, view]);

  useEffect(() => {
    void load();
  }, [load]);

  const canSeePayables = can("purchase:view");

  return (
    <>
      <PageHead
        title="Credit"
        subtitle={
          kind === "receivable"
            ? "What customers owe you"
            : "What you owe suppliers"
        }
        actions={
          canSeePayables ? (
            <>
              <button
                type="button"
                className={kind === "receivable" ? undefined : "secondary"}
                onClick={() => setKind("receivable")}
              >
                Receivables
              </button>
              <button
                type="button"
                className={kind === "payable" ? undefined : "secondary"}
                onClick={() => setKind("payable")}
              >
                Payables
              </button>
            </>
          ) : null
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
        <div className="row" style={{ marginBottom: 12 }}>
          {VIEWS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={view === option.value ? undefined : "secondary"}
              onClick={() => setView(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

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
                  {can("credit:payment") && <th />}
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id}>
                    <td className="nowrap">{row.reference}</td>
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
                    {can("credit:payment") && (
                      <td className="num">
                        {Number(row.balance) > 0 && row.status !== "cancelled" && (
                          <button
                            type="button"
                            className="link"
                            onClick={() => setPaying(row)}
                          >
                            Record payment
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {paying && (
        <RecordPayment
          transaction={paying}
          currency={currency}
          onClose={() => setPaying(null)}
          onDone={() => {
            setPaying(null);
            void load();
          }}
        />
      )}
    </>
  );
}

function RecordPayment({
  transaction,
  currency,
  onClose,
  onDone,
}: {
  transaction: CreditTransaction;
  currency: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState(transaction.balance);
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.recordCreditPayment(transaction.id, {
        amount,
        method,
        reference: reference || undefined,
      });
      onDone();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not record the payment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">
        Record a payment on {transaction.reference}
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Outstanding balance: {money(transaction.balance, currency)}
      </p>

      <Alert>{error}</Alert>

      <form onSubmit={submit}>
        <div className="grid">
          <Field label="Amount" hint="partial payments are fine">
            <input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              inputMode="decimal"
              required
            />
          </Field>
          <Field label="Method">
            <select value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="cash">Cash</option>
              <option value="telebirr">Telebirr</option>
              <option value="cbe_birr">CBE Birr</option>
              <option value="bank_transfer">Bank transfer</option>
              <option value="cheque">Cheque</option>
            </select>
          </Field>
          <Field label="Reference" hint="optional">
            <input value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
        </div>
        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Record payment"}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
