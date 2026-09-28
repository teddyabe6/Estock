"use client";

/**
 * The customer's tracking page for one checkout: each shop's order or
 * proforma request, its status and what happens next.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useCallback, useEffect, useState } from "react";

import { StorefrontShell } from "@/components/Storefront";
import { Alert } from "@/components/ui";
import { money, shortDate } from "@/lib/format";
import {
  orderLabel,
  orderTone,
  paymentLabel,
  proformaLabel,
  proformaTone,
  shopApi,
  type CheckoutPart,
  type CheckoutView,
} from "@/lib/storefront";

export default function TrackPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  return (
    <Suspense fallback={null}>
      <Tracking token={token} />
    </Suspense>
  );
}

function Tracking({ token }: { token: string }) {
  const search = useSearchParams();
  const isNew = search.get("new") === "1";
  const [view, setView] = useState<CheckoutView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    shopApi
      .track(token)
      .then(setView)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "This link is no longer valid"));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  async function cancel(part: CheckoutPart) {
    if (!part.token) return;
    const reason = window.prompt("Cancel this order? Tell the shop why (optional):");
    if (reason === null) return;
    try {
      const result = await shopApi.cancelOrder(part.token, reason);
      setNotice(result.message);
      load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not cancel");
    }
  }

  if (error) {
    return (
      <StorefrontShell title="Tracking" showBar={false}>
        <Alert>{error}</Alert>
      </StorefrontShell>
    );
  }

  return (
    <StorefrontShell title={view?.kind === "proforma" ? "Your proforma requests" : "Your orders"} showBar={false}>
      {!view ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          {isNew && (
            <Alert kind="ok">
              Thank you, {view.customer.name}. {view.parts.length === 1 ? "The shop has" : `${view.parts.length} shops have`}{" "}
              {view.kind === "order" ? "your order" : "your request"}. Keep this link to follow it.
            </Alert>
          )}
          {notice && <Alert kind="ok">{notice}</Alert>}
          <p className="muted" style={{ fontSize: "0.88rem" }}>
            {view.kind === "order" ? "Placed" : "Requested"} {shortDate(view.created_at)} · {view.customer.phone}
            {view.customer.delivery_location ? ` · ${view.customer.delivery_location}` : ""}
          </p>

          {view.parts.map((part) => (
            <section key={part.number} className="card">
              <div className="page-head" style={{ marginBottom: 8 }}>
                <div>
                  <h2 style={{ margin: 0 }}>
                    {part.shop ? <Link href={`/shop/${part.shop.slug}`}>{part.shop.display_name}</Link> : "Shop"}
                  </h2>
                  <p>
                    {part.kind === "order" ? "Order" : "Proforma"} {part.number}
                  </p>
                </div>
                <span className={`badge ${part.kind === "order" ? orderTone(part.status) : proformaTone(part.status)}`}>
                  {part.kind === "order" ? orderLabel(part.status) : proformaLabel(part.status)}
                </span>
              </div>
              {part.next_step && <p className="next-step">{part.next_step}</p>}
              {part.seller_note && <p>{part.seller_note}</p>}

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th className="num">Qty</th>
                      {part.amounts_visible !== false && <th className="num">Total</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {part.lines.map((line, index) => (
                      <tr key={`${line.description}-${index}`}>
                        <td>{line.description}</td>
                        <td className="num">{Number(line.quantity).toLocaleString()}</td>
                        {part.amounts_visible !== false && (
                          <td className="num">{line.line_total ? money(line.line_total, part.currency) : "—"}</td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                  {part.amounts_visible !== false && (
                    <tfoot>
                      {Number(part.delivery_charge ?? 0) > 0 && (
                        <tr>
                          <td colSpan={2} className="num muted">
                            Delivery
                          </td>
                          <td className="num">{money(part.delivery_charge, part.currency)}</td>
                        </tr>
                      )}
                      <tr>
                        <td colSpan={2} className="num">
                          <strong>{part.status === "requested" ? "Estimated total" : "Total"}</strong>
                        </td>
                        <td className="num">
                          <strong>{part.total_amount ? money(part.total_amount, part.currency) : "—"}</strong>
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>

              {part.kind === "order" && (
                <p className="muted" style={{ fontSize: "0.88rem" }}>
                  {paymentLabel(part.payment_method)} ·{" "}
                  {part.delivery_method === "pickup" ? "pickup at the shop" : `delivery${part.delivery_location ? ` to ${part.delivery_location}` : ""}`}
                </p>
              )}

              <div className="row no-print">
                {part.kind === "proforma" && part.url && (
                  <Link href={part.url.replace(/^https?:\/\/[^/]+/, "")} className="btn">
                    {part.status === "sent" ? "Open and accept the proforma" : "Open the proforma"}
                  </Link>
                )}
                {part.kind === "order" && part.can_cancel && (
                  <button type="button" className="secondary" onClick={() => void cancel(part)}>
                    Cancel this order
                  </button>
                )}
                {part.shop?.contact_phone && (
                  <a href={`tel:${part.shop.contact_phone.replace(/[^\d+]/g, "")}`} className="btn secondary">
                    Call {part.shop.display_name}
                  </a>
                )}
                {part.shop?.telegram_username && (
                  <a
                    href={`https://t.me/${part.shop.telegram_username.replace(/^@/, "")}`}
                    target="_blank"
                    rel="noreferrer"
                    className="btn secondary"
                  >
                    Telegram
                  </a>
                )}
              </div>
            </section>
          ))}
          <p className="muted no-print" style={{ textAlign: "center", fontSize: "0.85rem" }}>
            <Link href="/market">Back to the marketplace</Link>
          </p>
        </>
      )}
    </StorefrontShell>
  );
}
