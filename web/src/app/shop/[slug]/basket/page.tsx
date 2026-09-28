"use client";

/**
 * The basket and the checkout: the visitor's items become a numbered proforma
 * request the seller reviews. No payment online and no stock reserved (PRD 13).
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { ProductImage, Stepper, StorefrontShell } from "@/components/Storefront";
import { Alert, Empty, Field } from "@/components/ui";
import { money } from "@/lib/format";
import { shopApi, useBasket, useMyRequests, type Shop } from "@/lib/storefront";

export default function BasketPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const router = useRouter();
  const [shop, setShop] = useState<Shop | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    contact_name: "",
    contact_phone: "",
    contact_email: "",
    company: "",
    delivery_location: "",
    message: "",
  });
  const basket = useBasket(slug);
  const requests = useMyRequests(slug);
  const currency = shop?.currency ?? "ETB";

  useEffect(() => {
    shopApi
      .shop(slug)
      .then(setShop)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Shop not found"));
    try {
      const saved = window.localStorage.getItem("estock.visitor");
      if (saved) setForm((prev) => ({ ...prev, ...(JSON.parse(saved) as Partial<typeof form>) }));
    } catch {
      // No remembered details; the form starts empty.
    }
  }, [slug]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await shopApi.requestProforma(slug, {
        items: basket.lines.map((line) => ({ variant_id: line.variantId, quantity: String(line.quantity) })),
        contact_name: form.contact_name,
        contact_phone: form.contact_phone,
        contact_email: form.contact_email || undefined,
        company: form.company || undefined,
        delivery_location: form.delivery_location || undefined,
        message: form.message || undefined,
      });
      try {
        const { contact_name, contact_phone, contact_email, company, delivery_location } = form;
        window.localStorage.setItem(
          "estock.visitor",
          JSON.stringify({ contact_name, contact_phone, contact_email, company, delivery_location }),
        );
      } catch {
        // Remembering the details is a convenience only.
      }
      requests.remember({ number: result.number, token: result.token });
      basket.clear();
      router.push(`/q/${result.token}?requested=1`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send your request");
      setBusy(false);
    }
  }

  return (
    <StorefrontShell slug={slug} shop={shop} basketCount={basket.count} basketTotal={basket.total} showBar={false}>
      <h1 style={{ marginTop: 0 }}>Your basket</h1>
      <Alert>{error}</Alert>

      {basket.loaded && basket.lines.length === 0 ? (
        <Empty title="Your basket is empty">
          <p>
            <Link href={`/shop/${slug}`}>Browse the products</Link> and add what you need.
          </p>
        </Empty>
      ) : (
        <>
          <div className="card basket-lines">
            {basket.lines.map((line) => (
              <div key={line.variantId} className="line">
                <ProductImage src={line.imageUrl} name={line.name} className="thumb small" />
                <div>
                  <Link href={`/shop/${slug}/p/${line.productId}`} className="name">
                    {line.name}
                    {line.variantName ? ` — ${line.variantName}` : ""}
                  </Link>
                  <div className="muted" style={{ fontSize: "0.85rem" }}>
                    {line.price ? `${money(line.price, currency)} / ${line.unit}` : "Price on request"}
                  </div>
                  <div className="row" style={{ marginTop: 6 }}>
                    <Stepper value={line.quantity} onChange={(q) => basket.setQuantity(line.variantId, q)} />
                    <button type="button" className="link" onClick={() => basket.remove(line.variantId)}>
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
              <span className="muted">Estimated total, before delivery</span>
              <strong>{basket.total !== null ? money(basket.total, currency) : "On request"}</strong>
            </div>
            <p className="muted" style={{ fontSize: "0.85rem", margin: "8px 0 0" }}>
              The seller confirms prices, tax and delivery on the proforma. Nothing is paid or reserved yet.
            </p>
          </div>

          <form className="card" onSubmit={submit}>
            <div className="card-title">Request a proforma</div>
            {shop?.checkout_note && <Alert kind="ok">{shop.checkout_note}</Alert>}
            <div className="grid">
              <Field label="Your name">
                <input
                  value={form.contact_name}
                  onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
                  required
                  autoComplete="name"
                />
              </Field>
              <Field label="Phone" hint="the seller confirms by phone">
                <input
                  value={form.contact_phone}
                  onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
                  inputMode="tel"
                  autoComplete="tel"
                  required
                />
              </Field>
              <Field label="Email" hint="optional, to receive the proforma">
                <input
                  type="email"
                  value={form.contact_email}
                  onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                  autoComplete="email"
                />
              </Field>
              <Field label="Company" hint="optional">
                <input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              </Field>
              <Field label="Delivery location" hint="optional">
                <input
                  value={form.delivery_location}
                  onChange={(e) => setForm({ ...form, delivery_location: e.target.value })}
                  placeholder="e.g. Bole, near Edna Mall"
                />
              </Field>
            </div>
            <Field label="Note to the seller" hint="optional">
              <textarea
                rows={2}
                value={form.message}
                onChange={(e) => setForm({ ...form, message: e.target.value })}
                placeholder="Delivery day, packaging, anything else"
              />
            </Field>
            <div className="row">
              <button type="submit" disabled={busy || basket.lines.length === 0}>
                {busy ? "Sending…" : "Request proforma"}
              </button>
              <Link href={`/shop/${slug}`} className="btn secondary">
                Keep shopping
              </Link>
            </div>
          </form>
        </>
      )}
    </StorefrontShell>
  );
}
