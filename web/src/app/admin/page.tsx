"use client";

/**
 * The operator's first screen: the money, and the shops that need a decision.
 *
 * Deliberately not a wall of charts. The questions a platform owner opens this
 * for are "what am I owed", "who is late" and "who is about to fall out of
 * service", so those are what it answers, each one a link to the thing it is
 * about.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell, InvoiceStatus, ShopStatus } from "@/components/AdminShell";
import { Alert, Empty, PageHead, Stat } from "@/components/ui";
import { adminApi, SHOP_STATUS_NOTE, type BillingSummary, type Invoice, type ShopRow } from "@/lib/admin";
import { useAdmin, useAdminCall } from "@/lib/adminSession";
import { money, shortDate } from "@/lib/format";

/** A trial inside this many days is worth the operator's attention. */
const SOON_DAYS = 7;

export default function AdminOverviewPage() {
  const { admin, signOut } = useAdmin();
  const describe = useAdminCall(signOut);

  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [overdue, setOverdue] = useState<Invoice[]>([]);
  const [shops, setShops] = useState<ShopRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [totals, late, allShops] = await Promise.all([
        adminApi.billingSummary(),
        adminApi.invoices({ status: "overdue", limit: 10 }),
        adminApi.shops({ limit: 200 }),
      ]);
      setSummary(totals);
      setOverdue(late.items);
      setShops(allShops.items);
      setError(null);
    } catch (cause) {
      setError(describe(cause, "Could not load the platform summary"));
    }
  }, [describe]);

  useEffect(() => {
    if (admin) void load();
  }, [admin, load]);

  async function runBilling() {
    setBusy(true);
    setNotice(null);
    try {
      const result = await adminApi.runBilling();
      setNotice(
        result.invoices_raised === 0
          ? `Nothing to raise. ${result.skipped_already_billed} shop(s) already billed for the next period, ${result.skipped_no_plan} on no plan.`
          : `Raised ${result.invoices_raised} invoice(s). ${result.skipped_already_billed} already billed, ${result.skipped_no_plan} on no plan.`,
      );
      await load();
    } catch (cause) {
      setError(describe(cause, "Could not run the billing cycle"));
    } finally {
      setBusy(false);
    }
  }

  const counts = shops.reduce<Record<string, number>>((acc, shop) => {
    acc[shop.status] = (acc[shop.status] ?? 0) + 1;
    return acc;
  }, {});

  const today = new Date();
  const endingSoon = shops
    .filter((shop) => {
      if (!shop.trial_ends_on || shop.status !== "trial") return false;
      const days = Math.ceil(
        (new Date(shop.trial_ends_on).getTime() - today.getTime()) / 86_400_000,
      );
      return days <= SOON_DAYS;
    })
    .sort((a, b) => (a.trial_ends_on ?? "").localeCompare(b.trial_ends_on ?? ""));

  const restricted = shops.filter((shop) => shop.status === "restricted");
  const currency = summary?.currency ?? "ETB";

  return (
    <AdminShell>
      <PageHead
        title="Overview"
        subtitle={`${shops.length} shop(s) on the platform`}
        actions={
          <button type="button" className="secondary" onClick={() => void runBilling()} disabled={busy}>
            {busy ? "Running…" : "Run billing cycle"}
          </button>
        }
      />

      <Alert>{error}</Alert>
      {notice && <Alert kind="ok">{notice}</Alert>}

      <div className="grid">
        <Stat
          label="Collected"
          value={money(summary?.collected ?? "0", currency)}
          note={`from ${summary?.paying_shops ?? 0} shop(s)`}
        />
        <Stat
          label="Outstanding"
          value={money(summary?.outstanding ?? "0", currency)}
          note={`${summary?.shops_in_arrears ?? 0} shop(s) owing`}
          tone={Number(summary?.outstanding ?? 0) > 0 ? "warn" : "muted"}
        />
        <Stat
          label="Overdue"
          value={money(summary?.overdue ?? "0", currency)}
          note={`${summary?.overdue_count ?? 0} invoice(s) past due`}
          tone={Number(summary?.overdue ?? 0) > 0 ? "danger" : "muted"}
        />
        <Stat label="Billed in total" value={money(summary?.billed ?? "0", currency)} />
      </div>

      <div className="grid" style={{ marginTop: 8 }}>
        {(["active", "trial", "restricted", "suspended"] as const).map((status) => (
          <Stat
            key={status}
            label={status === "restricted" ? "Read-only" : status}
            value={counts[status] ?? 0}
            note={SHOP_STATUS_NOTE[status]}
            tone={status === "suspended" ? "danger" : status === "restricted" ? "warn" : "muted"}
          />
        ))}
      </div>

      <section className="card">
        <div className="card-title">Owed and overdue</div>
        {overdue.length === 0 ? (
          <Empty title="Nothing overdue">
            Every issued invoice is either paid or still within its terms.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Shop</th>
                <th>Invoice</th>
                <th>Due</th>
                <th className="num">Owing</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {overdue.map((invoice) => (
                <tr key={invoice.id}>
                  <td>
                    <Link href={`/admin/shops/${invoice.tenant_id}`}>
                      {invoice.tenant_name ?? "—"}
                    </Link>
                  </td>
                  <td>
                    {invoice.number} <InvoiceStatus status={invoice.status} />
                  </td>
                  <td>{shortDate(invoice.due_on)}</td>
                  <td className="num">{money(invoice.balance_due, invoice.currency)}</td>
                  <td className="num">
                    <Link href={`/admin/shops/${invoice.tenant_id}`} className="link">
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="grid">
        <div className="card">
          <div className="card-title">Trials ending within {SOON_DAYS} days</div>
          {endingSoon.length === 0 ? (
            <p className="muted">None.</p>
          ) : (
            <ul className="menu-list">
              {endingSoon.map((shop) => (
                <li key={shop.id}>
                  <Link href={`/admin/shops/${shop.id}`}>{shop.name}</Link>
                  <span className="muted"> · ends {shortDate(shop.trial_ends_on)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <div className="card-title">Read-only shops</div>
          <p className="muted" style={{ marginTop: 0 }}>
            Their data is intact. Paying the latest invoice brings them back.
          </p>
          {restricted.length === 0 ? (
            <p className="muted">None.</p>
          ) : (
            <ul className="menu-list">
              {restricted.map((shop) => (
                <li key={shop.id}>
                  <Link href={`/admin/shops/${shop.id}`}>{shop.name}</Link>{" "}
                  <ShopStatus status={shop.status} note={SHOP_STATUS_NOTE[shop.status]} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </AdminShell>
  );
}
