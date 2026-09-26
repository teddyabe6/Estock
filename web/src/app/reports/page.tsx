"use client";

/**
 * Reports (PRD 15). Every figure states its period, currency and basis. A
 * ranking is a data view for the stated period, not a verdict on a branch or
 * a person.
 */

import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Empty, PageHead, Stat, Tabs } from "@/components/ui";
import {
  api,
  type BranchReport,
  type CreditReport,
  type InventoryReport,
  type ProductReport,
  type ReportPeriod,
  type SalesReport,
} from "@/lib/api";
import { money, quantity } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

const PERIODS: Array<{ value: ReportPeriod; label: string }> = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "month", label: "This month" },
  { value: "year", label: "This year" },
];

type Tab = "sales" | "products" | "branches" | "inventory" | "credit";

export default function ReportsPage() {
  return (
    <AppShell>
      <Reports />
    </AppShell>
  );
}

function Reports() {
  const { can } = useSession();
  const [tab, setTab] = useState<Tab>("sales");
  const [period, setPeriod] = useState<ReportPeriod>("30d");
  const tabs = [
    { value: "sales" as const, label: "Sales", show: can("report:sales") },
    { value: "products" as const, label: "Products", show: can("report:sales") },
    { value: "branches" as const, label: "Branches", show: can("report:branch_compare") },
    { value: "inventory" as const, label: "Inventory", show: can("report:inventory") },
    { value: "credit" as const, label: "Credit", show: can("report:credit") },
  ].filter((t) => t.show);
  const periodic = tab === "sales" || tab === "products" || tab === "branches";

  return (
    <>
      <PageHead
        title="Reports"
        actions={
          periodic ? (
            <Tabs value={period} options={PERIODS} onChange={setPeriod} />
          ) : null
        }
      />
      <Tabs value={tab} options={tabs} onChange={setTab} />
      {tab === "sales" && <Sales period={period} />}
      {tab === "products" && <Products period={period} />}
      {tab === "branches" && <Branches period={period} />}
      {tab === "inventory" && <Inventory />}
      {tab === "credit" && <Credit />}
    </>
  );
}

function useReport<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setData(null);
    loader()
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((cause) => setError(describeError(cause, "Could not load the report")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, setError };
}

function PeriodLine({ period, currency, extra }: { period: { start: string; end: string; timezone?: string }; currency: string; extra?: string }) {
  return (
    <p className="muted" style={{ fontSize: "0.85rem" }}>
      {period.start} to {period.end} · {currency}
      {period.timezone ? ` · days in ${period.timezone}` : ""}
      {extra ? ` · ${extra}` : ""}
    </p>
  );
}

function Sales({ period }: { period: ReportPeriod }) {
  const { session } = useSession();
  const { data: report, error, setError } = useReport<SalesReport>(() => api.salesReport(period), [period]);
  const currency = report?.summary.currency ?? session?.currency ?? "ETB";
  const maxDay = Math.max(1, ...(report?.by_day ?? []).map((row) => Number(row.total)));

  return (
    <>
      <Alert>{error}</Alert>
      {!report && !error && <Empty title="Loading…" />}
      {report && (
        <>
          <div className="grid">
            <Stat label="Net sales" value={money(report.summary.net_sales, currency)} />
            <Stat label="Orders" value={report.summary.sale_count} />
            <Stat label="Items sold" value={quantity(report.summary.items_sold)} />
            <Stat label="Discounts" value={money(report.summary.discounts, currency)} />
            {report.summary.gross_profit !== undefined && (
              <Stat label="Gross profit" value={money(report.summary.gross_profit, currency)} note={report.summary.profit_basis} />
            )}
          </div>
          <PeriodLine period={report.summary.period} currency={currency} />

          <div className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="card-title">By day</div>
              <button type="button" className="link" onClick={() => api.exportSalesReport(period).catch((c) => setError(describeError(c)))}>
                Export CSV
              </button>
            </div>
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
          <p className="muted" style={{ fontSize: "0.85rem" }}>{report.basis}</p>
        </>
      )}
    </>
  );
}

