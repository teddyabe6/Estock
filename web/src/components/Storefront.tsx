"use client";

/**
 * Pieces of the public shop shared by the catalogue, product and basket
 * pages. No sign-in anywhere here (PRD 13).
 */

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { Alert, Field } from "@/components/ui";
import { money } from "@/lib/format";
import {
  SLIP_METHODS,
  defaultVariant,
  shopApi,
  slipMethodLabel,
  type ProductSort,
  type PublicProduct,
  type Shop,
} from "@/lib/storefront";

/**
 * The frame around every public page — one shop's storefront and the central
 * marketplace alike.
 *
 * To a buyer the two are the same thing: a name that takes them back to the
 * start, a basket they can check from anywhere, and a page that has to work
 * in one hand. Holding both to one shell is what stops the marketplace
 * drifting into a header of its own again, which is how it ended up with one
 * the stylesheet had never heard of.
 */
export function PublicShell({
  brandHref,
  brandName,
  tagline,
  basketHref,
  basketCount,
  bar,
  footer,
  children,
}: {
  brandHref: string;
  brandName: ReactNode;
  tagline?: ReactNode;
  basketHref: string;
  basketCount: number;
  bar?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="shell storefront">
      <header className="topbar">
        <div className="store-brand">
          <Link href={brandHref} className="brand">
            {brandName}
          </Link>
          {tagline && <div className="who">{tagline}</div>}
        </div>
        <Link
          href={basketHref}
          className="basket-button"
          aria-label={`Basket, ${formatCount(basketCount)} items`}
        >
          Basket
          {basketCount > 0 && <span className="basket-count">{formatCount(basketCount)}</span>}
        </Link>
      </header>

      <main>{children}</main>

      {bar}

      <footer className="store-footer no-print">{footer}</footer>
    </div>
  );
}

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
    <PublicShell
      brandHref={`/shop/${slug}`}
      brandName={shop?.display_name ?? "Loading…"}
      tagline={shop?.tagline}
      basketHref={`/shop/${slug}/basket`}
      basketCount={basketCount}
      bar={
        showBar &&
        basketCount > 0 && (
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
        )
      }
      footer={
        <>
          {shop && (
            <div>
              {[shop.address, shop.contact_phone, shop.contact_email].filter(Boolean).join(" · ")}
              {shop.telegram_username ? ` · Telegram @${shop.telegram_username}` : ""}
            </div>
          )}
          <div style={{ marginTop: 4 }}>Online shop by Estock</div>
        </>
      }
    >
      {children}
    </PublicShell>
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

/**
 * The filter rail beside a shop's catalogue.
 *
 * On a phone there is no room for a rail, so it collapses behind a Filters
 * button and opens in place — the same controls, not a cut-down set, because
 * a shopper on a phone is the one most likely to want to narrow a long list.
 *
 * The price filter only appears when the shop shows prices and something
 * carries one. Offering a price range to a shop that quotes on request would
 * be a control that cannot do anything.
 */
