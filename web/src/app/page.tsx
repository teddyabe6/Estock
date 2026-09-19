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
  const { session } = useSession();
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

      {data?.today && (
        <div className="grid">
          <Stat label="Sales today" value={money(data.today.net_sales, currency)} />
          <Stat label="Orders" value={data.today.sale_count} />
          <Stat label="Items sold" value={quantity(data.today.items_sold)} />
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
                />
                <Stat
                  label="Due within 7 days"
                  value={money(data.receivables.due_within_7_days, currency)}
                  tone={Number(data.receivables.due_within_7_days) > 0 ? "warn" : "muted"}
                />
                <Stat
                  label="Overdue"
                  value={money(data.receivables.overdue, currency)}
                  tone={Number(data.receivables.overdue) > 0 ? "danger" : "muted"}
                />
              </>
            )}
            {data.payables && (
              <Stat
                label="You owe suppliers"
                value={money(data.payables.total_outstanding, currency)}
                note={`${data.payables.transaction_count} open balance(s)`}
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
                    <th className="num">On hand</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.low_stock.map((item) => (
                    <tr key={`${item.product_id}-${item.name}`}>
                      <td>{item.name}</td>
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
