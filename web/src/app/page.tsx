"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Empty, PageHead, Stat } from "@/components/ui";
import { api, type Dashboard } from "@/lib/api";
import { money, quantity, shortDate } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function HomePage() {
  return (
    <AppShell>
      <Home />
    </AppShell>
  );
}

function Home() {
  const { session, can, canWrite } = useSession();
  const mayCount = canWrite && can("stock:adjust");
  // A single-shop business never needs telling which branch it is.
  const manyBranches = (session?.branches.length ?? 0) > 1;
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "Could not load the dashboard"),
      );
  }, []);

  const currency = data?.currency ?? session?.currency ?? "ETB";
  // The shop's own today, not the browser's: a till in Addis closing at
  // midnight local is still yesterday's takings to a server in UTC.
  const soldToday = data ? `/sales?date_from=${data.date}&date_to=${data.date}` : "/sales";

  return (
    <>
      <PageHead
        title="Home"
        subtitle={data ? `Today, ${shortDate(data.date)}` : "Loading…"}
        actions={
          session?.permissions.includes("sale:create") ? (
            <Link href="/sales/new">
              <button type="button">New sale</button>
            </Link>
          ) : null
        }
      />

      <Alert>{error}</Alert>

      {mayCount && data?.stock_setup && data.stock_setup.length > 0 && (
        <div className="alert warn" role="status" style={{ marginBottom: 12 }}>
          <strong>
            {data.stock_setup.length === 1
              ? `${data.stock_setup[0].branch_name} has no stock recorded yet.`
              : `${data.stock_setup.length} branches have no stock recorded yet.`}
          </strong>{" "}
          Every product is available there with nothing on hand.{" "}
          <Link href={`/stock?tab=opening&branch=${data.stock_setup[0].branch_id}`}>
            Record what is on the shelves →
          </Link>
        </div>
      )}

      {data?.today && (
        <div className="grid">
          {/* Each of today's figures opens the sales it was added up from.
              Profit is not one of them: it is worked out from cost against
              revenue, so there is no list of profits to show. */}
          <Stat label="Sales today" value={money(data.today.net_sales, currency)} href={soldToday} />
          <Stat label="Orders" value={data.today.sale_count} href={soldToday} />
          <Stat label="Items sold" value={quantity(data.today.items_sold)} href={soldToday} />
          {data.today.gross_profit !== undefined && (
            <Stat
              label="Gross profit"
              value={money(data.today.gross_profit, currency)}
              note={data.today.profit_basis}
            />
          )}
        </div>
      )}

      {(data?.receivables || data?.payables) && (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="card-title">Money owed</div>
          <div className="grid">
            {data.receivables && (
              <>
                <Stat
                  label="Customers owe you"
                  value={money(data.receivables.total_outstanding, currency)}
                  note={`${data.receivables.transaction_count} open balance(s)`}
                  href="/credit?kind=receivable&view=outstanding"
                />
                <Stat
                  label="Due within 7 days"
                  value={money(data.receivables.due_within_7_days, currency)}
                  tone={Number(data.receivables.due_within_7_days) > 0 ? "warn" : "muted"}
                  href="/credit?kind=receivable&view=due_soon"
                />
                <Stat
                  label="Overdue"
                  value={money(data.receivables.overdue, currency)}
                  tone={Number(data.receivables.overdue) > 0 ? "danger" : "muted"}
                  href="/credit?kind=receivable&view=overdue"
                />
              </>
            )}
            {data.payables && (
              <Stat
                label="You owe suppliers"
                value={money(data.payables.total_outstanding, currency)}
                note={`${data.payables.transaction_count} open balance(s)`}
                href="/credit?kind=payable&view=outstanding"
              />
            )}
          </div>
          <p style={{ marginTop: 10, marginBottom: 0 }}>
            <Link href="/credit">Open the credit list →</Link>
          </p>
        </div>
      )}

      {data?.low_stock !== undefined && (
        <div className="card">
          <div className="card-title">
            Low stock {data.low_stock_count ? `(${data.low_stock_count})` : ""}
          </div>
          {data.low_stock.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              Nothing needs restocking right now.
            </p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Product</th>
                    {manyBranches && <th>Branch</th>}
                    <th className="num">On hand</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {/* Keyed by branch as well: the same product can be short at
                      one branch and fine at another, and those are two rows. */}
                  {data.low_stock.map((item) => (
                    <tr key={`${item.variant_id}-${item.branch_id}`}>
                      <td>{item.name}</td>
                      {manyBranches && <td className="muted">{item.branch_name}</td>}
                      <td className="num">{quantity(item.quantity)}</td>
                      <td>
                        <span
                          className={`badge ${
                            item.severity === "out_of_stock" || item.severity === "critical"
                              ? "danger"
                              : "warn"
                          }`}
                        >
                          {item.severity.replace(/_/g, " ")}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {data?.setup && !data.setup_complete && (
        <div className="card">
          <div className="card-title">Finish setting up</div>
          <ul className="checklist">
            {data.setup.map((step) => (
              <li key={step.key} className={step.done ? "done" : undefined}>
                <span className="tick" aria-hidden>
                  {step.done ? "✓" : ""}
                </span>
                <span>
                  {step.done || !step.action_url ? (
                    step.label
                  ) : (
                    <Link href={step.action_url}>{step.label}</Link>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!data && !error && <Empty title="Loading your dashboard…" />}
    </>
  );
}