export function ShopFilters({
  categories,
  category,
  onCategory,
  range,
  minPrice,
  maxPrice,
  onPrice,
  sort,
  onSort,
  currency,
  resultCount,
  open,
  onToggle,
}: {
  categories: string[];
  category: string;
  onCategory: (name: string) => void;
  range: [string | null, string | null];
  minPrice: string;
  maxPrice: string;
  onPrice: (min: string, max: string) => void;
  sort: ProductSort;
  onSort: (value: ProductSort) => void;
  currency: string;
  resultCount: number | null;
  open: boolean;
  onToggle: () => void;
}) {
  const [low, high] = range;
  const canFilterByPrice = low !== null && high !== null;
  const [draftMin, setDraftMin] = useState(minPrice);
  const [draftMax, setDraftMax] = useState(maxPrice);

  // Keep the inputs in step when the filters are cleared from outside.
  useEffect(() => {
    setDraftMin(minPrice);
    setDraftMax(maxPrice);
  }, [minPrice, maxPrice]);

  const active =
    (category ? 1 : 0) + (minPrice ? 1 : 0) + (maxPrice ? 1 : 0) + (sort !== "name" ? 1 : 0);

  return (
    <>
      <button
        type="button"
        className="filters-toggle secondary"
        onClick={onToggle}
        aria-expanded={open}
      >
        {open ? "Hide filters" : "Filters"}
        {active > 0 && <span className="basket-count">{active}</span>}
      </button>

      <aside className={open ? "shop-filters is-open" : "shop-filters"} aria-label="Filters">
        <div className="filter-group">
          <h2>Sort by</h2>
          <select value={sort} onChange={(e) => onSort(e.target.value as ProductSort)}>
            <option value="name">Name</option>
            <option value="price_low">Price, low to high</option>
            <option value="price_high">Price, high to low</option>
          </select>
        </div>

        {categories.length > 0 && (
          <div className="filter-group">
            <h2>Category</h2>
            <ul className="filter-list">
              <li>
                <button
                  type="button"
                  className={category ? "" : "is-active"}
                  onClick={() => onCategory("")}
                >
                  All products
                </button>
              </li>
              {categories.map((name) => (
                <li key={name}>
                  <button
                    type="button"
                    className={category.toLowerCase() === name.toLowerCase() ? "is-active" : ""}
                    onClick={() => onCategory(name)}
                  >
                    {name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {canFilterByPrice && (
          <form
            className="filter-group"
            onSubmit={(event) => {
              event.preventDefault();
              onPrice(draftMin.trim(), draftMax.trim());
            }}
          >
            <h2>Price</h2>
            <p className="muted" style={{ margin: "0 0 8px", fontSize: "0.82rem" }}>
              This shop sells from {money(low, currency)} to {money(high, currency)}.
            </p>
            <div className="price-inputs">
              <label>
                <span>From</span>
                <input
                  value={draftMin}
                  onChange={(e) => setDraftMin(e.target.value)}
                  inputMode="decimal"
                  placeholder={low ?? ""}
                  aria-label={`Lowest price in ${currency}`}
                />
              </label>
              <label>
                <span>To</span>
                <input
                  value={draftMax}
                  onChange={(e) => setDraftMax(e.target.value)}
                  inputMode="decimal"
                  placeholder={high ?? ""}
                  aria-label={`Highest price in ${currency}`}
                />
              </label>
            </div>
            <button type="submit" className="secondary">
              Apply
            </button>
          </form>
        )}

        {active > 0 && (
          <button
            type="button"
            className="link"
            onClick={() => {
              onCategory("");
              onPrice("", "");
              onSort("name");
            }}
          >
            Clear filters
          </button>
        )}

        {resultCount !== null && (
          <p className="muted result-count">
            {resultCount} product{resultCount === 1 ? "" : "s"}
          </p>
        )}
      </aside>
    </>
  );
}

/**
 * "I have paid" — the checkout, in a country with no card rails worth using.
 *
 * The buyer transfers by telebirr, CBE Birr or at a bank, then sends the
 * seller the screenshot. That is how this trade already works, so the form
 * asks for exactly what a seller needs to find the money in their own
 * account: how much, how, the transaction number, and the picture.
 *
 * It claims nothing on the buyer's behalf. The seller checks and confirms,
 * and until they do the screen says so rather than implying the order is
 * settled.
 */
export function PaymentSlipForm({
  token,
  total,
  currency,
  shopName,
  onSent,
}: {
  token: string;
  total: string | null;
  currency: string;
  shopName: string | null;
  onSent: (message: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [amount, setAmount] = useState(total ?? "");
  const [method, setMethod] = useState<string>("telebirr");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10));
  const [senderName, setSenderName] = useState("");
  const [senderPhone, setSenderPhone] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Attach a photo of the slip, or the PDF from your bank.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      if (amount.trim()) form.append("amount", amount.trim());
      form.append("method", method);
      if (reference.trim()) form.append("reference", reference.trim());
      if (paidOn) form.append("paid_on", paidOn);
      if (note.trim()) form.append("note", note.trim());
      if (senderName.trim()) form.append("sender_name", senderName.trim());
      if (senderPhone.trim()) form.append("sender_phone", senderPhone.trim());
      const result = await shopApi.sendPaymentSlip(token, form);
      onSent(result.message);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send your slip");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card slip-form" onSubmit={submit}>
      <div className="card-title">I have paid</div>
      <p className="muted" style={{ marginTop: 0 }}>
        There is no card payment here. Transfer the amount to {shopName ?? "the seller"}{" "}
        by telebirr, CBE Birr or at a bank, then send the slip so they can check it
        against their account.
      </p>

      <Alert>{error}</Alert>

      <div className="grid">
        <Field label="How much you sent" hint={total ? `the proforma is ${money(total, currency)}` : undefined}>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
        </Field>
        <Field label="How you sent it">
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            {SLIP_METHODS.map((value) => (
              <option key={value} value={value}>
                {slipMethodLabel(value)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Transaction number" hint="from the SMS or the slip">
          <input value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
        <Field label="Date you paid">
          <input type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </Field>
        <Field label="Your name">
          <input value={senderName} onChange={(e) => setSenderName(e.target.value)} />
        </Field>
        <Field label="Your phone">
          <input
            value={senderPhone}
            onChange={(e) => setSenderPhone(e.target.value)}
            inputMode="tel"
          />
        </Field>
      </div>

      <Field label="The slip" hint="a photo or a PDF, up to 10MB">
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          required
        />
      </Field>
      {file && (
        <p className="muted" style={{ marginTop: -6, fontSize: "0.85rem" }}>
          {file.name} · {Math.round(file.size / 1024)} KB
        </p>
      )}

      <Field label="Anything else they should know" hint="optional">
        <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>

      <button type="submit" disabled={busy}>
        {busy ? "Sending…" : "Send the slip"}
      </button>
      <p className="disclaimer">
        Sending a slip is not the same as the seller confirming it. Keep your own copy
        until they do.
      </p>
    </form>
  );
}
