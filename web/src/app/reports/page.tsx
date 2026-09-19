"use client";

import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Empty, PageHead, Stat } from "@/components/ui";
import { request } from "@/lib/api";
import { money, quantity } from "@/lib/format";
import { useSession } from "@/lib/session";

type SalesReport = {
  summary: {
    period: { start: string; end: string };
    currency: string;
    sale_count: number;
    items_sold: string;
    gross_sales: string;
    discounts: string;
    tax: string;
    net_sales: string;
    cost_of_goods?: string;
    gross_profit?: string;
    profit_basis?: string;
  };
  by_day: Array<{ date: string; sale_count: number; total: string }>;
  by_payment_method: Array<{ method: string; count: number; total: string }>;
  basis: string;
};

const PERIODS = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "month", label: "This month" },
  { value: "year", label: "This year" },
];

export default function ReportsPage() {
  return (
    <AppShell>
      <Reports />
    </AppShell>
  );
}

function Reports() {
  const { session } = useSession();
  const [period, setPeriod] = useState("30d");
  const [report, setReport] = useState<SalesReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    request<SalesReport>(`/reports/sales?period=${period}`)
      .then((data) => {
        setReport(data);
        setError(null);
      })
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "Could not load the report"),
      )
      .finally(() => setLoading(false));
  }, [period]);

  const currency = report?.summary.currency ?? session?.currency ?? "ETB";
  const maxDay = Math.max(
    1,
    ...(report?.by_day ?? []).map((row) => Number(row.total)),
  );

  return (
    <>
      <PageHead
        title="Sales report"
        subtitle={
          report
            ? `${report.summary.period.start} to ${report.summary.period.end} · ${currency}`
            : "Loading…"
        }
        actions={PERIODS.map((option) => (
          <button
            key={option.value}
            type="button"
            className={period === option.value ? undefined : "secondary"}
            onClick={() => setPeriod(option.value)}
          >
            {option.label}
          </button>
        ))}
      />

      <Alert>{error}</Alert>

      {report && (
        <>
          <div className="grid">
            <Stat label="Net sales" value={money(report.summary.net_sales, currency)} />
            <Stat label="Orders" value={report.summary.sale_count} />
            <Stat label="Items sold" value={quantity(report.summary.items_sold)} />
            <Stat label="Discounts" value={money(report.summary.discounts, currency)} />
            {report.summary.gross_profit !== undefined && (
              <Stat
                label="Gross profit"
                value={money(report.summary.gross_profit, currency)}
                note={report.summary.profit_basis}
              />
            )}
          </div>

          <div className="card">
            <div className="card-title">By day</div>
            {report.by_day.length === 0 ? (
              <Empty title="No sales in this period" />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th className="num">Orders</th>
                      <th className="num">Total</th>
                      <th style={{ width: "40%" }} />
                    </tr>
                  </thead>
                  <tbody>
                    {report.by_day.map((row) => (
                      <tr key={row.date}>
                        <td>{row.date}</td>
                        <td className="num">{row.sale_count}</td>
                        <td className="num">{money(row.total, currency)}</td>
                        <td>
                          <div
                            aria-hidden
                            style={{
                              height: 8,
                              borderRadius: 4,
                              background: "var(--brand)",
                              opacity: 0.85,
                              width: `${(Number(row.total) / maxDay) * 100}%`,
                              minWidth: 2,
                            }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <div className="card-title">By payment method</div>
            {report.by_payment_method.length === 0 ? (
              <Empty title="No payments in this period" />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Method</th>
                      <th className="num">Payments</th>
                      <th className="num">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.by_payment_method.map((row) => (
                      <tr key={row.method}>
                        <td>{row.method.replace(/_/g, " ")}</td>
                        <td className="num">{row.count}</td>
                        <td className="num">{money(row.total, currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <p className="muted" style={{ fontSize: "0.85rem" }}>
            {report.basis}
          </p>
        </>
      )}

      {!report && !error && loading && <Empty title="Loading…" />}
    </>
  );
}
