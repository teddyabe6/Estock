"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Empty, Field, PageHead } from "@/components/ui";
import { api, type Customer, type Product } from "@/lib/api";
import { money } from "@/lib/format";
import { useSession } from "@/lib/session";

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
  const { session } = useSession();
  const router = useRouter();
  const currency = session?.currency ?? "ETB";

  const [search, setSearch] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [method, setMethod] = useState("cash");
  const [amountPaid, setAmountPaid] = useState("");
  const [duePreset, setDuePreset] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  // Generated once per cart, so a retried submission cannot post twice.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .products({ q: search || undefined, limit: 20 })
        .then((page) => setResults(page.items))
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    api
      .customers({ limit: 100 })
      .then((page) => setCustomers(page.items))
      .catch(() => setCustomers([]));
  }, []);

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

  const addProduct = useCallback((product: Product) => {
    const variant = product.variants[0];
    if (!variant) return;
    setCart((lines) => {
      const existing = lines.find((line) => line.variantId === variant.id);
      if (existing) {
        return lines.map((line) =>
          line.variantId === variant.id
            ? { ...line, quantity: line.quantity + 1 }
            : line,
        );
      }
      return [
        ...lines,
        {
          variantId: variant.id,
          productId: product.id,
          name: product.name,
          unitPrice: Number(variant.selling_price ?? 0),
          quantity: 1,
          available: product.track_stock ? Number(product.quantity_on_hand ?? 0) : null,
        },
      ];
    });
  }, []);

  async function scanBarcode(code: string) {
    try {
      const variant = await api.lookupBarcode(code);
      setCart((lines) => {
        const existing = lines.find((line) => line.variantId === variant.id);
        if (existing) {
          return lines.map((line) =>
            line.variantId === variant.id
              ? { ...line, quantity: line.quantity + 1 }
              : line,
          );
        }
        return [
          ...lines,
          {
            variantId: variant.id,
            productId: variant.id,
            name: variant.name ?? variant.sku ?? "Scanned item",
            unitPrice: Number(variant.selling_price ?? 0),
            quantity: 1,
            available:
              variant.quantity_on_hand === null ? null : Number(variant.quantity_on_hand),
          },
        ];
      });
      setSearch("");
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Barcode not found");
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (cart.length === 0) return;
    setBusy(true);
    setError(null);
    setWarnings([]);
    try {
      const payments =
        paid > 0 ? [{ method, amount: paid.toFixed(2) }] : [];
      const result = await api.createSale({
        lines: cart.map((line) => ({
          variant_id: line.variantId,
          quantity: String(line.quantity),
        })),
        payments,
        customer_id: customerId || undefined,
        due_date_preset: balance > 0 && duePreset ? duePreset : undefined,
        idempotency_key: idempotencyKey,
      });
      setWarnings(result.warnings ?? []);
      setCart([]);
      setCustomerId("");
      setIdempotencyKey(crypto.randomUUID());
      router.push(`/sales?highlight=${result.sale.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not complete the sale");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead title="New sale" subtitle="Find products, take payment, done." />

      <Alert>{error}</Alert>
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
                    <td>{product.name}</td>
                    <td className="num">
                      {money(product.variants[0]?.selling_price, currency)}
                    </td>
                    <td className="num">
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => addProduct(product)}
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
                            <span className="badge danger">
                              only {line.available} in stock
                            </span>
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
                      <td className="num">
                        {money(line.unitPrice * line.quantity, currency)}
                      </td>
                      <td className="num">
                        <button
                          type="button"
                          className="link"
                          onClick={() =>
                            setCart((lines) =>
                              lines.filter((item) => item.variantId !== line.variantId),
                            )
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
                <input
                  value={amountPaid}
                  onChange={(e) => setAmountPaid(e.target.value)}
                  inputMode="decimal"
                />
              </Field>
              <Field label="Customer" hint={balance > 0 ? "required for credit" : "optional"}>
                <select
                  value={customerId}
                  onChange={(e) => setCustomerId(e.target.value)}
                  required={balance > 0}
                >
                  <option value="">Walk-in customer</option>
                  {customers.map((customer) => (
                    <option key={customer.id} value={customer.id}>
                      {customer.name}
                      {customer.phone ? ` · ${customer.phone}` : ""}
                    </option>
                  ))}
                </select>
              </Field>
              {balance > 0 && (
                <Field label="Payment due" hint="optional">
                  <select value={duePreset} onChange={(e) => setDuePreset(e.target.value)}>
                    {DUE_PRESETS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
            </div>

            <div className="grid" style={{ marginTop: 6 }}>
              <div className="stat">
                <div className="label">Total</div>
                <div className="value">{money(total, currency)}</div>
              </div>
              <div className={balance > 0 ? "stat is-warn" : "stat"}>
                <div className="label">{balance > 0 ? "On credit" : "Change due"}</div>
                <div className="value">
                  {money(balance > 0 ? balance : paid - total, currency)}
                </div>
                {balance > 0 && !duePreset && (
                  <div className="note">
                    No due date: stays outstanding, never marked overdue.
                  </div>
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
