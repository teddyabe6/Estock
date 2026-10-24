"use client";

/**
 * What has happened across the platform, newest first.
 *
 * The same append-only trail each shop sees for itself, read across shops —
 * including every privileged thing the operator has done, which is the point:
 * support access and status changes are recorded against the shop they
 * affected, not hidden in a console log.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "@/components/AdminShell";
import { Alert, Empty, PageHead } from "@/components/ui";
import { adminApi, type AuditRow, type ShopRow } from "@/lib/admin";
import { useAdmin, useAdminCall } from "@/lib/adminSession";
import { dateTime } from "@/lib/format";

/** The actions an operator is usually looking for, named in plain words. */
const LABELS: Record<string, string> = {
  "tenant.registered": "Shop registered",
  "tenant.status_changed": "Access changed",
  "subscription.changed": "Subscription changed",
  "subscription.invoice_issued": "Invoice issued",
  "subscription.invoice_voided": "Invoice voided",
  "subscription.payment_recorded": "Payment recorded",
  "subscription.payment_reversed": "Payment reversed",
  "subscription.renewed": "Service renewed",
  "subscription.lapsed": "Subscription lapsed",
  "platform.support_access": "Support access granted",
  "platform.setting_changed": "Platform setting changed",
  // The shop's own events show up here too, since this trail is read across
  // shops; naming them keeps the column readable rather than half raw keys.
  "sale.completed": "Sale",
  "sale.voided": "Sale voided",
  "sale.returned": "Return",
  "purchase.received": "Stock received",
  "payment.recorded": "Customer payment",
  "payment.reversed": "Customer payment reversed",
  "quotation.sent": "Proforma sent",
  "quotation.converted": "Proforma became a sale",
  "stock.adjusted": "Stock adjusted",
  "user.invited": "Staff invited",
  "user.disabled": "Staff disabled",
};

export default function AdminAuditPage() {
  const { admin, signOut } = useAdmin();
  const describe = useAdminCall(signOut);

  const [events, setEvents] = useState<AuditRow[]>([]);
  const [shops, setShops] = useState<ShopRow[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // A tenant may be pre-selected from a shop page's link.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const fromLink = new URLSearchParams(window.location.search).get("tenant_id");
    if (fromLink) setTenantId(fromLink);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [rows, shopPage] = await Promise.all([
        adminApi.auditEvents({ tenant_id: tenantId || undefined, limit: 200 }),
        adminApi.shops({ limit: 200 }),
      ]);
      setEvents(rows);
      setShops(shopPage.items);
      setError(null);
    } catch (cause) {
      setError(describe(cause, "Could not load the activity trail"));
    } finally {
      setLoading(false);
    }
  }, [describe, tenantId]);

  useEffect(() => {
    if (admin) void load();
  }, [admin, load]);

  const nameFor = (id: string | null) =>
    id ? (shops.find((shop) => shop.id === id)?.name ?? "—") : "platform";

  return (
    <AdminShell>
      <PageHead title="Activity" subtitle="Across every shop, newest first" />

      <Alert>{error}</Alert>

      <div className="search-row">
        <select
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          aria-label="Filter by shop"
        >
          <option value="">Every shop</option>
          {shops.map((shop) => (
            <option key={shop.id} value={shop.id}>
              {shop.name}
            </option>
          ))}
        </select>
      </div>

      {loading && events.length === 0 ? (
        <p className="muted">Loading…</p>
      ) : events.length === 0 ? (
        <Empty title="Nothing recorded yet">
          Privileged and financially material actions show up here as they happen.
        </Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>What</th>
              <th>Shop</th>
              <th>Who</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id}>
                <td>{dateTime(event.created_at)}</td>
                <td>{LABELS[event.action] ?? event.action.replace(/[._]/g, " ")}</td>
                <td>
                  {event.tenant_id ? (
                    <Link href={`/admin/shops/${event.tenant_id}`}>
                      {nameFor(event.tenant_id)}
                    </Link>
                  ) : (
                    <span className="muted">platform</span>
                  )}
                </td>
                <td className="muted">{event.actor_label ?? "—"}</td>
                <td>{event.summary ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </AdminShell>
  );
}
