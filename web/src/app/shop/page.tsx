"use client";

/**
 * The online shop from the seller's side: storefront settings, enquiries from
 * customers, and proformas (PRD 13, 14). Same catalogue and stock as the
 * counter; an enquiry or proforma never touches stock.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Drawer, Empty, Field, PageHead, Tabs, Toggle } from "@/components/ui";
import { api, type Enquiry, type Product, type Quotation, type Store } from "@/lib/api";
import { dateTime, money, shortDate } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

type Tab = "storefront" | "enquiries" | "proformas";

export default function ShopPage() {
  return (
    <AppShell>
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <Shop />
      </Suspense>
    </AppShell>
  );
}

function Shop() {
  const { can } = useSession();
  const params = useSearchParams();
  const initial = params.get("tab");
  const [tab, setTab] = useState<Tab>(
    initial === "enquiries" || initial === "proformas" ? initial : "storefront",
  );
  const tabs = [
    { value: "storefront" as const, label: "Storefront", show: true },
    { value: "enquiries" as const, label: "Enquiries", show: can("enquiry:view") },
    { value: "proformas" as const, label: "Proformas", show: can("quotation:view") },
  ].filter((t) => t.show);

  return (
    <>
      <PageHead title="Online shop" subtitle="The same products and stock as the counter" />
      <Tabs value={tab} options={tabs} onChange={setTab} />
      {tab === "storefront" && <Storefront />}
      {tab === "enquiries" && <Enquiries openId={params.get("open")} onQuote={() => setTab("proformas")} />}
      {tab === "proformas" && <Proformas />}
    </>
  );
}

// --------------------------------------------------------------------------- //
// Storefront settings and publishing
// --------------------------------------------------------------------------- //

function Storefront() {
  const { session, can, canWrite } = useSession();
  const currency = session?.currency ?? "ETB";
  const [store, setStore] = useState<Store | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, page] = await Promise.all([api.store(), api.products({ limit: 200 })]);
      setStore(s);
      setProducts(page.items);
      setForm({
        display_name: s.display_name,
        tagline: s.tagline ?? "",
        about: s.about ?? "",
        contact_phone: s.contact_phone ?? "",
        contact_email: s.contact_email ?? "",
        telegram_username: s.telegram_username ?? "",
        address: s.address ?? "",
      });
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load the shop"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setSaved(false);
    try {
      setStore(
        await api.updateStore({
          ...form,
          tagline: form.tagline || null,
          about: form.about || null,
          contact_phone: form.contact_phone || null,
          contact_email: form.contact_email || null,
          telegram_username: form.telegram_username || null,
          address: form.address || null,
        }),
      );
      setSaved(true);
    } catch (cause) {
      setError(describeError(cause, "Could not save"));
    } finally {
      setBusy(false);
    }
  }

  async function setFlag(key: "is_published" | "show_prices", value: boolean) {
    try {
      setStore(await api.updateStore({ [key]: value }));
    } catch (cause) {
      setError(describeError(cause, "Could not save"));
    }
  }

  async function togglePublish(product: Product) {
    try {
      const updated = await api.publishProduct(product.id, !product.is_published);
      setProducts((all) => all.map((p) => (p.id === product.id ? updated : p)));
    } catch (cause) {
      setError(describeError(cause, "Could not change availability"));
    }
  }

  const manage = canWrite && can("shop:manage");
  const published = products.filter((p) => p.is_published);

  return (
    <>
      <Alert>{error}</Alert>
      {store && (
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <div className="card-title" style={{ marginBottom: 2 }}>
                {store.is_published ? "Your shop is live" : "Your shop is not published yet"}
              </div>
              {store.public_url && (
                <a href={store.public_url} target="_blank" rel="noreferrer">
                  {store.public_url}
                </a>
              )}
            </div>
            {manage && (
              <button type="button" className={store.is_published ? "secondary" : undefined} onClick={() => void setFlag("is_published", !store.is_published)}>
                {store.is_published ? "Take the shop offline" : "Publish the shop"}
              </button>
            )}
          </div>
          {manage && (
            <Toggle
              label="Show prices to visitors"
              hint="off means visitors ask for a price"
              checked={store.show_prices}
              onChange={(v) => void setFlag("show_prices", v)}
            />
          )}
        </div>
      )}

      {store && manage && (
        <form className="card" onSubmit={save}>
          <div className="card-title">Shop details</div>
          {saved && <Alert kind="ok">Saved.</Alert>}
          <div className="grid">
            <Field label="Shop name">
              <input value={form.display_name ?? ""} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required />
            </Field>
            <Field label="Tagline" hint="optional">
              <input value={form.tagline ?? ""} onChange={(e) => setForm({ ...form, tagline: e.target.value })} />
            </Field>
            <Field label="Phone">
              <input value={form.contact_phone ?? ""} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} inputMode="tel" />
            </Field>
            <Field label="Email" hint="optional">
              <input type="email" value={form.contact_email ?? ""} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
            </Field>
            <Field label="Telegram username" hint="optional, without @">
              <input value={form.telegram_username ?? ""} onChange={(e) => setForm({ ...form, telegram_username: e.target.value })} />
            </Field>
            <Field label="Address" hint="optional">
              <input value={form.address ?? ""} onChange={(e) => setForm({ ...form, address: e.target.value })} />
            </Field>
          </div>
          <Field label="About" hint="optional">
            <textarea rows={3} value={form.about ?? ""} onChange={(e) => setForm({ ...form, about: e.target.value })} />
          </Field>
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save shop details"}
          </button>
        </form>
      )}

      <div className="card">
        <div className="card-title">
          Published products ({published.length} of {products.length})
        </div>
        <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
          Availability online comes from the same stock ledger as the counter. Publishing is a simple
          toggle per product.
        </p>
        {products.length === 0 ? (
          <Empty title="No products yet">
            <p>
              <Link href="/products">Add products</Link> first, then publish the ones to show online.
            </p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Price</th>
                  <th>Online</th>
                  {manage && <th />}
                </tr>
              </thead>
              <tbody>
                {products.map((product) => (
                  <tr key={product.id}>
                    <td>
                      {product.name}
                      {product.track_stock && Number(product.quantity_on_hand ?? 0) <= 0 && (
                        <>
                          {" "}
                          <span className="badge warn">out of stock</span>
                        </>
                      )}
                    </td>
                    <td className="num">{money(product.variants[0]?.selling_price, currency)}</td>
                    <td>
                      <Badge status={product.is_published ? "ok" : "muted"} label={product.is_published ? "published" : "hidden"} />
                    </td>
                    {manage && (
                      <td className="num">
                        <button type="button" className="link" onClick={() => void togglePublish(product)}>
                          {product.is_published ? "Hide" : "Publish"}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Enquiries
// --------------------------------------------------------------------------- //

function Enquiries({ openId, onQuote }: { openId: string | null; onQuote: () => void }) {
  const { can, canWrite } = useSession();
  const [items, setItems] = useState<Enquiry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(openId);

  const load = useCallback(async () => {
    try {
      setItems((await api.enquiries({ limit: 100 })).items);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load enquiries"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function setStatus(enquiry: Enquiry, status: string) {
    try {
      const updated = await api.updateEnquiry(enquiry.id, status);
      setItems((all) => all.map((e) => (e.id === enquiry.id ? updated : e)));
    } catch (cause) {
      setError(describeError(cause, "Could not update the enquiry"));
    }
  }

  const open = items.find((e) => e.id === selected) ?? null;
  const manage = canWrite && can("enquiry:manage");

  return (
    <>
      <Alert>{error}</Alert>
      <div className="card">
        {items.length === 0 ? (
          <Empty title="No enquiries yet">
            <p>Customers can ask about a product or request a proforma from your shop page.</p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>From</th>
                  <th>Message</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((enquiry) => (
                  <tr key={enquiry.id}>
                    <td className="muted nowrap">{dateTime(enquiry.created_at)}</td>
                    <td>
                      <button type="button" className="link" onClick={() => setSelected(enquiry.id)}>
                        {enquiry.contact_name}
                      </button>
                      <div className="muted" style={{ fontSize: "0.82rem" }}>
                        {enquiry.contact_phone}
                        {enquiry.wants_proforma ? " · wants a proforma" : ""}
                      </div>
                    </td>
                    <td className="muted">{enquiry.message ?? "—"}</td>
                    <td className="nowrap">
                      <Badge status={enquiry.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {open && (
        <Drawer title={`${open.reference} · ${open.contact_name}`} onClose={() => setSelected(null)}>
          <p>
            <strong>{open.contact_name}</strong> · {open.contact_phone}
            {open.contact_email ? ` · ${open.contact_email}` : ""}
            {open.company ? ` · ${open.company}` : ""}
          </p>
          {open.delivery_location && <p className="muted">Delivery: {open.delivery_location}</p>}
          {open.message && <p>{open.message}</p>}
          {open.items.length > 0 && (
            <ul>
              {open.items.map((item, index) => (
                <li key={index}>
                  {item.name ?? item.product_id} × {item.quantity ?? "1"}
                </li>
              ))}
            </ul>
          )}
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            An enquiry reserves no stock. Reply by phone{open.contact_email ? " or email" : ""}, or prepare a
            proforma.
          </p>
          {manage && (
            <div className="row">
              {open.status === "new" && (
                <button type="button" className="secondary" onClick={() => void setStatus(open, "in_review")}>
                  Mark in review
                </button>
              )}
              {can("quotation:manage") && (
                <button
                  type="button"
                  onClick={() => {
                    void setStatus(open, "quoted");
                    onQuote();
                  }}
                >
                  Prepare a proforma
                </button>
              )}
              {open.status !== "closed" && (
                <button type="button" className="secondary" onClick={() => void setStatus(open, "closed")}>
                  Close
                </button>
              )}
            </div>
          )}
        </Drawer>
      )}
    </>
  );
}

// --------------------------------------------------------------------------- //
// Proformas
// --------------------------------------------------------------------------- //

function Proformas() {
  const { session, can, canWrite } = useSession();
  const currency = session?.currency ?? "ETB";
  const [items, setItems] = useState<Quotation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Quotation | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await api.quotations({ limit: 100 })).items);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load proformas"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function send(quotation: Quotation) {
    try {
      const sent = await api.sendQuotation(quotation.id);
      setItems((all) => all.map((q) => (q.id === quotation.id ? sent : q)));
      setSelected(sent);
    } catch (cause) {
      setError(describeError(cause, "Could not send"));
    }
  }

  async function convert(quotation: Quotation) {
    if (!window.confirm(`Post a sale for ${quotation.number}? This deducts stock and records the sale.`)) return;
    try {
      const result = await api.convertQuotation(quotation.id, { payments: [] });
      setNotice(
        `Sale ${result.sale.number} posted from ${quotation.number}.` +
          (result.warnings.length ? ` ${result.warnings.join(" ")}` : ""),
      );
      setSelected(null);
      await load();
    } catch (cause) {
      setError(describeError(cause, "Could not convert"));
    }
  }

  const manage = canWrite && can("quotation:manage");

  return (
    <>
      <Alert>{error}</Alert>
      {notice && <Alert kind="ok">{notice}</Alert>}
      {manage && !creating && (
        <p>
          <button type="button" onClick={() => setCreating(true)}>
            New proforma
          </button>
        </p>
      )}
      {creating && (
        <NewProforma
          onDone={(created) => {
            setCreating(false);
            if (created) {
              void load();
              setSelected(created);
            }
          }}
        />
      )}
      <div className="card">
        <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
          A proforma is a numbered quotation. It is not a sale, a payment or a stock deduction until you
          convert it explicitly.
        </p>
        {items.length === 0 ? (
          <Empty title="No proformas yet" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Number</th>
                  <th>Customer</th>
                  <th>Valid until</th>
                  <th className="num">Total ({currency})</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((q) => (
                  <tr key={q.id}>
                    <td className="nowrap">
                      <button type="button" className="link" onClick={() => setSelected(q)}>
                        {q.number}
                      </button>
                    </td>
                    <td>{q.customer_company || q.customer_name}</td>
                    <td className="muted nowrap">{shortDate(q.valid_until)}</td>
                    <td className="num">{money(q.total_amount, currency)}</td>
                    <td className="nowrap">
                      <Badge status={q.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {selected && (
        <Drawer title={selected.number} onClose={() => setSelected(null)}>
          <p>
            <strong>{selected.customer_company || selected.customer_name}</strong>
            {selected.customer_phone ? ` · ${selected.customer_phone}` : ""} · <Badge status={selected.status} />
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="num">Qty</th>
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {selected.lines.map((line) => (
                  <tr key={line.id}>
                    <td>{line.description}</td>
                    <td className="num">{line.quantity}</td>
                    <td className="num">{money(line.line_total, currency)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                {Number(selected.delivery_charge) > 0 && (
                  <tr>
                    <td colSpan={2} className="num muted">Delivery</td>
                    <td className="num">{money(selected.delivery_charge, currency)}</td>
                  </tr>
                )}
                <tr>
                  <td colSpan={2} className="num"><strong>Total</strong></td>
                  <td className="num"><strong>{money(selected.total_amount, currency)}</strong></td>
                </tr>
              </tfoot>
            </table>
          </div>
          {selected.share?.url ? (
            <div className="card">
              <div className="card-title">Share</div>
              <p style={{ wordBreak: "break-all" }}>
                <a href={selected.share.url} target="_blank" rel="noreferrer">
                  {selected.share.url}
                </a>
              </p>
              <div className="row">
                <button type="button" className="secondary" onClick={() => void navigator.clipboard?.writeText(selected.share?.url ?? "")}>
                  Copy link
                </button>
                {selected.share.telegram && (
                  <a href={selected.share.telegram} target="_blank" rel="noreferrer">
                    <button type="button" className="secondary">Share on Telegram</button>
                  </a>
                )}
                {selected.share.mailto && (
                  <a href={selected.share.mailto}>
                    <button type="button" className="secondary">Send by email</button>
                  </a>
                )}
              </div>
              <p className="muted" style={{ fontSize: "0.85rem", marginBottom: 0 }}>
                The link opens a mobile-friendly page the customer can print or save as PDF, and accept or
                decline. Acceptance records intent only.
              </p>
            </div>
          ) : (
            manage &&
            selected.status === "draft" && (
              <p>
                <button type="button" onClick={() => void send(selected)}>
                  Send and get a share link
                </button>
              </p>
            )
          )}
          {manage && selected.status !== "converted" && selected.status !== "cancelled" && (
            <p>
              <button type="button" className="secondary" onClick={() => void convert(selected)}>
                Convert to a sale
              </button>
            </p>
          )}
          {selected.converted_sale_id && (
            <p>
              <Link href={`/sales/${selected.converted_sale_id}`}>See the sale →</Link>
            </p>
          )}
        </Drawer>
      )}
    </>
  );
}

function NewProforma({ onDone }: { onDone: (created: Quotation | null) => void }) {
  const { session } = useSession();
  const currency = session?.currency ?? "ETB";
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [company, setCompany] = useState("");
  const [delivery, setDelivery] = useState("");
  const [deliveryCharge, setDeliveryCharge] = useState("");
  const [validityDays, setValidityDays] = useState("14");
  const [terms, setTerms] = useState("");
  const [lines, setLines] = useState<Array<{ variantId: string; name: string; quantity: string; unitPrice: string }>>([]);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setResults([]);
    if (!search.trim()) return;
    let stale = false;
    const timer = setTimeout(() => {
      api
        .products({ q: search, limit: 8 })
        .then((page) => {
          if (!stale) setResults(page.items);
        })
        .catch(() => setResults([]));
    }, 200);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [search]);

  const total = lines.reduce((sum, l) => sum + Number(l.quantity || 0) * Number(l.unitPrice || 0), 0) + Number(deliveryCharge || 0);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.createQuotation({
        customer_name: customerName,
        customer_phone: customerPhone || undefined,
        customer_email: customerEmail || undefined,
        customer_company: company || undefined,
        delivery_location: delivery || undefined,
        delivery_charge: deliveryCharge || "0",
        validity_days: Number(validityDays) || 14,
        terms: terms || undefined,
        lines: lines.map((l) => ({ variant_id: l.variantId, quantity: l.quantity, unit_price: l.unitPrice || undefined })),
      });
      onDone(created);
    } catch (cause) {
      setError(describeError(cause, "Could not create the proforma"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">New proforma</div>
      <Alert>{error}</Alert>
      <div className="grid">
        <Field label="Customer name">
          <input value={customerName} onChange={(e) => setCustomerName(e.target.value)} required />
        </Field>
        <Field label="Phone" hint="optional">
          <input value={customerPhone} onChange={(e) => setCustomerPhone(e.target.value)} inputMode="tel" />
        </Field>
        <Field label="Email" hint="optional, for the email share">
          <input type="email" value={customerEmail} onChange={(e) => setCustomerEmail(e.target.value)} />
        </Field>
        <Field label="Company" hint="optional">
          <input value={company} onChange={(e) => setCompany(e.target.value)} />
        </Field>
        <Field label="Delivery location" hint="optional">
          <input value={delivery} onChange={(e) => setDelivery(e.target.value)} />
        </Field>
        <Field label="Delivery charge" hint="optional">
          <input value={deliveryCharge} onChange={(e) => setDeliveryCharge(e.target.value)} inputMode="decimal" />
        </Field>
        <Field label="Valid for (days)">
          <input value={validityDays} onChange={(e) => setValidityDays(e.target.value)} inputMode="numeric" />
        </Field>
      </div>
      <Field label="Add a product">
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Start typing…" />
      </Field>
      {results.length > 0 && (
        <div className="table-wrap" style={{ marginBottom: 10 }}>
          <table>
            <tbody>
              {results.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td className="num">{money(p.variants[0]?.selling_price, currency)}</td>
                  <td className="num">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        const v = p.variants[0];
                        if (v && !lines.some((l) => l.variantId === v.id)) {
                          setLines((all) => [...all, { variantId: v.id, name: p.name, quantity: "1", unitPrice: v.selling_price ?? "" }]);
                        }
                        setSearch("");
                        setResults([]);
                      }}
                    >
                      Add
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {lines.map((line) => (
        <div key={line.variantId} className="row" style={{ marginBottom: 8 }}>
          <span style={{ flex: 1 }}>{line.name}</span>
          <input style={{ width: 80, textAlign: "right" }} inputMode="decimal" value={line.quantity} onChange={(e) => setLines((all) => all.map((l) => (l.variantId === line.variantId ? { ...l, quantity: e.target.value } : l)))} />
          <input style={{ width: 120, textAlign: "right" }} inputMode="decimal" value={line.unitPrice} onChange={(e) => setLines((all) => all.map((l) => (l.variantId === line.variantId ? { ...l, unitPrice: e.target.value } : l)))} />
          <button type="button" className="link" onClick={() => setLines((all) => all.filter((l) => l.variantId !== line.variantId))}>
            Remove
          </button>
        </div>
      ))}
      <Field label="Terms" hint="optional">
        <textarea rows={2} value={terms} onChange={(e) => setTerms(e.target.value)} placeholder="e.g. 50% advance before delivery" />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy || lines.length === 0}>
          {busy ? "Saving…" : `Create proforma · ${money(total, currency)}`}
        </button>
        <button type="button" className="secondary" onClick={() => onDone(null)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
