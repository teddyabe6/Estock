"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Empty, PageHead, Toggle } from "@/components/ui";
import { api, type Sale } from "@/lib/api";
import { amount, dateTime } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

export default function SalesPage() {
  return (
    <AppShell>
      <Sales />
    </AppShell>
  );
}

function Sales() {
  const { session, can, canWrite } = useSession();
  const [items, setItems] = useState<Sale[]>([]);
  const [total, setTotal] = useState(0);
  const [includeVoided, setIncludeVoided] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .sales({ limit: 100, include_voided: includeVoided })
      .then((page) => {
        setItems(page.items);
        setTotal(page.total);
        setError(null);
      })
      .catch((cause) => setError(describeError(cause, "Could not load sales")))
      .finally(() => setLoading(false));
  }, [includeVoided]);

  const currency = session?.currency ?? "ETB";

  return (
    <>
      <PageHead
        title="Sales"
        subtitle={loading ? "Loading…" : `${total} recorded`}
        actions={
          canWrite && can("sale:create") ? (
            <Link href="/sales/new">
              <button type="button">New sale</button>
            </Link>
          ) : null
        }
      />

      <Alert>{error}</Alert>

      <div className="card">
        <Toggle label="Show voided sales" checked={includeVoided} onChange={setIncludeVoided} />
        {items.length === 0 && !loading ? (
          <Empty title="No sales yet">
            <p>Your first sale will appear here.</p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Number</th>
                  <th>When</th>
                  <th className="num">Total ({currency})</th>
                  <th className="num">Paid</th>
                  <th className="num">Balance</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((sale) => (
                  <tr key={sale.id}>
                    <td className="nowrap">
                      <Link href={`/sales/${sale.id}`}>{sale.number}</Link>
                    </td>
                    <td className="muted nowrap">{dateTime(sale.sold_at)}</td>
                    <td className="num">{amount(sale.total_amount)}</td>
                    <td className="num">{amount(sale.amount_paid)}</td>
                    <td className="num">
                      {Number(sale.balance_due) > 0 ? (
                        <strong>{amount(sale.balance_due)}</strong>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="nowrap">
                      <Badge status={sale.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
