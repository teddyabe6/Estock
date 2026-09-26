"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Empty, Field, PageHead } from "@/components/ui";
import { api, type Customer, type Product, type Variant } from "@/lib/api";
import { money } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

type CartLine = {
  variantId: string;
  productId: string;
  name: string;
  unitPrice: number;
  quantity: number;
  available: number | null;
};

const PAYMENT_METHODS = [
  { value: "cash", label: "Cash" },
  { value: "telebirr", label: "Telebirr" },
  { value: "cbe_birr", label: "CBE Birr" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "card", label: "Card" },
  { value: "cheque", label: "Cheque" },
];

const DUE_PRESETS = [
  { value: "", label: "No due date" },
  { value: "today", label: "Today" },
  { value: "tomorrow", label: "Tomorrow" },
  { value: "7_days", label: "In 7 days" },
  { value: "15_days", label: "In 15 days" },
  { value: "30_days", label: "In 30 days" },
];

export default function NewSalePage() {
  return (
    <AppShell>
      <NewSale />
    </AppShell>
  );
}

function NewSale() {
  const { session, can, canWrite } = useSession();
  const currency = session?.currency ?? "ETB";
  const branches = useMemo(() => session?.branches ?? [], [session]);

  const [search, setSearch] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [addingCustomer, setAddingCustomer] = useState(false);
  const [branchId, setBranchId] = useState("");
  const [method, setMethod] = useState("cash");
  const [amountPaid, setAmountPaid] = useState("");
  const [duePreset, setDuePreset] = useState("");
  const [creditNote, setCreditNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [lastSale, setLastSale] = useState<{ id: string; number: string; balance: string } | null>(null);
  const [busy, setBusy] = useState(false);
  // Generated once per cart, so a retried submission cannot post twice.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    // Results belong to one query: clear them the moment the query changes so
    // a fast tap can never add an item from the previous list.
    setResults([]);
    if (!search.trim()) return;
    let stale = false;
    const timer = setTimeout(() => {
      api
        .products({ q: search, limit: 20 })
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

  const loadCustomers = useCallback(
    () =>
      api
        .customers({ limit: 200 })
        .then((page) => setCustomers(page.items))
        .catch(() => setCustomers([])),
    [],
  );

  useEffect(() => {
    void loadCustomers();
  }, [loadCustomers]);

  useEffect(() => {
    if (!branchId && branches.length > 0) {
      setBranchId((branches.find((b) => b.is_default) ?? branches[0]).id);
    }
  }, [branches, branchId]);

  const total = useMemo(
    () => cart.reduce((sum, line) => sum + line.unitPrice * line.quantity, 0),
    [cart],
  );

  // Default to "paid in full"; the cashier can lower it to take partial payment.
  useEffect(() => {
    setAmountPaid(total ? total.toFixed(2) : "");
  }, [total]);

  const paid = Number(amountPaid || 0);
  const balance = Math.max(0, total - paid);

  const addVariant = useCallback(
    (variant: Variant, productId: string, name: string, trackStock: boolean) => {
      setCart((lines) => {
        const existing = lines.find((line) => line.variantId === variant.id);
        if (existing) {
          return lines.map((line) =>
            line.variantId === variant.id ? { ...line, quantity: line.quantity + 1 } : line,
          );
        }
        return [
          ...lines,
          {
            variantId: variant.id,
            productId,
            name,
            unitPrice: Number(variant.selling_price ?? 0),
            quantity: 1,
            available:
              trackStock && variant.quantity_on_hand !== null
                ? Number(variant.quantity_on_hand)
                : null,
          },
        ];
      });
      setLastSale(null);
    },
    [],
  );

  const addProduct = useCallback(
    (product: Product) => {
      const variant = product.variants[0];
      if (!variant) return;
      addVariant(variant, product.id, product.name, product.track_stock);
    },
    [addVariant],
  );

  async function scanBarcode(code: string) {
    try {
      const variant = await api.lookupBarcode(code);
      addVariant(
        variant,
        variant.product_id ?? variant.id,
        variant.display_name ?? variant.product_name ?? variant.sku ?? "Scanned item",
        variant.quantity_on_hand !== null,
      );
      setSearch("");
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Barcode not found"));
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (cart.length === 0) return;
    setBusy(true);
    setError(null);
    setWarnings([]);
    try {
      const payments = paid > 0 ? [{ method, amount: paid.toFixed(2) }] : [];
      const result = await api.createSale({
        lines: cart.map((line) => ({
          variant_id: line.variantId,
          quantity: String(line.quantity),
        })),
        payments,
        branch_id: branchId || undefined,
        customer_id: customerId || undefined,
        due_date_preset: balance > 0 && duePreset ? duePreset : undefined,
        credit_note: balance > 0 && creditNote ? creditNote : undefined,
        idempotency_key: idempotencyKey,
      });
      setWarnings(result.warnings ?? []);
      setLastSale({
        id: result.sale.id,
        number: result.sale.number,
        balance: result.sale.balance_due,
      });
      // Straight on to the next customer: the cart clears, the screen stays.
      setCart([]);
      setCustomerId("");
      setDuePreset("");
      setCreditNote("");
      setIdempotencyKey(crypto.randomUUID());
    } catch (cause) {
      setError(describeError(cause, "Could not complete the sale"));
    } finally {
      setBusy(false);
    }
  }

  if (!canWrite || !can("sale:create")) {
    return (
      <>
        <PageHead title="New sale" />
        <Alert kind="warn">You cannot record sales with this account.</Alert>
      </>
    );
  }

  return (
    <>
      <PageHead title="New sale" subtitle="Find products, take payment, done." />

      <Alert>{error}</Alert>
      {lastSale && (
        <Alert kind="ok">
          Sale {lastSale.number} recorded
          {Number(lastSale.balance) > 0
            ? ` with ${money(lastSale.balance, currency)} on credit`
            : ""}
          . <Link href={`/sales/${lastSale.id}`}>Receipt →</Link>
        </Alert>
      )}
      {warnings.map((warning) => (
        <Alert key={warning} kind="warn">
          {warning}
        </Alert>
      ))}

      <div className="card">
        <Field label="Find a product" hint="name, or scan a barcode">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              // A barcode scanner types fast and ends with Enter.
              if (e.key === "Enter" && search.trim()) {
                e.preventDefault();
                void scanBarcode(search.trim());
              }
            }}
            placeholder="Start typing or scan…"
            autoFocus
          />
        </Field>

        {search && results.length > 0 && (
          <div className="table-wrap">
            <table>
              <tbody>
                {results.slice(0, 8).map((product) => (
                  <tr key={product.id}>
                    <td>
                      {product.name}
                      {product.track_stock && (
                        <span className="muted" style={{ fontSize: "0.82rem" }}>
                          {" "}
                          · {product.quantity_on_hand ?? "0"} on hand
                        </span>
                      )}
                    </td>
                    <td className="num">{money(product.variants[0]?.selling_price, currency)}</td>
                    <td className="num">
                      <button type="button" className="secondary" onClick={() => addProduct(product)}>
                        Add
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <form onSubmit={submit}>
        <div className="card">
          <div className="card-title">Cart</div>
          {cart.length === 0 ? (
            <Empty title="Nothing added yet">
              <p>Search above, or scan a barcode.</p>
            </Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Item</th>
                    <th className="num">Price</th>
                    <th className="num">Qty</th>
                    <th className="num">Total</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {cart.map((line) => (
                    <tr key={line.variantId}>
                      <td>
                        {line.name}
                        {line.available !== null && line.quantity > line.available && (
                          <>
                            {" "}
                            <span className="badge danger">only {line.available} in stock</span>
                          </>
                        )}
                      </td>
                      <td className="num">{money(line.unitPrice, currency)}</td>
                      <td className="num" style={{ width: 90 }}>
                        <input
                          type="number"
                          min="0.001"
                          step="any"
                          value={line.quantity}
                          onChange={(e) =>
                            setCart((lines) =>
                              lines.map((item) =>
                                item.variantId === line.variantId
                                  ? { ...item, quantity: Number(e.target.value) }
                                  : item,
                              ),
                            )
                          }
                          style={{ textAlign: "right" }}
                        />
                      </td>
                      <td className="num">{money(line.unitPrice * line.quantity, currency)}</td>
                      <td className="num">
                        <button
                          type="button"
                          className="link"
                          onClick={() =>
                            setCart((lines) => lines.filter((item) => item.variantId !== line.variantId))
                          }
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {cart.length > 0 && (
          <div className="card">
            <div className="card-title">Payment</div>
            <div className="grid">
              {branches.length > 1 && (
                <Field label="Branch">
                  <select value={branchId} onChange={(e) => setBranchId(e.target.value)}>
                    {branches.map((branch) => (
                      <option key={branch.id} value={branch.id}>
                        {branch.name}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
              <Field label="Method">
                <select value={method} onChange={(e) => setMethod(e.target.value)}>
                  {PAYMENT_METHODS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Amount received" hint="lower it to sell on credit">
                <input value={amountPaid} onChange={(e) => setAmountPaid(e.target.value)} inputMode="decimal" />
              </Field>
              <Field label="Customer" hint={balance > 0 ? "required for credit" : "optional"}>
                <select
                  value={customerId}
                  onChange={(e) => {
                    if (e.target.value === "__new__") {
                      setAddingCustomer(true);
                    } else {
                      setCustomerId(e.target.value);
                    }
                  }}
                  required={balance > 0}
                >
                  <option value="">Walk-in customer</option>
                  {customers.map((customer) => (
                    <option key={customer.id} value={customer.id}>
                      {customer.name}
                      {customer.phone ? ` · ${customer.phone}` : ""}
                    </option>
                  ))}
                  {can("customer:manage") && <option value="__new__">+ New customer…</option>}
                </select>
              </Field>
              {balance > 0 && (
                <>
                  <Field label="Payment due" hint="optional">
                    <select value={duePreset} onChange={(e) => setDuePreset(e.target.value)}>
                      {DUE_PRESETS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Agreement" hint="optional">
                    <input
                      value={creditNote}
                      onChange={(e) => setCreditNote(e.target.value)}
                      placeholder="e.g. pays after delivery"
                    />
                  </Field>
                </>
              )}
            </div>

            {addingCustomer && (
              <QuickCustomer
                onDone={(customer) => {
                  setAddingCustomer(false);
                  if (customer) {
                    setCustomers((all) =>
                      [...all, customer].sort((a, b) => a.name.localeCompare(b.name)),
                    );
                    setCustomerId(customer.id);
                  }
                }}
              />
            )}

            <div className="grid" style={{ marginTop: 6 }}>
              <div className="stat">
                <div className="label">Total</div>
                <div className="value">{money(total, currency)}</div>
              </div>
              <div className={balance > 0 ? "stat is-warn" : "stat"}>
                <div className="label">{balance > 0 ? "On credit" : "Change due"}</div>
                <div className="value">{money(balance > 0 ? balance : paid - total, currency)}</div>
                {balance > 0 && !duePreset && (
                  <div className="note">No due date: stays outstanding, never marked overdue.</div>
                )}
                {balance > 0 && duePreset && (
                  <div className="note">A reminder is scheduled for staff. Nothing is sent to the customer.</div>
                )}
              </div>
            </div>

            <button type="submit" disabled={busy} style={{ marginTop: 10 }}>
              {busy ? "Recording…" : `Complete sale · ${money(total, currency)}`}
            </button>
          </div>
        )}
      </form>
    </>
  );
}

/** Name and phone are enough for a walk-in who wants credit (PRD 12). */
function QuickCustomer({ onDone }: { onDone: (customer: Customer | null) => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const customer = await api.createCustomer({ name: name.trim(), phone: phone || undefined });
      onDone(customer);
    } catch (cause) {
      setError(describeError(cause, "Could not save the customer"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginTop: 0, marginBottom: 12 }}>
      <div className="card-title">New customer</div>
      <Alert>{error}</Alert>
      <div className="grid">
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label="Phone" hint="optional">
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            inputMode="tel"
            placeholder="0911234567"
          />
        </Field>
      </div>
      <div className="row">
        <button type="button" disabled={busy || !name.trim()} onClick={() => void save()}>
          {busy ? "Saving…" : "Save customer"}
        </button>
        <button type="button" className="secondary" onClick={() => onDone(null)}>
          Cancel
        </button>
      </div>
    </div>
  );
}
