"use client";

/**
 * Pieces of the public shop shared by the catalogue, product and basket
 * pages. No sign-in anywhere here (PRD 13).
 */

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Alert, Field } from "@/components/ui";
import { money } from "@/lib/format";
import { defaultVariant, shopApi, type PublicProduct, type Shop } from "@/lib/storefront";

export function StorefrontShell({
  slug,
  shop,
  basketCount,
  basketTotal,
  showBar = true,
  children,
}: {
  slug: string;
  shop: Shop | null;
  basketCount: number;
  basketTotal: number | null;
  showBar?: boolean;
  children: ReactNode;
}) {
  const currency = shop?.currency ?? "ETB";
  return (
    <div className="shell storefront">
      <header className="topbar">
        <div className="store-brand">
          <Link href={`/shop/${slug}`} className="brand">
            {shop?.display_name ?? "Loading…"}
          </Link>
          {shop?.tagline && <div className="who">{shop.tagline}</div>}
        </div>
        <Link href={`/shop/${slug}/basket`} className="basket-button" aria-label={`Basket, ${basketCount} items`}>
          Basket
          {basketCount > 0 && <span className="basket-count">{formatCount(basketCount)}</span>}
        </Link>
      </header>

      <main>{children}</main>

      {showBar && basketCount > 0 && (
        <div className="basket-bar no-print">
          <div>
            <strong>{formatCount(basketCount)} in your basket</strong>
            {basketTotal !== null && (
              <div className="muted" style={{ fontSize: "0.85rem" }}>
                About {money(basketTotal, currency)} before delivery
              </div>
            )}
          </div>
          <Link href={`/shop/${slug}/basket`} className="btn">
            View basket
          </Link>
        </div>
      )}

      <footer className="store-footer no-print">
        {shop && (
          <div>
            {[shop.address, shop.contact_phone, shop.contact_email].filter(Boolean).join(" · ")}
            {shop.telegram_username ? ` · Telegram @${shop.telegram_username}` : ""}
          </div>
        )}
        <div style={{ marginTop: 4 }}>Online shop by Estock</div>
      </footer>
    </div>
  );
}

function formatCount(count: number): string {
  return Number.isInteger(count) ? String(count) : count.toFixed(3).replace(/\.?0+$/, "");
}

export function ProductImage({
  src,
  name,
  className = "thumb",
}: {
  src: string | null;
  name: string;
  className?: string;
}) {
  return (
    <div className={className}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- images come from the API, not the Next image pipeline
        <img src={src} alt={name} loading="lazy" />
      ) : (
        <span className="initial" aria-hidden="true">
          {name.trim().charAt(0).toUpperCase() || "·"}
        </span>
      )}
    </div>
  );
}

export function Stepper({
  value,
  onChange,
  disabled = false,
}: {
  value: number;
  onChange: (next: number) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? formatCount(value);
  return (
    <div className="stepper" role="group" aria-label="Quantity">
      <button type="button" onClick={() => onChange(value - 1)} disabled={disabled} aria-label="Less">
        −
      </button>
      <input
        value={shown}
        inputMode="decimal"
        aria-label="Quantity"
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          const parsed = Number(text);
          if (text !== null && Number.isFinite(parsed)) onChange(parsed);
          setText(null);
        }}
      />
      <button type="button" onClick={() => onChange(value + 1)} disabled={disabled} aria-label="More">
        +
      </button>
    </div>
  );
}

export function ProductCard({
  slug,
  product,
  currency,
  inBasket,
  onAdd,
  onChange,
}: {
  slug: string;
  product: PublicProduct;
  currency: string;
  inBasket: number;
  onAdd: () => void;
  onChange: (quantity: number) => void;
}) {
  const chooseOnPage = product.variants.length > 1;
  return (
    <article className="product-card">
      <Link href={`/shop/${slug}/p/${product.id}`} className="thumb-link">
        <ProductImage src={product.image_url} name={product.name} />
      </Link>
      <div className="body">
        {product.category && <div className="label muted">{product.category}</div>}
        <Link href={`/shop/${slug}/p/${product.id}`} className="name">
          {product.name}
        </Link>
        <div className="price">
          {product.price ? money(product.price, currency) : <span className="muted">Ask for a price</span>}
          <span className="muted unit"> / {product.unit_of_measure}</span>
        </div>
        {!product.in_stock && <span className="badge warn">Out of stock</span>}
        <div className="actions">
          {chooseOnPage ? (
            <Link href={`/shop/${slug}/p/${product.id}`} className="btn secondary">
              Choose an option
            </Link>
          ) : inBasket > 0 ? (
            <Stepper value={inBasket} onChange={onChange} />
          ) : (
            <button type="button" onClick={onAdd} disabled={!defaultVariant(product)}>
              Add to basket
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

export function SellerContact({ shop }: { shop: Shop }) {
  const phone = shop.contact_phone?.replace(/[^\d+]/g, "");
  return (
    <div className="row">
      {phone && (
        <a href={`tel:${phone}`} className="btn secondary">
          Call {shop.contact_phone}
        </a>
      )}
      {shop.telegram_username && (
        <a
          href={`https://t.me/${shop.telegram_username.replace(/^@/, "")}`}
          target="_blank"
          rel="noreferrer"
          className="btn secondary"
        >
          Message on Telegram
        </a>
      )}
      {shop.contact_email && (
        <a href={`mailto:${shop.contact_email}`} className="btn secondary">
          Email
        </a>
      )}
    </div>
  );
}

export function EnquiryForm({
  slug,
  product,
  onDone,
}: {
  slug: string;
  product?: PublicProduct | null;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    contact_name: "",
    contact_phone: "",
    message: "",
  });
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await shopApi.enquire(slug, {
        ...form,
        message: form.message || undefined,
        items: product ? [{ product_id: product.id, name: product.name, quantity: "1" }] : [],
      });
      setSent(result.reference);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send your message");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="card">
        <Alert kind="ok">Thank you — the seller has your question. Your reference is {sent}.</Alert>
        <button type="button" className="secondary" onClick={onDone}>
          Close
        </button>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">{product ? `Ask about ${product.name}` : "Ask the seller a question"}</div>
      <Alert>{error}</Alert>
      <div className="grid">
        <Field label="Your name">
          <input
            value={form.contact_name}
            onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
            required
          />
        </Field>
        <Field label="Phone">
          <input
            value={form.contact_phone}
            onChange={(e) => setForm({ ...form, contact_phone: e.target.value })}
            inputMode="tel"
            required
          />
        </Field>
      </div>
      <Field label="Your question">
        <textarea
          rows={3}
          value={form.message}
          onChange={(e) => setForm({ ...form, message: e.target.value })}
          placeholder={product ? "e.g. Do you have this in a larger size?" : "What would you like to know?"}
          required
        />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy}>
          {busy ? "Sending…" : "Send"}
        </button>
        <button type="button" className="secondary" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
