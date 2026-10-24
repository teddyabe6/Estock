"use client";

/** Every registered shop, searchable, with what it is and how much it uses. */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell, ShopStatus } from "@/components/AdminShell";
import { Alert, Empty, PageHead } from "@/components/ui";
import { adminApi, SHOP_STATUS_NOTE, SHOP_STATUSES, type ShopRow } from "@/lib/admin";
import { useAdmin, useAdminCall } from "@/lib/adminSession";
import { shortDate } from "@/lib/format";

const PAGE = 50;

export default function AdminShopsPage() {
  const { admin, signOut } = useAdmin();
  const describe = useAdminCall(signOut);

  const [shops, setShops] = useState<ShopRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await adminApi.shops({
        q: query || undefined,
        status: status || undefined,
        limit: PAGE,
        offset,
      });
      setShops(page.items);
      setTotal(page.total);
      setError(null);
    } catch (cause) {
      setError(describe(cause, "Could not load the shops"));
    } finally {
      setLoading(false);
    }
  }, [describe, query, status, offset]);

  useEffect(() => {
    if (!admin) return;
    const timer = setTimeout(() => void load(), query ? 250 : 0);
    return () => clearTimeout(timer);
  }, [admin, load, query]);

  return (
    <AdminShell>
      <PageHead title="Shops" subtitle={`${total} registered`} />

      <Alert>{error}</Alert>

      <div className="search-row">
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
          placeholder="Search by name"
          aria-label="Search shops"
        />
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
          {SHOP_STATUSES.map((value) => (
            <button
              key={value}
              type="button"
              className={status === value ? "chip is-active" : "chip"}
              title={SHOP_STATUS_NOTE[value]}
              onClick={() => {
                setStatus(value);
                setOffset(0);
              }}
            >
              {value === "restricted" ? "read-only" : value}
            </button>
          ))}
        </div>
      </div>

      {loading && shops.length === 0 ? (
        <p className="muted">Loading…</p>
      ) : shops.length === 0 ? (
        <Empty title="No shops match">Try a different name or status.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Shop</th>
              <th>Status</th>
              <th>Subscription</th>
              <th>Trial ends</th>
              <th className="num">Users</th>
              <th className="num">Products</th>
              <th className="num">Sales</th>
              <th>Joined</th>
            </tr>
          </thead>
          <tbody>
            {shops.map((shop) => (
              <tr key={shop.id}>
                <td>
                  <Link href={`/admin/shops/${shop.id}`}>{shop.name}</Link>
                  <br />
                  <span className="muted" style={{ fontSize: "0.85rem" }}>
                    /{shop.slug}
                  </span>
                </td>
                <td>
                  <ShopStatus status={shop.status} note={SHOP_STATUS_NOTE[shop.status]} />
                </td>
                <td className="muted">{shop.subscription_status ?? "—"}</td>
                <td>{shortDate(shop.trial_ends_on) || "—"}</td>
                <td className="num">{shop.user_count}</td>
                <td className="num">{shop.product_count}</td>
                <td className="num">{shop.sale_count}</td>
                <td>{shortDate(shop.created_at)}</td>
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
    </AdminShell>
  );
}
