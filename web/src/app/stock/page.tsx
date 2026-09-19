"use client";

import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Empty, Field, PageHead } from "@/components/ui";
import { api, type StockLevel } from "@/lib/api";
import { quantity } from "@/lib/format";

export default function StockPage() {
  return (
    <AppShell>
      <Stock />
    </AppShell>
  );
}

function Stock() {
  const [items, setItems] = useState<StockLevel[]>([]);
  const [search, setSearch] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const timer = setTimeout(() => {
      const request = lowOnly
        ? api.lowStock()
        : api.stockLevels({ q: search || undefined, limit: 200 }).then((page) => page.items);
      request
        .then((rows) => {
          setItems(rows);
          setError(null);
        })
        .catch((cause) =>
          setError(cause instanceof Error ? cause.message : "Could not load stock"),
        )
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(timer);
  }, [search, lowOnly]);

  return (
    <>
      <PageHead
        title="Stock"
        subtitle={loading ? "Loading…" : `${items.length} line${items.length === 1 ? "" : "s"}`}
        actions={
          <button
            type="button"
            className={lowOnly ? undefined : "secondary"}
            onClick={() => setLowOnly((value) => !value)}
          >
            {lowOnly ? "Showing low stock" : "Show low stock"}
          </button>
        }
      />

      <Alert>{error}</Alert>

      <div className="card">
        {!lowOnly && (
          <Field label="Search">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Product name…"
            />
          </Field>
        )}

        {items.length === 0 && !loading ? (
          <Empty title={lowOnly ? "Nothing needs restocking" : "No stock recorded"}>
            <p>
              {lowOnly
                ? "Every tracked product is above its reorder level."
                : "Add products with an opening quantity, or receive stock from a supplier."}
            </p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Branch</th>
                  <th className="num">On hand</th>
                  <th className="num">Min</th>
                  <th className="num">Reorder at</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={`${row.variant_id}-${row.branch_id}`}>
                    <td>{row.name}</td>
                    <td className="muted">{row.branch_name ?? "—"}</td>
                    <td className="num">{quantity(row.quantity)}</td>
                    <td className="num muted">{quantity(row.min_stock)}</td>
                    <td className="num muted">{quantity(row.reorder_level)}</td>
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
    </>
  );
}
