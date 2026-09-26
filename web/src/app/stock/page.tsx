"use client";

/**
 * Stock: what is on hand, receiving from suppliers (with supplier credit),
 * adjustments, transfers between branches and the movement ledger (PRD 9,
 * 11.2, A3). Every change here is a traceable movement with a reason.
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Empty, Field, PageHead, Tabs } from "@/components/ui";
import {
  api,
  type Movement,
  type Product,
  type StockLevel,
  type StockLocation,
  type Supplier,
  type Transfer,
} from "@/lib/api";
import { dateTime, money, quantity } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

type Tab = "levels" | "receive" | "adjust" | "transfers" | "movements";

export default function StockPage() {
  return (
    <AppShell>
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <Stock />
      </Suspense>
    </AppShell>
  );
}

function Stock() {
  const { can, canWrite } = useSession();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(params.get("tab") === "receive" ? "receive" : "levels");
  const [error, setError] = useState<string | null>(null);

  const tabs = useMemo(
    () =>
      [
        { value: "levels" as const, label: "On hand", show: true },
        { value: "receive" as const, label: "Receive stock", show: canWrite && can("stock:receive") && can("purchase:create") },
        { value: "adjust" as const, label: "Adjust", show: canWrite && can("stock:adjust") },
        { value: "transfers" as const, label: "Transfers", show: can("stock:transfer") },
        { value: "movements" as const, label: "History", show: true },
      ].filter((t) => t.show),
    [can, canWrite],
  );

  return (
    <>
      <PageHead
        title="Stock"
        subtitle="One ledger for the counter and the online shop"
        actions={
          can("report:inventory") ? (
            <button
              type="button"
              className="secondary"
              onClick={() => api.exportStock().catch((c) => setError(describeError(c)))}
            >
              Export CSV
            </button>
          ) : null
        }
      />
      <Alert>{error}</Alert>
      <Tabs value={tab} options={tabs} onChange={setTab} />
      {tab === "levels" && <Levels initialLow={params.get("view") === "low"} />}
      {tab === "receive" && <Receive onDone={() => setTab("movements")} />}
      {tab === "adjust" && <Adjust onDone={() => setTab("movements")} />}
      {tab === "transfers" && <Transfers />}
      {tab === "movements" && <Movements />}
    </>
  );
}

// --------------------------------------------------------------------------- //
// Shared pickers
// --------------------------------------------------------------------------- //

function useLocations() {
  const { session } = useSession();
  const [locations, setLocations] = useState<StockLocation[]>([]);
  useEffect(() => {
    api.locations().then(setLocations).catch(() => setLocations([]));
  }, []);
  // The business's main branch first, so it is the default everywhere below.
  const mainBranch = session?.branches.find((b) => b.is_default)?.id;
  return useMemo(
    () =>
      [...locations].sort((a, b) => {
        if (a.branch_id === mainBranch && b.branch_id !== mainBranch) return -1;
        if (b.branch_id === mainBranch && a.branch_id !== mainBranch) return 1;
        return a.name.localeCompare(b.name);
      }),
    [locations, mainBranch],
  );
}

function ProductPicker({
  onPick,
  label = "Find a product",
}: {
  onPick: (product: Product) => void;
  label?: string;
}) {
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<Product[]>([]);

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

  return (
    <div>
      <Field label={label} hint="name, SKU or barcode">
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Start typing…" />
      </Field>
      {results.length > 0 && (
        <div className="table-wrap" style={{ marginBottom: 12 }}>
          <table>
            <tbody>
              {results.map((product) => (
                <tr key={product.id}>
                  <td>
                    {product.name}
                    <span className="muted" style={{ fontSize: "0.82rem" }}>
                      {" "}
                      · {product.track_stock ? `${quantity(product.quantity_on_hand)} on hand` : "not stocked"}
                    </span>
                  </td>
                  <td className="num">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        onPick(product);
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
    </div>
  );
}

// --------------------------------------------------------------------------- //
// On hand
// --------------------------------------------------------------------------- //

function Levels({ initialLow }: { initialLow: boolean }) {
  const [items, setItems] = useState<StockLevel[]>([]);
  const [search, setSearch] = useState("");
  const [lowOnly, setLowOnly] = useState(initialLow);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const timer = setTimeout(() => {
      const request = lowOnly
        ? api.lowStock()
        : api.stockLevels({ q: search || undefined, limit: 200 }).then((page) => page.items);
      request
        .then((rows) => {
          setItems(rows);
          setError(null);
        })
        .catch((cause) => setError(describeError(cause, "Could not load stock")))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(timer);
  }, [search, lowOnly]);

  return (
    <div className="card">
      <Alert>{error}</Alert>
      <div className="row" style={{ marginBottom: 8 }}>
        {!lowOnly && (
          <div style={{ flex: 1, minWidth: 200 }}>
            <Field label="Search">
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Product name…" />
            </Field>
          </div>
        )}
        <button type="button" className={lowOnly ? undefined : "secondary"} onClick={() => setLowOnly((v) => !v)}>
          {lowOnly ? "Showing low stock" : "Show low stock"}
        </button>
      </div>

      {items.length === 0 && !loading ? (
        <Empty title={lowOnly ? "Nothing needs restocking" : "No stock recorded"}>
          <p>
            {lowOnly
              ? "Every tracked product is above its reorder level."
              : "Add products with an opening quantity, or receive stock from a supplier."}
          </p>
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>Branch</th>
                <th className="num">On hand</th>
                <th className="num">Min</th>
                <th className="num">Reorder at</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={`${row.variant_id}-${row.branch_id}`}>
                  <td>{row.name}</td>
                  <td className="muted">{row.branch_name ?? "—"}</td>
                  <td className="num">{quantity(row.quantity)}</td>
                  <td className="num muted">{quantity(row.min_stock)}</td>
                  <td className="num muted">{quantity(row.reorder_level)}</td>
                  <td className="nowrap">
                    <Badge status={row.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Receive stock (A3)
// --------------------------------------------------------------------------- //

type ReceiveLine = { variantId: string; name: string; quantity: string; unitCost: string };

function Receive({ onDone }: { onDone: () => void }) {
  const { session, can } = useSession();
  const currency = session?.currency ?? "ETB";
  const locations = useLocations();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [newSupplier, setNewSupplier] = useState("");
  const [locationId, setLocationId] = useState("");
  const [lines, setLines] = useState<ReceiveLine[]>([]);
  const [transport, setTransport] = useState("");
  const [other, setOther] = useState("");
  const [allocation, setAllocation] = useState("by_value");
  const [amountPaid, setAmountPaid] = useState("");
  const [method, setMethod] = useState("cash");
  const [invoiceRef, setInvoiceRef] = useState("");
  const [duePreset, setDuePreset] = useState("");
  const [reprice, setReprice] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    api.suppliers({ limit: 200 }).then((page) => setSuppliers(page.items)).catch(() => setSuppliers([]));
  }, []);

  useEffect(() => {
    if (!locationId && locations.length > 0) setLocationId(locations[0].id);
  }, [locations, locationId]);

  const goodsTotal = lines.reduce((sum, l) => sum + Number(l.quantity || 0) * Number(l.unitCost || 0), 0);
  const total = goodsTotal + Number(transport || 0) + Number(other || 0);
  const balance = Math.max(0, total - Number(amountPaid || 0));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (lines.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      let supplier = supplierId;
      if (supplier === "__new__" && newSupplier.trim()) {
        const created = await api.createSupplier({ name: newSupplier.trim() });
        supplier = created.id;
      }
      const location = locations.find((l) => l.id === locationId);
      const result = await api.receivePurchase({
        lines: lines.map((l) => ({ variant_id: l.variantId, quantity: l.quantity, unit_cost: l.unitCost })),
        supplier_id: supplier && supplier !== "__new__" ? supplier : undefined,
        branch_id: location?.branch_id,
        location_id: locationId || undefined,
        transport_cost: transport || "0",
        other_costs: other || "0",
        cost_allocation_method: allocation,
        amount_paid: amountPaid || "0",
        payment_method: method,
        supplier_invoice_ref: invoiceRef || undefined,
        due_date_preset: balance > 0 && duePreset ? duePreset : undefined,
        reprice_from_cost: reprice,
        idempotency_key: idempotencyKey,
      });
      setDone(
        `Received ${result.purchase.number} for ${money(result.purchase.total_amount, currency)}` +
          (result.credit_transaction_id ? ` with ${money(result.purchase.balance_due, currency)} owed to the supplier.` : "."),
      );
      setLines([]);
      setTransport("");
      setOther("");
      setAmountPaid("");
      setInvoiceRef("");
      setIdempotencyKey(crypto.randomUUID());
    } catch (cause) {
      setError(describeError(cause, "Could not receive the stock"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <Alert>{error}</Alert>
      {done && (
        <Alert kind="ok">
          {done}{" "}
          <button type="button" className="link" onClick={onDone}>
            See the movements →
          </button>
        </Alert>
      )}
      <div className="card">
        <div className="card-title">What arrived</div>
        <ProductPicker
          onPick={(product) => {
            const variant = product.variants[0];
            if (!variant) return;
            setLines((all) =>
              all.some((l) => l.variantId === variant.id)
                ? all
                : [...all, { variantId: variant.id, name: product.name, quantity: "1", unitCost: variant.purchase_price ?? "" }],
            );
            setDone(null);
          }}
        />
        {lines.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Quantity</th>
                  <th className="num">Unit cost</th>
                  <th className="num">Line</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={line.variantId}>
                    <td>{line.name}</td>
                    <td className="num" style={{ width: 110 }}>
                      <input
                        inputMode="decimal"
                        value={line.quantity}
                        onChange={(e) => setLines((all) => all.map((l) => (l.variantId === line.variantId ? { ...l, quantity: e.target.value } : l)))}
                        style={{ textAlign: "right" }}
                      />
                    </td>
                    <td className="num" style={{ width: 130 }}>
                      <input
                        inputMode="decimal"
                        value={line.unitCost}
                        onChange={(e) => setLines((all) => all.map((l) => (l.variantId === line.variantId ? { ...l, unitCost: e.target.value } : l)))}
                        style={{ textAlign: "right" }}
                        required
                      />
                    </td>
                    <td className="num">{money(Number(line.quantity || 0) * Number(line.unitCost || 0), currency)}</td>
                    <td className="num">
                      <button type="button" className="link" onClick={() => setLines((all) => all.filter((l) => l.variantId !== line.variantId))}>
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

      {lines.length > 0 && (
        <div className="card">
          <div className="card-title">Supplier, costs and payment</div>
          <div className="grid">
            <Field label="Supplier" hint="optional">
              <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
                <option value="">Not recorded</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
                {can("supplier:manage") && <option value="__new__">+ New supplier…</option>}
              </select>
            </Field>
            {supplierId === "__new__" && (
              <Field label="New supplier name">
                <input value={newSupplier} onChange={(e) => setNewSupplier(e.target.value)} required />
              </Field>
            )}
            {locations.length > 1 && (
              <Field label="Received into">
                <select value={locationId} onChange={(e) => setLocationId(e.target.value)}>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="Supplier invoice" hint="optional">
              <input value={invoiceRef} onChange={(e) => setInvoiceRef(e.target.value)} />
            </Field>
            <Field label="Transport cost" hint="shared across the lines">
              <input value={transport} onChange={(e) => setTransport(e.target.value)} inputMode="decimal" />
            </Field>
            <Field label="Other costs" hint="loading, duty, …">
              <input value={other} onChange={(e) => setOther(e.target.value)} inputMode="decimal" />
            </Field>
            {(Number(transport) > 0 || Number(other) > 0) && lines.length > 1 && (
              <Field label="Share costs" hint="how transport and other costs are split">
                <select value={allocation} onChange={(e) => setAllocation(e.target.value)}>
                  <option value="by_value">In proportion to line value</option>
                  <option value="by_quantity">In proportion to quantity</option>
                </select>
              </Field>
            )}
            <Field label="Amount paid now" hint="leave it short to record supplier credit">
              <input value={amountPaid} onChange={(e) => setAmountPaid(e.target.value)} inputMode="decimal" />
            </Field>
            {Number(amountPaid) > 0 && (
              <Field label="Paid by">
                <select value={method} onChange={(e) => setMethod(e.target.value)}>
                  <option value="cash">Cash</option>
                  <option value="bank_transfer">Bank transfer</option>
                  <option value="telebirr">Telebirr</option>
                  <option value="cbe_birr">CBE Birr</option>
                  <option value="cheque">Cheque</option>
                </select>
              </Field>
            )}
            {balance > 0 && (
              <Field label="Payment due" hint="optional">
                <select value={duePreset} onChange={(e) => setDuePreset(e.target.value)}>
                  <option value="">No due date</option>
                  <option value="7_days">In 7 days</option>
                  <option value="15_days">In 15 days</option>
                  <option value="30_days">In 30 days</option>
                </select>
              </Field>
            )}
          </div>
          {can("pricing:manage") && (
            <label className="toggle">
              <input type="checkbox" checked={reprice} onChange={(e) => setReprice(e.target.checked)} />
              <span>
                Update selling prices from the new landed cost using the pricing rule
                <em className="hint"> — you will see the result on each product</em>
              </span>
            </label>
          )}
          <div className="grid" style={{ marginTop: 6 }}>
            <div className="stat">
              <div className="label">Goods</div>
              <div className="value">{money(goodsTotal, currency)}</div>
            </div>
            <div className="stat">
              <div className="label">Total landed</div>
              <div className="value">{money(total, currency)}</div>
            </div>
            <div className={balance > 0 ? "stat is-warn" : "stat"}>
              <div className="label">Owed to supplier</div>
              <div className="value">{money(balance, currency)}</div>
            </div>
          </div>
          <button type="submit" disabled={busy} style={{ marginTop: 10 }}>
            {busy ? "Receiving…" : "Receive stock"}
          </button>
        </div>
      )}
    </form>
  );
}

// --------------------------------------------------------------------------- //
// Adjustments (damage, loss, corrections)
// --------------------------------------------------------------------------- //

function Adjust({ onDone }: { onDone: () => void }) {
  const locations = useLocations();
  const [product, setProduct] = useState<Product | null>(null);
  const [locationId, setLocationId] = useState("");
  const [direction, setDirection] = useState<"remove" | "add">("remove");
  const [reason, setReason] = useState("damage");
  const [qty, setQty] = useState("1");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!locationId && locations.length > 0) setLocationId(locations[0].id);
  }, [locations, locationId]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!product) return;
    setBusy(true);
    setError(null);
    try {
      const signed = direction === "remove" ? `-${qty}` : qty;
      const movement = await api.adjustStock({
        variant_id: product.variants[0].id,
        location_id: locationId,
        quantity: signed,
        reason: direction === "add" ? "adjustment" : reason,
        note,
      });
      setDone(`Recorded. ${product.name} now ${quantity(movement.balance_after)} at this location.`);
      setProduct(null);
      setQty("1");
      setNote("");
    } catch (cause) {
      setError(describeError(cause, "Could not record the adjustment"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">Adjust stock</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        For damage, loss and corrections. Sales, receipts and transfers have their own screens so the
        ledger says why each unit moved. Every adjustment is audited.
      </p>
      <Alert>{error}</Alert>
      {done && (
        <Alert kind="ok">
          {done}{" "}
          <button type="button" className="link" onClick={onDone}>
            See the movements →
          </button>
        </Alert>
      )}
      {product ? (
        <p>
          <strong>{product.name}</strong>{" "}
          <button type="button" className="link" onClick={() => setProduct(null)}>
            change
          </button>
        </p>
      ) : (
        <ProductPicker
          onPick={(p) => {
            setProduct(p);
            setDone(null);
          }}
          label="Product"
        />
      )}
      <div className="grid">
        {locations.length > 1 && (
          <Field label="Location">
            <select value={locationId} onChange={(e) => setLocationId(e.target.value)}>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Direction">
          <select value={direction} onChange={(e) => setDirection(e.target.value as "remove" | "add")}>
            <option value="remove">Remove from stock</option>
            <option value="add">Add to stock (correction)</option>
          </select>
        </Field>
        {direction === "remove" && (
          <Field label="Reason">
            <select value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="damage">Damaged</option>
              <option value="loss">Lost or stolen</option>
              <option value="adjustment">Correction</option>
            </select>
          </Field>
        )}
        <Field label="Quantity">
          <input value={qty} onChange={(e) => setQty(e.target.value)} inputMode="decimal" required />
        </Field>
      </div>
      <Field label="Note" hint="required — say what happened">
        <input value={note} onChange={(e) => setNote(e.target.value)} minLength={3} required />
      </Field>
      <button type="submit" disabled={busy || !product}>
        {busy ? "Saving…" : "Record adjustment"}
      </button>
    </form>
  );
}

// --------------------------------------------------------------------------- //
// Transfers between branches (draft → dispatched → received)
// --------------------------------------------------------------------------- //

function Transfers() {
  const { can, canWrite } = useSession();
  const locations = useLocations();
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [products, setProducts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [receiving, setReceiving] = useState<Transfer | null>(null);

  const load = useCallback(async () => {
    try {
      const rows = await api.transfers();
      setTransfers(rows);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load transfers"));
    }
  }, []);

  useEffect(() => {
    void load();
    api.products({ limit: 200 }).then((page) => {
      const names: Record<string, string> = {};
      for (const p of page.items) for (const v of p.variants) names[v.id] = v.display_name ?? p.name;
      setProducts(names);
    }).catch(() => undefined);
  }, [load]);

  const locationName = (id: string) => locations.find((l) => l.id === id)?.name ?? "…";

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      setReceiving(null);
      await load();
    } catch (cause) {
      setError(describeError(cause, "Could not update the transfer"));
    }
  }

  return (
    <>
      <Alert>{error}</Alert>
      {canWrite && can("stock:transfer") && !creating && (
        <p>
          <button type="button" onClick={() => setCreating(true)}>
            New transfer
          </button>
        </p>
      )}
      {creating && (
        <NewTransfer
          locations={locations}
          onDone={() => {
            setCreating(false);
            void load();
          }}
        />
      )}
      {receiving && (
        <ReceiveTransfer
          transfer={receiving}
          names={products}
          onSubmit={(received) => act(() => api.receiveTransfer(receiving.id, received))}
          onCancel={() => setReceiving(null)}
        />
      )}
      <div className="card">
        <div className="card-title">Transfers</div>
        <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
          Stock leaves the source on dispatch and arrives on receipt. Anything received short is posted
          as a loss so every unit is accounted for.
        </p>
        {transfers.length === 0 ? (
          <Empty title="No transfers yet" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Reference</th>
                  <th>From → to</th>
                  <th>Lines</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {transfers.map((t) => (
                  <tr key={t.id}>
                    <td className="nowrap">{t.reference}</td>
                    <td>
                      {locationName(t.from_location_id)} → {locationName(t.to_location_id)}
                    </td>
                    <td>
                      {t.lines.map((line) => (
                        <div key={line.id} style={{ fontSize: "0.88rem" }}>
                          {products[line.variant_id] ?? "Product"} × {quantity(line.quantity_sent)}
                          {line.quantity_received !== null && line.quantity_received !== line.quantity_sent && (
                            <span className="badge warn" style={{ marginLeft: 6 }}>
                              received {quantity(line.quantity_received)}
                            </span>
                          )}
                        </div>
                      ))}
                    </td>
                    <td className="nowrap">
                      <Badge status={t.status} />
                    </td>
                    <td className="num nowrap">
                      {canWrite && can("stock:transfer") && t.status === "draft" && (
                        <button type="button" className="link" onClick={() => act(() => api.dispatchTransfer(t.id))}>
                          Dispatch
                        </button>
                      )}
                      {canWrite && can("stock:transfer") && t.status === "dispatched" && (
                        <button type="button" className="link" onClick={() => setReceiving(t)}>
                          Receive
                        </button>
                      )}
                    </td>
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

function NewTransfer({ locations, onDone }: { locations: StockLocation[]; onDone: () => void }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [lines, setLines] = useState<Array<{ variantId: string; name: string; quantity: string }>>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (locations.length > 1) {
      setFrom((f) => f || locations[0].id);
      setTo((t) => t || locations[1].id);
    }
  }, [locations]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createTransfer({
        from_location_id: from,
        to_location_id: to,
        lines: lines.map((l) => ({ variant_id: l.variantId, quantity: l.quantity })),
        note: note || undefined,
      });
      onDone();
    } catch (cause) {
      setError(describeError(cause, "Could not create the transfer"));
    } finally {
      setBusy(false);
    }
  }

  if (locations.length < 2) {
    return (
      <div className="card">
        <Alert kind="warn">A transfer needs two locations. Add a branch under Settings first.</Alert>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">New transfer</div>
      <Alert>{error}</Alert>
      <div className="grid">
        <Field label="From">
          <select value={from} onChange={(e) => setFrom(e.target.value)}>
            {locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="To">
          <select value={to} onChange={(e) => setTo(e.target.value)}>
            {locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ProductPicker
        onPick={(p) => {
          const v = p.variants[0];
          if (v && !lines.some((l) => l.variantId === v.id)) setLines((all) => [...all, { variantId: v.id, name: p.name, quantity: "1" }]);
        }}
      />
      {lines.map((line) => (
        <div key={line.variantId} className="row" style={{ marginBottom: 8 }}>
          <span style={{ flex: 1 }}>{line.name}</span>
          <input
            style={{ width: 100, textAlign: "right" }}
            inputMode="decimal"
            value={line.quantity}
            onChange={(e) => setLines((all) => all.map((l) => (l.variantId === line.variantId ? { ...l, quantity: e.target.value } : l)))}
          />
          <button type="button" className="link" onClick={() => setLines((all) => all.filter((l) => l.variantId !== line.variantId))}>
            Remove
          </button>
        </div>
      ))}
      <Field label="Note" hint="optional">
        <input value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy || lines.length === 0 || from === to}>
          {busy ? "Saving…" : "Save as draft"}
        </button>
        <button type="button" className="secondary" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ReceiveTransfer({
  transfer,
  names,
  onSubmit,
  onCancel,
}: {
  transfer: Transfer;
  names: Record<string, string>;
  onSubmit: (received: Record<string, string>) => Promise<void>;
  onCancel: () => void;
}) {
  const [received, setReceived] = useState<Record<string, string>>(
    Object.fromEntries(transfer.lines.map((l) => [l.id, l.quantity_sent])),
  );
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        void onSubmit(received).finally(() => setBusy(false));
      }}
    >
      <div className="card-title">Receive {transfer.reference}</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Enter what actually arrived. Less than was sent is recorded as a loss in transit.
      </p>
      {transfer.lines.map((line) => (
        <div key={line.id} className="row" style={{ marginBottom: 8 }}>
          <span style={{ flex: 1 }}>
            {names[line.variant_id] ?? "Product"} <span className="muted">(sent {quantity(line.quantity_sent)})</span>
          </span>
          <input
            style={{ width: 110, textAlign: "right" }}
            inputMode="decimal"
            value={received[line.id]}
            onChange={(e) => setReceived((all) => ({ ...all, [line.id]: e.target.value }))}
          />
        </div>
      ))}
      <div className="row">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Confirm receipt"}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// --------------------------------------------------------------------------- //
// The ledger
// --------------------------------------------------------------------------- //

function Movements() {
  const [rows, setRows] = useState<Movement[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .movements({ limit: 100 })
      .then((page) => setRows(page.items))
      .catch((cause) => setError(describeError(cause, "Could not load the ledger")));
    api.products({ limit: 200 }).then((page) => {
      const map: Record<string, string> = {};
      for (const p of page.items) for (const v of p.variants) map[v.id] = v.display_name ?? p.name;
      setNames(map);
    }).catch(() => undefined);
  }, []);

  return (
    <div className="card">
      <div className="card-title">Recent movements</div>
      <Alert>{error}</Alert>
      {rows.length === 0 ? (
        <Empty title="Nothing has moved yet" />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Product</th>
                <th>Reason</th>
                <th className="num">Change</th>
                <th className="num">After</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id}>
                  <td className="muted nowrap">{dateTime(m.occurred_at)}</td>
                  <td>
                    {names[m.variant_id] ?? "Product"}
                    {m.note && <div className="muted" style={{ fontSize: "0.8rem" }}>{m.note}</div>}
                  </td>
                  <td className="nowrap">
                    <Badge status={m.reason} />
                  </td>
                  <td className="num">
                    {Number(m.quantity) > 0 ? "+" : ""}
                    {quantity(m.quantity)}
                  </td>
                  <td className="num muted">{quantity(m.balance_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
