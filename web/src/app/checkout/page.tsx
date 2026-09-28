"use client";

/**
 * Checkout, in one of two modes: place an order with each shop, or send each
 * chosen shop a proforma request. No online payment; nothing reserved.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ContactFields, StorefrontShell } from "@/components/Storefront";
import { Alert, Empty, Field } from "@/components/ui";
import { money } from "@/lib/format";
import {
  PAYMENT_METHODS,
  loadVisitor,
  saveVisitor,
  shopApi,
  useCart,
  useMyCheckouts,
  type VisitorDetails,
} from "@/lib/storefront";

export default function CheckoutPage() {
  return (
    <Suspense fallback={null}>
      <Checkout />
    </Suspense>
  );
}

function Checkout() {
  const router = useRouter();
  const search = useSearchParams();
  const mode = search.get("mode") === "proforma" ? "proforma" : "order";
  const shops = useMemo(() => (search.get("shops") ?? "").split(",").filter(Boolean), [search]);
  const cart = useCart();
  const checkouts = useMyCheckouts();
  const [form, setForm] = useState<VisitorDetails>({
    contact_name: "",
    contact_phone: "",
    contact_email: "",
    company: "",
    delivery_location: "",
  });
  const [message, setMessage] = useState("");
  const [deliveryMethod, setDeliveryMethod] = useState<"delivery" | "pickup">("delivery");
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const currency = "ETB";

  useEffect(() => {
    setForm((prev) => ({ ...prev, ...loadVisitor() }));
  }, []);

  const groups = cart.groups.filter((g) => shops.length === 0 || shops.includes(g.shop.slug));
  const lines = groups.flatMap((g) => g.lines);
  const total = lines.some((l) => l.price === null) ? null : lines.reduce((s, l) => s + Number(l.price) * l.quantity, 0);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      items: lines.map((l) => ({ shop: l.shop.slug, variant_id: l.variantId, quantity: String(l.quantity) })),
      contact_name: form.contact_name,
      contact_phone: form.contact_phone,
      contact_email: form.contact_email || undefined,
      company: form.company || undefined,
      delivery_location: form.delivery_location || undefined,
      message: message || undefined,
    };
    try {
      const result =
        mode === "order"
          ? await shopApi.checkoutOrders({ ...body, delivery_method: deliveryMethod, payment_method: paymentMethod })
          : await shopApi.checkoutProformas(body);
      saveVisitor(form);
      checkouts.remember({ token: result.token, kind: result.kind, numbers: result.parts.map((p) => p.number) });
      for (const group of groups) cart.removeShop(group.shop.slug);
      router.push(`/track/${result.token}?new=1`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send");
      setBusy(false);
    }
  }

  return (
    <StorefrontShell title={mode === "order" ? "Checkout" : "Request a proforma"} homeHref="/market" showBar={false}>
      <p className="crumbs">
        <Link href="/cart">← Back to your cart</Link>
      </p>
      <Alert>{error}</Alert>
      {cart.loaded && lines.length === 0 ? (
        <Empty title="Nothing to check out">
          <p>
            <Link href="/market">Browse the marketplace</Link> and add what you need.
          </p>
        </Empty>
      ) : (
        <form onSubmit={submit}>
          <section className="card">
            <div className="card-title">
              {groups.length} shop{groups.length === 1 ? "" : "s"} · {lines.length} item{lines.length === 1 ? "" : "s"}
            </div>
            {groups.map((group) => (
              <div key={group.shop.slug} className="checkout-group">
                <strong>{group.shop.display_name}</strong>
                <ul className="muted" style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: "0.9rem" }}>
                  {group.lines.map((l) => (
                    <li key={l.variantId}>
                      {l.name}
                      {l.variantName ? ` — ${l.variantName}` : ""} × {l.quantity}
                      {l.price ? ` · ${money(Number(l.price) * l.quantity, currency)}` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <div className="totals">
              <span className="muted">
                {mode === "order" ? "Total before delivery" : "At catalogue prices, before the shops confirm"}
              </span>
              <strong>{total !== null ? money(total, currency) : "On request"}</strong>
            </div>
          </section>

          <section className="card">
            <div className="card-title">Your details</div>
            <ContactFields
              form={form}
              onChange={setForm}
              phoneHint={mode === "order" ? "the shops confirm by phone" : "the shops reply by phone"}
            />
            {mode === "order" && (
              <div className="grid">
                <Field label="Delivery">
                  <select value={deliveryMethod} onChange={(e) => setDeliveryMethod(e.target.value as "delivery" | "pickup")}>
                    <option value="delivery">Deliver to my location</option>
                    <option value="pickup">I will pick up at the shop</option>
                  </select>
                </Field>
                <Field label="How you will pay" hint="nothing is charged online">
                  <select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)}>
                    {PAYMENT_METHODS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            )}
            <Field label={mode === "order" ? "Note to the shops" : "Note to the sellers"} hint="optional">
              <textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Delivery day, packaging, anything else" />
            </Field>
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              {mode === "order"
                ? "Each shop confirms its own order and contacts you. You pay the shop directly, the way you chose. Nothing is reserved until a shop completes your order."
                : "Each shop receives only its own items and sends you a priced proforma to accept. Nothing is reserved."}
            </p>
            <div className="row">
              <button type="submit" disabled={busy || lines.length === 0}>
                {busy ? "Sending…" : mode === "order" ? `Place order${groups.length > 1 ? "s" : ""}` : `Send request${groups.length > 1 ? "s" : ""}`}
              </button>
              <Link href="/cart" className="btn secondary">
                Back to cart
              </Link>
            </div>
          </section>
        </form>
      )}
    </StorefrontShell>
  );
}
