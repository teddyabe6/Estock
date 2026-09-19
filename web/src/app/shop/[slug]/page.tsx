"use client";

/**
 * Public storefront. No sign-in, and no stock is reserved by browsing or
 * enquiring (PRD 13).
 */

import { use, useEffect, useState } from "react";

import { Alert, Empty, Field } from "@/components/ui";
import { request } from "@/lib/api";
import { money } from "@/lib/format";

type Shop = {
  slug: string;
  display_name: string;
  tagline: string | null;
  about: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  telegram_username: string | null;
  address: string | null;
  currency: string;
  show_prices: boolean;
};

type PublicProduct = {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  unit_of_measure: string;
  price: string | null;
  in_stock: boolean;
};

export default function ShopPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const [shop, setShop] = useState<Shop | null>(null);
  const [products, setProducts] = useState<PublicProduct[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [enquiring, setEnquiring] = useState(false);

  useEffect(() => {
    request<Shop>(`/public/shops/${slug}`, { anonymous: true })
      .then(setShop)
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "Shop not found"),
      );
  }, [slug]);

  useEffect(() => {
    const timer = setTimeout(() => {
      request<{ items: PublicProduct[] }>(
        `/public/shops/${slug}/products?limit=60${search ? `&q=${encodeURIComponent(search)}` : ""}`,
        { anonymous: true },
      )
        .then((page) => setProducts(page.items))
        .catch(() => setProducts([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [slug, search]);

  if (error) {
    return (
      <main style={{ maxWidth: 720, margin: "10vh auto", padding: "0 16px" }}>
        <Alert>{error}</Alert>
      </main>
    );
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <div className="brand">{shop?.display_name ?? "Loading…"}</div>
          {shop?.tagline && <div className="who">{shop.tagline}</div>}
        </div>
        <button type="button" onClick={() => setEnquiring((value) => !value)}>
          {enquiring ? "Close" : "Ask about an item"}
        </button>
      </header>

      <main>
        {shop && (
          <div className="card">
            {shop.about && <p style={{ marginTop: 0 }}>{shop.about}</p>}
            <p className="muted" style={{ margin: 0, fontSize: "0.9rem" }}>
              {[shop.address, shop.contact_phone, shop.contact_email]
                .filter(Boolean)
                .join(" · ")}
              {shop.telegram_username ? ` · @${shop.telegram_username}` : ""}
            </p>
          </div>
        )}

        {enquiring && shop && (
          <EnquiryForm slug={slug} onDone={() => setEnquiring(false)} />
        )}

        <div className="card">
          <Field label="Search products">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="What are you looking for?"
            />
          </Field>

          {products.length === 0 ? (
            <Empty title="Nothing to show">
              <p>This shop has not published any products yet.</p>
            </Empty>
          ) : (
            <div className="grid">
              {products.map((product) => (
                <article key={product.id} className="stat">
                  <div className="label">{product.category ?? "Product"}</div>
                  <div style={{ fontWeight: 600, margin: "4px 0" }}>{product.name}</div>
                  {product.description && (
                    <p className="muted" style={{ fontSize: "0.85rem", margin: "0 0 6px" }}>
                      {product.description}
                    </p>
                  )}
                  <div className="value" style={{ fontSize: "1.1rem" }}>
                    {product.price
                      ? money(product.price, shop?.currency ?? "ETB")
                      : "Ask for a price"}
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <span className={`badge ${product.in_stock ? "ok" : "warn"}`}>
                      {product.in_stock ? "In stock" : "Out of stock"}
                    </span>
                    <span className="muted" style={{ marginLeft: 8, fontSize: "0.82rem" }}>
                      per {product.unit_of_measure}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function EnquiryForm({ slug, onDone }: { slug: string; onDone: () => void }) {
  const [form, setForm] = useState({
    contact_name: "",
    contact_phone: "",
    company: "",
    delivery_location: "",
    message: "",
    wants_proforma: false,
  });
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await request<{ reference: string }>(
        `/public/shops/${slug}/enquiries`,
        {
          method: "POST",
          anonymous: true,
          body: {
            ...form,
            company: form.company || undefined,
            delivery_location: form.delivery_location || undefined,
            message: form.message || undefined,
          },
        },
      );
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
        <Alert kind="ok">
          Thank you — the seller has your message. Your reference is {sent}.
        </Alert>
        <button type="button" className="secondary" onClick={onDone}>
          Close
        </button>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-title">Send an enquiry</div>
      <Alert>{error}</Alert>
      <form onSubmit={submit}>
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
          <Field label="Company" hint="optional">
            <input
              value={form.company}
              onChange={(e) => setForm({ ...form, company: e.target.value })}
            />
          </Field>
          <Field label="Delivery location" hint="optional">
            <input
              value={form.delivery_location}
              onChange={(e) => setForm({ ...form, delivery_location: e.target.value })}
            />
          </Field>
        </div>
        <Field label="What do you need?">
          <textarea
            rows={3}
            value={form.message}
            onChange={(e) => setForm({ ...form, message: e.target.value })}
          />
        </Field>
        <label className="row" style={{ marginBottom: 12 }}>
          <input
            type="checkbox"
            checked={form.wants_proforma}
            onChange={(e) => setForm({ ...form, wants_proforma: e.target.checked })}
            style={{ width: "auto" }}
          />
          <span>Please send me a proforma invoice</span>
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Sending…" : "Send enquiry"}
        </button>
      </form>
    </div>
  );
}
