"use client";

/**
 * The cross-shop basket and checkout.
 *
 * Grouped by shop, because that is what happens when it is sent: each shop
 * receives only its own lines and prices them independently. Showing the
 * grouping here means the buyer is never surprised by getting several
 * separate quotations back.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { MarketShell } from "@/components/Market";
import { ProductImage, Stepper } from "@/components/Storefront";
import { Alert, Empty, Field } from "@/components/ui";
import { money } from "@/lib/format";
import { describeError } from "@/lib/session";
import { marketApi, useMarketBasket, useMyMarketRequests } from "@/lib/market";

export default function MarketBasketPage() {
  const basket = useMarketBasket();
  const { remember } = useMyMarketRequests();
  const router = useRouter();

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [delivery, setDelivery] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await marketApi.submitRequest({
        items: basket.lines.map((line) => ({
          variant_id: line.variantId,
          quantity: String(line.quantity),
        })),
        contact_name: name,
        contact_phone: phone,
        contact_email: email || undefined,
        company: company || undefined,
        delivery_location: delivery || undefined,
        message: message || undefined,
      });
      remember({
        reference: result.reference,
        token: result.token,
        shopCount: result.shop_count,
      });
      basket.clear();
      router.push(`/market/requests/${result.token}`);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  }

  if (!basket.loaded) {
    return (
      <MarketShell basketCount={0} shopCount={0} basketTotal={null} showBar={false}>
        <p className="muted">Loading your basket…</p>
      </MarketShell>
    );
  }

  if (basket.lines.length === 0) {
    return (
      <MarketShell basketCount={0} shopCount={0} basketTotal={null} showBar={false}>
        <Empty title="Your basket is empty">
          <p className="muted">
            <Link href="/market">Browse the marketplace</Link> and add what you need
            — from as many shops as you like.
          </p>
        </Empty>
      </MarketShell>
    );
  }

  return (
    <MarketShell
      basketCount={basket.count}
      shopCount={basket.shopCount}
      basketTotal={basket.total}
      showBar={false}
    >
      <h1>Your basket</h1>
      <p className="muted">
        {basket.count} item{basket.count === 1 ? "" : "s"} from {basket.shopCount} shop
        {basket.shopCount === 1 ? "" : "s"}. Each shop below will price its own
        part and reply separately.
      </p>

      {basket.groups.map((group) => (
        <section key={group.slug} className="basket-group">
          <header>
            <h2>{group.name}</h2>
            <span className="muted small">
              {group.lines.length} item{group.lines.length === 1 ? "" : "s"}
              {group.total !== null ? ` · ${money(group.total)}` : " · prices on request"}
            </span>
          </header>
          <ul className="basket-lines">
            {group.lines.map((line) => (
              <li key={line.variantId} className="line">
                <ProductImage src={line.imageUrl} name={line.name} className="thumb small" />
                <div className="line-body">
                  <Link href={`/market/p/${line.productId}`} className="name">
                    {line.name}
                  </Link>
                  {line.variantName ? (
                    <span className="muted small"> · {line.variantName}</span>
                  ) : null}
                  <p className="muted small">
                    {line.price ? `${money(line.price)} / ${line.unit}` : "Price on request"}
                  </p>
                  {/* Under the line rather than beside it: on a phone there is
                      no room for a picture, a name, a stepper and a button
                      across one row, and the name is what gets squeezed. */}
                  <div className="row" style={{ marginTop: 6 }}>
                    <Stepper
                      value={line.quantity}
                      onChange={(next) => basket.setQuantity(line.variantId, next)}
                    />
                    <button
                      type="button"
                      className="link"
                      onClick={() => basket.remove(line.variantId)}
                      aria-label={`Remove ${line.name}`}
                    >
                      Remove
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}

      {basket.total !== null ? (
        <p className="basket-total">
          Indicative total <strong>{money(basket.total)}</strong>
          <span className="muted small">
            {" "}
            — each shop confirms its own prices, which may differ.
          </span>
        </p>
      ) : (
        <p className="muted">
          Some shops do not show prices online. They will quote when they reply.
        </p>
      )}

      <form className="checkout" onSubmit={submit}>
        <h2>Where should the shops reply?</h2>
        <p className="muted small">
          Your details go to each shop in this basket, so they can quote and
          reach you. Nothing is ordered and nothing is reserved.
        </p>

        <Field label="Your name">
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label="Phone" hint="The shops will call or message you on this.">
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            inputMode="tel"
            required
          />
        </Field>
        <Field label="Email" hint="Optional.">
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" />
        </Field>
        <Field label="Company" hint="Optional.">
          <input value={company} onChange={(e) => setCompany(e.target.value)} />
        </Field>
        <Field label="Where to deliver" hint="Optional, but it helps them quote.">
          <input value={delivery} onChange={(e) => setDelivery(e.target.value)} />
        </Field>
        <Field label="Anything else they should know">
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3} />
        </Field>

        {error ? <Alert>{error}</Alert> : null}

        <div className="row">
          <button type="submit" disabled={busy}>
            {busy
              ? "Sending…"
              : `Ask ${basket.shopCount} shop${basket.shopCount === 1 ? "" : "s"} for prices`}
          </button>
          <Link href="/market" className="btn secondary">
            Add more products
          </Link>
        </div>
        <p className="disclaimer">
          You will get one link that tracks every shop&apos;s reply. You can
          accept one shop&apos;s quotation and leave another&apos;s.
        </p>
      </form>
    </MarketShell>
  );
}
