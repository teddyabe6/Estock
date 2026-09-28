"use client";

/**
 * The cart, grouped by shop, with the two ways out: check out as orders, or
 * send the chosen shops a proforma request. Nothing is reserved either way.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ProductImage, Stepper, StorefrontShell } from "@/components/Storefront";
import { Alert, Empty } from "@/components/ui";
import { money } from "@/lib/format";
import { useCart } from "@/lib/storefront";

export default function CartPage() {
  const router = useRouter();
  const cart = useCart();
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const currency = "ETB";

  useEffect(() => {
    setSelected((current) => {
      const next = { ...current };
      for (const group of cart.groups) if (next[group.shop.slug] === undefined) next[group.shop.slug] = true;
      return next;
    });
  }, [cart.groups]);

  const chosen = cart.groups.filter((g) => selected[g.shop.slug] !== false);
  const orderable = cart.groups.filter((g) => g.shop.accepts_orders && g.lines.every((l) => l.price !== null));
  const requestOnly = cart.groups.filter((g) => !orderable.includes(g));

  function checkout(mode: "order" | "proforma") {
    const shops = (mode === "order" ? orderable : chosen).map((g) => g.shop.slug);
    router.push(`/checkout?mode=${mode}&shops=${encodeURIComponent(shops.join(","))}`);
  }

  return (
    <StorefrontShell title="Your cart" homeHref="/market" showBar={false}>
      {cart.loaded && cart.lines.length === 0 ? (
        <Empty title="Your cart is empty">
          <p>
            <Link href="/market">Browse the marketplace</Link> and add what you need, from any shop.
          </p>
        </Empty>
      ) : (
        <>
          {cart.groups.map((group) => (
            <section key={group.shop.slug} className="card basket-lines">
              <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
                <label className="row" style={{ gap: 8, fontWeight: 600 }}>
                  <input
                    type="checkbox"
                    style={{ width: "auto" }}
                    checked={selected[group.shop.slug] !== false}
                    onChange={(e) => setSelected({ ...selected, [group.shop.slug]: e.target.checked })}
                    aria-label={`Include ${group.shop.display_name} in a proforma request`}
                  />
                  <Link href={`/shop/${group.shop.slug}`}>{group.shop.display_name}</Link>
                </label>
                <div className="row" style={{ gap: 10 }}>
                  {!group.shop.accepts_orders && <span className="badge">proforma requests only</span>}
                  <button type="button" className="link" onClick={() => cart.removeShop(group.shop.slug)}>
                    Remove all
                  </button>
                </div>
              </div>
              {group.lines.map((line) => (
                <div key={line.variantId} className="line">
                  <ProductImage src={line.imageUrl} name={line.name} className="thumb small" />
                  <div>
                    <Link href={`/shop/${line.shop.slug}/p/${line.productId}`} className="name">
                      {line.name}
                      {line.variantName ? ` — ${line.variantName}` : ""}
                    </Link>
                    <div className="muted" style={{ fontSize: "0.85rem" }}>
                      {line.price ? `${money(line.price, currency)} / ${line.unit}` : "Price on request"}
                    </div>
                    <div className="row" style={{ marginTop: 6 }}>
                      <Stepper value={line.quantity} onChange={(q) => cart.setQuantity(line.variantId, q)} />
                      <button type="button" className="link" onClick={() => cart.remove(line.variantId)}>
                        Remove
                      </button>
                    </div>
                  </div>
                  <div className="num line-total">
                    {line.price ? money(Number(line.price) * line.quantity, currency) : "—"}
                  </div>
                </div>
              ))}
              <div className="totals">
                <span className="muted">From this shop, before delivery</span>
                <strong>{group.total !== null ? money(group.total, currency) : "On request"}</strong>
              </div>
            </section>
          ))}

          <section className="card">
            <div className="card-title">What next?</div>
            <div className="choice-grid">
              <div className="choice">
                <strong>Order now</strong>
                <p className="muted">
                  Each shop receives its own order and confirms it. You choose how you will pay; nothing is charged
                  online.
                </p>
                {requestOnly.length > 0 && (
                  <Alert kind="warn">
                    {requestOnly.map((g) => g.shop.display_name).join(", ")}{" "}
                    {requestOnly.length === 1 ? "takes" : "take"} proforma requests only, so ordering covers the other
                    shops.
                  </Alert>
                )}
                <button type="button" onClick={() => checkout("order")} disabled={orderable.length === 0}>
                  Checkout {orderable.length > 0 && cart.groups.length > 1 ? `(${orderable.length} shop${orderable.length === 1 ? "" : "s"})` : ""}
                </button>
              </div>
              <div className="choice">
                <strong>Request a proforma</strong>
                <p className="muted">
                  Tick the shops above to include. Each one gets only its own items and sends you its priced
                  proforma to accept.
                </p>
                <button type="button" className="secondary" onClick={() => checkout("proforma")} disabled={chosen.length === 0}>
                  Request from {chosen.length} shop{chosen.length === 1 ? "" : "s"}
                </button>
              </div>
            </div>
          </section>
        </>
      )}
    </StorefrontShell>
  );
}