function Products({ period }: { period: ReportPeriod }) {
  const { data: report, error } = useReport<ProductReport>(() => api.productReport(period), [period]);
  const currency = report?.currency ?? "ETB";
  return (
    <>
      <Alert>{error}</Alert>
      {!report && !error && <Empty title="Loading…" />}
      {report && (
        <>
          <PeriodLine period={report.period} currency={currency} extra={report.note} />
          <div className="card">
            <div className="card-title">Products</div>
            {report.products.length === 0 ? (
              <Empty title="No sales in this period" />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th className="num">Sold</th>
                      <th className="num">Revenue</th>
                      {report.products[0]?.gross_profit !== undefined && <th className="num">Gross profit</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {report.products.map((row) => (
                      <tr key={row.product_id}>
                        <td>{row.name}</td>
                        <td className="num">{quantity(row.quantity_sold)}</td>
                        <td className="num">{money(row.revenue, currency)}</td>
                        {row.gross_profit !== undefined && <td className="num">{money(row.gross_profit, currency)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-title">Categories</div>
            {report.categories.length === 0 ? (
              <Empty title="No sales in this period" />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th className="num">Sold</th>
                      <th className="num">Revenue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.categories.map((row) => (
                      <tr key={row.category}>
                        <td>{row.category}</td>
                        <td className="num">{quantity(row.quantity_sold)}</td>
                        <td className="num">{money(row.revenue, currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}

function Branches({ period }: { period: ReportPeriod }) {
  const { data: report, error } = useReport<BranchReport>(() => api.branchReport(period), [period]);
  const currency = report?.currency ?? "ETB";
  return (
    <>
      <Alert>{error}</Alert>
      {!report && !error && <Empty title="Loading…" />}
      {report && (
        <div className="card">
          <div className="card-title">Branch comparison</div>
          <PeriodLine period={report.period} currency={currency} extra={report.note} />
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Branch</th>
                  <th className="num">Orders</th>
                  <th className="num">Sales</th>
                  {report.branches[0]?.gross_profit !== undefined && <th className="num">Gross profit</th>}
                </tr>
              </thead>
              <tbody>
                {report.branches.map((row) => (
                  <tr key={row.branch_id}>
                    <td>{row.branch_name}</td>
                    <td className="num">{row.sale_count}</td>
                    <td className="num">{money(row.total_sales, currency)}</td>
                    {row.gross_profit !== undefined && <td className="num">{money(row.gross_profit, currency)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function Inventory() {
  const { data: report, error, setError } = useReport<InventoryReport>(() => api.inventoryReport(), []);
  const currency = report?.currency ?? "ETB";
  return (
    <>
      <Alert>{error}</Alert>
      {!report && !error && <Empty title="Loading…" />}
      {report && (
        <>
          <div className="grid">
            <Stat label="Products in stock" value={report.product_count} />
            <Stat label="Units on hand" value={quantity(report.total_quantity)} />
            {report.value_at_cost !== null && (
              <Stat label="Value at cost" value={money(report.value_at_cost, currency)} note={report.valuation_basis} />
            )}
            <Stat label="Potential sales value" value={money(report.potential_sales_value, currency)} note="at current selling prices" />
            <Stat label="Low stock" value={report.low_stock_count} tone={report.low_stock_count > 0 ? "warn" : "muted"} />
          </div>
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            As of {report.as_of} · {currency} ·{" "}
            <button type="button" className="link" onClick={() => api.exportStock().catch((c) => setError(describeError(c)))}>
              Export stock on hand (CSV)
            </button>
          </p>
        </>
      )}
    </>
  );
}

function Credit() {
  const { can } = useSession();
  const [kind, setKind] = useState<"receivable" | "payable">("receivable");
  const { data: report, error } = useReport<CreditReport>(() => api.creditReport(kind), [kind]);
  const currency = report?.summary.currency ?? "ETB";
  const labels: Record<string, string> = {
    not_due: "Not yet due",
    no_due_date: "No due date",
    "1_30": "1–30 days overdue",
    "31_60": "31–60 days overdue",
    "61_90": "61–90 days overdue",
    over_90: "Over 90 days overdue",
  };
  return (
    <>
      {can("purchase:view") && (
        <Tabs
          value={kind}
          options={[
            { value: "receivable", label: "Receivables" },
            { value: "payable", label: "Payables" },
          ]}
          onChange={setKind}
        />
      )}
      <Alert>{error}</Alert>
      {!report && !error && <Empty title="Loading…" />}
      {report && (
        <>
          <div className="grid">
            <Stat label="Outstanding" value={money(report.summary.total_outstanding, currency)} note={`${report.summary.transaction_count} balance(s)`} />
            <Stat label="Due today" value={money(report.summary.due_today, currency)} />
            <Stat label="Due within 7 days" value={money(report.summary.due_within_7_days, currency)} />
            <Stat label="Overdue" value={money(report.summary.overdue, currency)} tone={Number(report.summary.overdue) > 0 ? "danger" : "muted"} />
          </div>
          <div className="card">
            <div className="card-title">Aging</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Bucket</th>
                    <th className="num">Amount ({currency})</th>
                  </tr>
                </thead>
                <tbody>
                  {report.aging.map((row) => (
                    <tr key={row.bucket}>
                      <td>{labels[row.bucket] ?? row.bucket}</td>
                      <td className="num">{money(row.amount, currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ fontSize: "0.85rem", marginBottom: 0 }}>As of {report.as_of}. {report.basis}</p>
          </div>
        </>
      )}
    </>
  );
}
