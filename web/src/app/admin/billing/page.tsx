"use client";

/** Invoices across every shop, filterable by what they actually are. */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell, InvoiceStatus } from "@/components/AdminShell";
import { Alert, Empty, PageHead, Stat } from "@/components/ui";
import {
  adminApi,
  INVOICE_STATUSES,
  type BillingSummary,
  type Invoice,
} from "@/lib/admin";
import { useAdmin, useAdminCall } from "@/lib/adminSession";
import { money, shortDate } from "@/lib/format";

const PAGE = 50;

export default function AdminBillingPage() {
  const { admin, signOut } = useAdmin();
  const describe = useAdminCall(signOut);

  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [totals, page] = await Promise.all([
        adminApi.billingSummary(),
        adminApi.invoices({ status: status || undefined, limit: PAGE, offset }),
      ]);
      setSummary(totals);
      setInvoices(page.items);
      setTotal(page.total);
      setError(null);
    } catch (cause) {
      setError(describe(cause, "Could not load the invoices"));
    }
  }, [describe, status, offset]);

  useEffect(() => {
    if (admin) void load();
  }, [admin, load]);

  async function runBilling() {
    setBusy(true);
    setNotice(null);
    try {
      const result = await adminApi.runBilling();
      setNotice(
        `Raised ${result.invoices_raised} invoice(s). ${result.skipped_already_billed} shop(s) already billed, ${result.skipped_no_plan} on no plan.`,
      );
      setOffset(0);
      await load();
    } catch (cause) {
      setError(describe(cause, "Could not run the billing cycle"));
    } finally {
      setBusy(false);
    }
  }

  const currency = summary?.currency ?? "ETB";

  return (
    <AdminShell>
      <PageHead
        title="Billing"
        subtitle={`${total} invoice(s)`}
        actions={
          <button type="button" className="secondary" onClick={() => void runBilling()} disabled={busy}>
            {busy ? "Running…" : "Run billing cycle"}
          </button>
        }
      />

      <Alert>{error}</Alert>
      {notice && <Alert kind="ok">{notice}</Alert>}

      <div className="grid">
        <Stat label="Billed" value={money(summary?.billed ?? "0", currency)} />
        <Stat label="Collected" value={money(summary?.collected ?? "0", currency)} />
        <Stat
          label="Outstanding"
          value={money(summary?.outstanding ?? "0", currency)}
          tone={Number(summary?.outstanding ?? 0) > 0 ? "warn" : "muted"}
        />
        <Stat
          label="Overdue"
          value={money(summary?.overdue ?? "0", currency)}
          note={`${summary?.overdue_count ?? 0} invoice(s)`}
          tone={Number(summary?.overdue ?? 0) > 0 ? "danger" : "muted"}
        />
      </div>

      <div className="chips">
        <button
          type="button"
          className={status === "" ? "chip is-active" : "chip"}
          onClick={() => {
            setStatus("");
            setOffset(0);
          }}
        >
          All
        </button>
        {INVOICE_STATUSES.map((value) => (
          <button
            key={value}
            type="button"
            className={status === value ? "chip is-active" : "chip"}
            onClick={() => {
              setStatus(value);
              setOffset(0);
            }}
          >
            {value.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {invoices.length === 0 ? (
        <Empty title="No invoices here">
          {status
            ? "Nothing in that state right now."
            : "Put a shop on a plan, then run the billing cycle."}
        </Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Shop</th>
              <th>Period</th>
              <th>Due</th>
              <th className="num">Amount</th>
              <th className="num">Paid</th>
              <th className="num">Owing</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((invoice) => (
              <tr key={invoice.id}>
                <td>
                  {invoice.number} <InvoiceStatus status={invoice.status} />
                  {invoice.plan_name && (
                    <div className="muted" style={{ fontSize: "0.85rem" }}>
                      {invoice.plan_name}
                    </div>
                  )}
                </td>
                <td>
                  <Link href={`/admin/shops/${invoice.tenant_id}`}>
                    {invoice.tenant_name ?? "—"}
                  </Link>
                </td>
                <td>
                  {shortDate(invoice.period_start)} – {shortDate(invoice.period_end)}
                </td>
                <td>{shortDate(invoice.due_on) || "—"}</td>
                <td className="num">{money(invoice.amount, invoice.currency)}</td>
                <td className="num">{money(invoice.amount_paid, invoice.currency)}</td>
                <td className="num">{money(invoice.balance_due, invoice.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {total > PAGE && (
        <div className="row" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="secondary"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
          >
            Previous
          </button>
          <span className="muted">
            {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
          </span>
          <button
            type="button"
            className="secondary"
            disabled={offset + PAGE >= total}
            onClick={() => setOffset(offset + PAGE)}
          >
            Next
          </button>
        </div>
      )}

      <p className="muted" style={{ marginTop: 16 }}>
        Recording a payment, voiding an invoice or reversing a payment is done on the
        shop it belongs to, where the context is.
      </p>
    </AdminShell>
  );
}
