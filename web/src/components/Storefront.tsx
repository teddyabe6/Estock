"use client";

/**
 * Pieces of the public side shared by the marketplace, shop, product, cart
 * and checkout pages. No sign-in anywhere here (PRD 13).
 */

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Alert, Field } from "@/components/ui";
import { money } from "@/lib/format";
import { cartLineFor, defaultVariant, shopApi, useCart, type PublicProduct, type Shop } from "@/lib/storefront";

export function StorefrontShell({
  title,
  subtitle,
  homeHref = "/market",
  contact,
  showBar = true,
  children,
}: {
  title: string;
  subtitle?: string | null;
  homeHref?: string;
  contact?: Shop | null;
  showBar?: boolean;
  children: ReactNode;
}) {
  const cart = useCart();
  const currency = contact?.currency ?? "ETB";
  return (
    <div className="shell storefront">
      <header className="topbar">
        <div className="store-brand">
          <Link href={homeHref} className="brand">
            {title}
          </Link>
          {subtitle && <div className="who">{subtitle}</div>}
        </div>
        <nav className="row" style={{ gap: 10 }}>
          {homeHref !== "/market" && (
            <Link href="/market" className="muted" style={{ fontSize: "0.9rem" }}>
              All shops
            </Link>
          )}
          <Link href="/cart" className="basket-button" aria-label={`Cart, ${formatCount(cart.count)} items`}>
            Cart
            {cart.count > 0 && <span className="basket-count">{formatCount(cart.count)}</span>}
          </Link>
        </nav>
      </header>

      <main>{children}</main>

      {showBar && cart.count > 0 && (
        <div className="basket-bar no-print">
          <div>
            <strong>{formatCount(cart.count)} in your cart</strong>
            <div className="muted" style={{ fontSize: "0.85rem" }}>
              {cart.groups.length} shop{cart.groups.length === 1 ? "" : "s"}
              {cart.total !== null ? ` · about ${money(cart.total, currency)} before delivery` : ""}
            </div>
          </div>
          <Link href="/cart" className="btn">
            View cart
          </Link>
        </div>
      )}

      <footer className="store-footer no-print">
        {contact && (
          <div>
            {[contact.address, contact.contact_phone, contact.contact_email].filter(Boolean).join(" · ")}
            {contact.telegram_username ? ` · Telegram @${contact.telegram_username}` : ""}
          </div>
        )}
        <div style={{ marginTop: 4 }}>
          <Link href="/market">Marketplace</Link> · Online shops by Estock
        </div>
      </footer>
    </div>
  );
}

export function formatCount(count: number): string {
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
  product,
  currency,
  showShop = false,
}: {
  product: PublicProduct;
  currency: string;
  showShop?: boolean;
}) {
  const cart = useCart();
  const variant = defaultVariant(product);
  const inCart = variant ? cart.quantityOf(variant.id) : 0;
  const chooseOnPage = product.variants.length > 1;
  const href = `/shop/${product.shop.slug}/p/${product.id}`;
  return (
    <article className="product-card">
      <Link href={href} className="thumb-link">
        <ProductImage src={product.image_url} name={product.name} />
      </Link>
      <div className="body">
        <div className="label muted">
          {showShop ? (
            <Link href={`/shop/${product.shop.slug}`}>{product.shop.display_name}</Link>
          ) : (
            product.category ?? "Product"
          )}
        </div>
        <Link href={href} className="name">
          {product.name}
        </Link>
        <div className="price">
          {product.price ? money(product.price, currency) : <span className="muted">Ask for a price</span>}
          <span className="muted unit"> / {product.unit_of_measure}</span>
        </div>
        {!product.in_stock && <span className="badge warn">Out of stock</span>}
        <div className="actions">
          {chooseOnPage ? (
            <Link href={href} className="btn secondary">
              Choose an option
            </Link>
          ) : inCart > 0 ? (
            <Stepper value={inCart} onChange={(q) => variant && cart.setQuantity(variant.id, q)} />
          ) : (
            <button
              type="button"
              onClick={() => variant && cart.add(cartLineFor(product, variant))}
              disabled={!variant}
            >
              {product.shop.accepts_orders && product.price ? "Add to cart" : "Add to request"}
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

/** Contact details asked at both checkouts, remembered in the browser. */
export function ContactFields({
  form,
  onChange,
  phoneHint,
}: {
  form: { contact_name: string; contact_phone: string; contact_email: string; company: string; delivery_location: string };
  onChange: (next: typeof form) => void;
  phoneHint: string;
}) {
  return (
    <div className="grid">
      <Field label="Your name">
        <input
          value={form.contact_name}
          onChange={(e) => onChange({ ...form, contact_name: e.target.value })}
          required
          autoComplete="name"
        />
      </Field>
      <Field label="Phone" hint={phoneHint}>
        <input
          value={form.contact_phone}
          onChange={(e) => onChange({ ...form, contact_phone: e.target.value })}
          inputMode="tel"
          autoComplete="tel"
          required
        />
      </Field>
      <Field label="Email" hint="optional, for updates">
        <input
          type="email"
          value={form.contact_email}
          onChange={(e) => onChange({ ...form, contact_email: e.target.value })}
          autoComplete="email"
        />
      </Field>
      <Field label="Company" hint="optional">
        <input value={form.company} onChange={(e) => onChange({ ...form, company: e.target.value })} />
      </Field>
      <Field label="Delivery location" hint="optional">
        <input
          value={form.delivery_location}
          onChange={(e) => onChange({ ...form, delivery_location: e.target.value })}
          placeholder="e.g. Bole, near Edna Mall"
        />
      </Field>
    </div>
  );
}
