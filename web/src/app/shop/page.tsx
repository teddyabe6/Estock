"use client";

/**
 * The online shop from the seller's side: storefront settings, questions from
 * customers, and proformas — including the requests customers make from
 * their basket on the shop page (PRD 13, 14). Same catalogue and stock as the
 * counter; a request or proforma never touches stock until it is converted.
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
  const [summary, setSummary] = useState<{ proforma_requests: number; new_enquiries: number } | null>(null);

  const refreshSummary = useCallback(() => {
    api.shopSummary().then(setSummary).catch(() => setSummary(null));
  }, []);

  useEffect(() => {
    refreshSummary();
  }, [refreshSummary]);

  const tabs = [
    { value: "storefront" as const, label: "Storefront", show: true },
    {
      value: "enquiries" as const,
      label: summary?.new_enquiries ? `Questions (${summary.new_enquiries})` : "Questions",
      show: can("enquiry:view"),
    },
    {
      value: "proformas" as const,
      label: summary?.proforma_requests ? `Proformas (${summary.proforma_requests} new)` : "Proformas",
      show: can("quotation:view"),
    },
  ].filter((t) => t.show);

  return (
    <>
      <PageHead title="Online shop" subtitle="The same products and stock as the counter" />
      <Tabs value={tab} options={tabs} onChange={setTab} />
      {tab === "storefront" && <Storefront />}
      {tab === "enquiries" && (
        <Enquiries openId={params.get("open")} onQuote={() => setTab("proformas")} onChanged={refreshSummary} />
      )}
      {tab === "proformas" && <Proformas openId={params.get("open")} onChanged={refreshSummary} />}
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
        checkout_note: s.checkout_note ?? "",
        default_terms: s.default_terms ?? "",
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
          checkout_note: form.checkout_note || null,
          default_terms: form.default_terms || null,
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
  const withoutPhoto = published.filter((p) => !p.image_url).length;

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
          <p className="muted" style={{ fontSize: "0.9rem", marginBottom: 0 }}>
            Customers browse by category, fill a basket and request a proforma. You review the prices and
            send it; nothing is reserved or sold until you convert it.
          </p>
          {manage && (
            <Toggle
              label="Show prices to visitors"
              hint="off means visitors see 'ask for a price' and your proforma request arrives unpriced for them"
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
          <Field label="Shown at checkout" hint="how you confirm, delivery areas, pickup">
            <textarea
              rows={2}
              value={form.checkout_note ?? ""}
              onChange={(e) => setForm({ ...form, checkout_note: e.target.value })}
              placeholder="e.g. We confirm prices and delivery by phone within one working day."
            />
          </Field>
          <Field label="Terms on every requested proforma" hint="optional">
            <textarea
              rows={2}
              value={form.default_terms ?? ""}
              onChange={(e) => setForm({ ...form, default_terms: e.target.value })}
              placeholder="e.g. Prices valid for 14 days. 50% advance before delivery."
            />
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
          {withoutPhoto > 0 && (
            <>
              {" "}
              {withoutPhoto} published {withoutPhoto === 1 ? "product has" : "products have"} no photo yet —
              add one from <Link href="/products">Products</Link>.
            </>
          )}
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

function Enquiries({
  openId,
  onQuote,
  onChanged,
}: {
  openId: string | null;
  onQuote: () => void;
  onChanged: () => void;
}) {
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
      onChanged();
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
          <Empty title="No questions yet">
            <p>Customers can ask about a product from your shop page. Basket requests appear under Proformas.</p>
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
            A question reserves no stock. Reply by phone{open.contact_email ? " or email" : ""}, or prepare a
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

type Filter = "all" | "requested" | "sent" | "accepted" | "converted" | "closed";

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "requested", label: "New requests" },
  { value: "sent", label: "Sent" },
  { value: "accepted", label: "Accepted" },
  { value: "converted", label: "Sold" },
  { value: "closed", label: "Declined, expired, cancelled" },
  { value: "all", label: "All" },
];

function matches(filter: Filter, status: string): boolean {
  switch (filter) {
    case "all":
      return true;
    case "closed":
      return status === "declined" || status === "expired" || status === "cancelled";
    case "sent":
      return status === "sent" || status === "draft";
    default:
      return status === filter;
  }
}

function Proformas({ openId, onChanged }: { openId: string | null; onChanged: () => void }) {
  const { session, can, canWrite } = useSession();
  const currency = session?.currency ?? "ETB";
  const [items, setItems] = useState<Quotation[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(openId);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const page = await api.quotations({ limit: 200 });
      setItems(page.items);
      setError(null);
      if (page.items.some((q) => q.status === "requested") && filter === "all" && !openId) {
        setFilter("requested");
      }
    } catch (cause) {
      setError(describeError(cause, "Could not load proformas"));
    }
    // The filter should settle on first load only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openId]);

  useEffect(() => {
    void load();
  }, [load]);

  function replace(updated: Quotation) {
    setItems((all) => (all ? all.map((q) => (q.id === updated.id ? updated : q)) : all));
    onChanged();
  }

  const manage = canWrite && can("quotation:manage");
  const selected = items?.find((q) => q.id === selectedId) ?? null;
  const shown = (items ?? []).filter((q) => matches(filter, q.status));
  const counts = (items ?? []).reduce<Record<string, number>>((acc, q) => {
    acc[q.status] = (acc[q.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <Alert>{error}</Alert>
      {notice && <Alert kind="ok">{notice}</Alert>}
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <div className="chips" style={{ marginBottom: 0, paddingBottom: 0 }}>
          {FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`chip${filter === option.value ? " is-active" : ""}`}
              onClick={() => setFilter(option.value)}
            >
              {option.label}
              {option.value === "requested" && counts.requested ? ` (${counts.requested})` : ""}
            </button>
          ))}
        </div>
        {manage && !creating && (
          <button type="button" onClick={() => setCreating(true)}>
            New proforma
          </button>
        )}
      </div>
      {creating && (
        <NewProforma
          onDone={(created) => {
            setCreating(false);
            if (created) {
              void load();
              setSelectedId(created.id);
            }
          }}
        />
      )}
      <div className="card">
        <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
          A proforma is a numbered quotation. Requests from your shop page arrive priced from your catalogue;
          review, then send. It is not a sale, a payment or a stock deduction until you convert it.
        </p>
        {items === null ? (
          <p className="muted">Loading…</p>
        ) : shown.length === 0 ? (
          <Empty title={filter === "all" ? "No proformas yet" : "Nothing here"} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Number</th>
                  <th>Customer</th>
                  <th>When</th>
                  <th className="num">Total ({currency})</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((q) => (
                  <tr key={q.id}>
                    <td className="nowrap">
                      <button type="button" className="link" onClick={() => setSelectedId(q.id)}>
                        {q.number}
                      </button>
                      {q.source === "storefront" && (
                        <>
                          {" "}
                          <span className="badge">online</span>
                        </>
                      )}
                    </td>
                    <td>
                      {q.customer_company || q.customer_name}
                      {q.customer_message && (
                        <div className="muted" style={{ fontSize: "0.82rem" }}>
                          “{q.customer_message}”
                        </div>
                      )}
                    </td>
                    <td className="muted nowrap">{q.created_at ? dateTime(q.created_at) : shortDate(q.issued_on)}</td>
                    <td className="num">{money(q.total_amount, currency)}</td>
                    <td className="nowrap">
                      <Badge status={q.status} label={q.status === "requested" ? "new request" : undefined} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {selected && (
        <ProformaDrawer
          quotation={selected}
          manage={manage}
          currency={currency}
          onClose={() => setSelectedId(null)}
          onChanged={replace}
          onConverted={(text) => {
            setNotice(text);
            setSelectedId(null);
            void load();
          }}
        />
      )}
    </>
  );
}

type EditableLine = { key: string; variantId: string | null; description: string; quantity: string; unitPrice: string; discount: string };

function toEditable(quotation: Quotation): EditableLine[] {
  return quotation.lines.map((line) => ({
    key: line.id,
    variantId: line.variant_id,
    description: line.description,
    quantity: line.quantity,
    unitPrice: line.unit_price,
    discount: Number(line.discount_amount) > 0 ? line.discount_amount : "",
  }));
}

function ProformaDrawer({
  quotation,
  manage,
  currency,
  onClose,
  onChanged,
  onConverted,
}: {
  quotation: Quotation;
  manage: boolean;
  currency: string;
  onClose: () => void;
  onChanged: (updated: Quotation) => void;
  onConverted: (notice: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [lines, setLines] = useState<EditableLine[]>(() => toEditable(quotation));
  const [delivery, setDelivery] = useState(quotation.delivery_charge);
  const [validityDays, setValidityDays] = useState("14");
  const [terms, setTerms] = useState(quotation.terms ?? "");
  const [note, setNote] = useState(quotation.note ?? "");
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setLines(toEditable(quotation));
    setDelivery(quotation.delivery_charge);
    setTerms(quotation.terms ?? "");
    setNote(quotation.note ?? "");
    setEditing(false);
  }, [quotation]);

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

  const estimated =
    lines.reduce((sum, l) => sum + Math.max(Number(l.quantity || 0) * Number(l.unitPrice || 0) - Number(l.discount || 0), 0), 0) +
    Number(delivery || 0);

  async function run<T>(work: () => Promise<T>, fallback: string): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (cause) {
      setError(describeError(cause, fallback));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function save(): Promise<Quotation | null> {
    const updated = await run(
      () =>
        api.updateQuotation(quotation.id, {
          lines: lines.map((l) => ({
            variant_id: l.variantId ?? undefined,
            description: l.variantId ? undefined : l.description,
            quantity: l.quantity,
            unit_price: l.unitPrice === "" ? undefined : l.unitPrice,
            discount_amount: l.discount === "" ? undefined : l.discount,
          })),
          delivery_charge: delivery || "0",
          validity_days: Number(validityDays) || 14,
          terms: terms || null,
          note: note || null,
        }),
      "Could not save the proforma",
    );
    if (updated) {
      onChanged(updated);
      setEditing(false);
    }
    return updated;
  }

  async function send() {
    if (editing) {
      const saved = await save();
      if (!saved) return;
    }
    const sent = await run(() => api.sendQuotation(quotation.id), "Could not send");
    if (sent) onChanged(sent);
  }

  async function cancel() {
    const reason = window.prompt(`Cancel ${quotation.number}? The customer's link will stop working. Reason (optional):`);
    if (reason === null) return;
    const cancelled = await run(() => api.cancelQuotation(quotation.id, reason), "Could not cancel");
    if (cancelled) onChanged(cancelled);
  }

  async function convert() {
    if (!window.confirm(`Post a sale for ${quotation.number}? This deducts stock and records the sale.`)) return;
    const result = await run(() => api.convertQuotation(quotation.id, { payments: [] }), "Could not convert");
    if (result) {
      onConverted(
        `Sale ${result.sale.number} posted from ${quotation.number}.` +
          (result.warnings.length ? ` ${result.warnings.join(" ")}` : ""),
      );
    }
  }

  function copyLink() {
    if (!quotation.share?.url) return;
    void navigator.clipboard?.writeText(quotation.share.url);
    setCopied(true);
  }

  const isRequest = quotation.status === "requested";
  const canEdit = manage && quotation.can_edit;
  const canSend = manage && quotation.can_edit;
  const canConvert = manage && quotation.status !== "converted" && quotation.status !== "cancelled";
  const canCancel = manage && quotation.status !== "converted" && quotation.status !== "cancelled";

  return (
    <Drawer title={quotation.number} onClose={onClose}>
      <Alert>{error}</Alert>
      <p>
        <strong>{quotation.customer_company || quotation.customer_name}</strong>
        {quotation.customer_phone ? ` · ${quotation.customer_phone}` : ""}
        {quotation.customer_email ? ` · ${quotation.customer_email}` : ""} ·{" "}
        <Badge status={quotation.status} label={isRequest ? "new request" : undefined} />
        {quotation.source === "storefront" && (
          <>
            {" "}
            <span className="badge">from your online shop</span>
          </>
        )}
      </p>
      {quotation.delivery_location && <p className="muted">Deliver to: {quotation.delivery_location}</p>}
      {quotation.customer_message && (
        <p>
          <span className="muted">Customer&apos;s note:</span> “{quotation.customer_message}”
        </p>
      )}
      {isRequest && (
        <Alert kind="ok">
          Check the prices and add a delivery charge if needed, then send. The customer already has the link
          and will see the priced proforma there.
        </Alert>
      )}

      {editing ? (
        <div className="card">
          <div className="card-title">Items</div>
          {lines.map((line) => (
            <div key={line.key} className="row" style={{ marginBottom: 8 }}>
              <span style={{ flex: 1, minWidth: 140 }}>{line.description}</span>
              <input
                style={{ width: 80, textAlign: "right" }}
                inputMode="decimal"
                aria-label="Quantity"
                value={line.quantity}
                onChange={(e) => setLines((all) => all.map((l) => (l.key === line.key ? { ...l, quantity: e.target.value } : l)))}
              />
              <input
                style={{ width: 110, textAlign: "right" }}
                inputMode="decimal"
                aria-label="Unit price"
                placeholder="Unit price"
                value={line.unitPrice}
                onChange={(e) => setLines((all) => all.map((l) => (l.key === line.key ? { ...l, unitPrice: e.target.value } : l)))}
              />
              <input
                style={{ width: 90, textAlign: "right" }}
                inputMode="decimal"
                aria-label="Discount"
                placeholder="Discount"
                value={line.discount}
                onChange={(e) => setLines((all) => all.map((l) => (l.key === line.key ? { ...l, discount: e.target.value } : l)))}
              />
              <button type="button" className="link" onClick={() => setLines((all) => all.filter((l) => l.key !== line.key))}>
                Remove
              </button>
            </div>
          ))}
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
                              setLines((all) => [
                                ...all,
                                { key: v.id, variantId: v.id, description: p.name, quantity: "1", unitPrice: v.selling_price ?? "", discount: "" },
                              ]);
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
          <div className="grid">
            <Field label="Delivery charge">
              <input value={delivery} onChange={(e) => setDelivery(e.target.value)} inputMode="decimal" />
            </Field>
            <Field label="Valid for (days)">
              <input value={validityDays} onChange={(e) => setValidityDays(e.target.value)} inputMode="numeric" />
            </Field>
          </div>
          <Field label="Note to the customer" hint="optional, shown on the proforma">
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <Field label="Terms" hint="optional">
            <textarea rows={2} value={terms} onChange={(e) => setTerms(e.target.value)} />
          </Field>
          <div className="row">
            <button type="button" disabled={busy || lines.length === 0} onClick={() => void save()}>
              {busy ? "Saving…" : `Save · ${money(estimated, currency)}`}
            </button>
            <button type="button" className="secondary" disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="num">Qty</th>
                  <th className="num">Unit</th>
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {quotation.lines.map((line) => (
                  <tr key={line.id}>
                    <td>{line.description}</td>
                    <td className="num">{Number(line.quantity).toLocaleString()}</td>
                    <td className="num">{money(line.unit_price, currency)}</td>
                    <td className="num">{money(line.line_total, currency)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                {Number(quotation.discount_total) > 0 && (
                  <tr>
                    <td colSpan={3} className="num muted">Discount</td>
                    <td className="num">−{money(quotation.discount_total, currency)}</td>
                  </tr>
                )}
                {Number(quotation.tax_total) > 0 && (
                  <tr>
                    <td colSpan={3} className="num muted">Tax</td>
                    <td className="num">{money(quotation.tax_total, currency)}</td>
                  </tr>
                )}
                {Number(quotation.delivery_charge) > 0 && (
                  <tr>
                    <td colSpan={3} className="num muted">Delivery</td>
                    <td className="num">{money(quotation.delivery_charge, currency)}</td>
                  </tr>
                )}
                <tr>
                  <td colSpan={3} className="num"><strong>Total</strong></td>
                  <td className="num"><strong>{money(quotation.total_amount, currency)}</strong></td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            {quotation.valid_until ? `Valid until ${shortDate(quotation.valid_until)}. ` : ""}
            {quotation.terms ? quotation.terms : ""}
          </p>
          {canEdit && (
            <p>
              <button type="button" className="secondary" onClick={() => setEditing(true)}>
                {isRequest ? "Adjust prices or items" : "Edit"}
              </button>
            </p>
          )}
        </>
      )}

      {!editing && (
        <div className="row" style={{ marginTop: 6 }}>
          {canSend && (
            <button type="button" disabled={busy} onClick={() => void send()}>
              {isRequest ? "Confirm and send proforma" : quotation.status === "sent" ? "Send again" : "Send and get a share link"}
            </button>
          )}
          {canConvert && !isRequest && (
            <button type="button" className="secondary" disabled={busy} onClick={() => void convert()}>
              Convert to a sale
            </button>
          )}
          {canCancel && (
            <button type="button" className="link" disabled={busy} onClick={() => void cancel()}>
              Cancel proforma
            </button>
          )}
        </div>
      )}

      {quotation.share?.url && (
        <div className="card">
          <div className="card-title">{isRequest ? "The customer's tracking link" : "Share"}</div>
          <p style={{ wordBreak: "break-all" }}>
            <a href={quotation.share.url} target="_blank" rel="noreferrer">
              {quotation.share.url}
            </a>
          </p>
          <div className="row">
            <button type="button" className="secondary" onClick={copyLink}>
              {copied ? "Copied" : "Copy link"}
            </button>
            {quotation.share.telegram && (
              <a href={quotation.share.telegram} target="_blank" rel="noreferrer" className="btn secondary">
                Share on Telegram
              </a>
            )}
            {quotation.share.mailto && (
              <a href={quotation.share.mailto} className="btn secondary">
                Send by email
              </a>
            )}
          </div>
          <p className="muted" style={{ fontSize: "0.85rem", marginBottom: 0 }}>
            {isRequest
              ? "The customer sees their request here now, and the priced proforma once you send it."
              : "The link opens a mobile-friendly page the customer can print or save as PDF, and accept or decline. Acceptance records intent only."}
          </p>
        </div>
      )}
      {quotation.converted_sale_id && (
        <p>
          <Link href={`/sales/${quotation.converted_sale_id}`}>See the sale →</Link>
        </p>
      )}
    </Drawer>
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
