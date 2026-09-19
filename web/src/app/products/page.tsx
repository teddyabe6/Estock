"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Empty, Field, PageHead } from "@/components/ui";
import { api, type Product } from "@/lib/api";
import { money, quantity } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function ProductsPage() {
  return (
    <AppShell>
      <Products />
    </AppShell>
  );
}

function Products() {
  const { session, can } = useSession();
  const [items, setItems] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);

  const load = useCallback(
    async (q: string) => {
      setLoading(true);
      try {
        const page = await api.products({ q: q || undefined, limit: 100 });
        setItems(page.items);
        setTotal(page.total);
        setError(null);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not load products");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    // Debounce so typing does not fire a request per keystroke.
    const timer = setTimeout(() => void load(search), 250);
    return () => clearTimeout(timer);
  }, [search, load]);

  const currency = session?.currency ?? "ETB";
  const showCost = can("cost:view");

  return (
    <>
      <PageHead
        title="Products"
        subtitle={loading ? "Loading…" : `${total} product${total === 1 ? "" : "s"}`}
        actions={
          can("product:manage") ? (
            <button type="button" onClick={() => setAdding((value) => !value)}>
              {adding ? "Cancel" : "Add product"}
            </button>
          ) : null
        }
      />

      <Alert>{error}</Alert>

      {adding && (
        <AddProduct
          onDone={() => {
            setAdding(false);
            void load(search);
          }}
        />
      )}

      <div className="card">
        <Field label="Search" hint="name, SKU or barcode">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Start typing…"
          />
        </Field>

        {items.length === 0 && !loading ? (
          <Empty title="No products yet">
            <p>Add your first product, or import a spreadsheet.</p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Category</th>
                  <th className="num">Price</th>
                  {showCost && <th className="num">Cost</th>}
                  <th className="num">On hand</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((product) => {
                  const variant = product.variants[0];
                  return (
                    <tr key={product.id}>
                      <td>
                        {product.name}
                        {product.is_published && (
                          <>
                            {" "}
                            <span className="badge ok">online</span>
                          </>
                        )}
                      </td>
                      <td className="muted">{product.category_name ?? "—"}</td>
                      <td className="num">{money(variant?.selling_price, currency)}</td>
                      {showCost && (
                        <td className="num">
                          {money(variant?.average_cost ?? variant?.landed_cost, currency)}
                        </td>
                      )}
                      <td className="num">
                        {product.track_stock ? quantity(product.quantity_on_hand) : "—"}
                      </td>
                      <td>
                        {product.stock_status ? (
                          <Badge status={product.stock_status} />
                        ) : (
                          <span className="muted">not stocked</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

/**
 * Quick add: a name is all that is required. Cost, price and opening stock are
 * offered because they are the usual next questions, but stay optional (PRD A1).
 */
function AddProduct({ onDone }: { onDone: () => void }) {
  const { can } = useSession();
  const [form, setForm] = useState({
    name: "",
    selling_price: "",
    purchase_price: "",
    opening_stock: "",
    category_name: "",
    barcode: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function update(key: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((prev) => ({ ...prev, [key]: event.target.value }));
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createProduct({
        name: form.name,
        selling_price: form.selling_price || undefined,
        purchase_price: form.purchase_price || undefined,
        opening_stock: form.opening_stock || undefined,
        category_name: form.category_name || undefined,
        barcode: form.barcode || undefined,
      });
      onDone();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the product");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">Add a product</div>
      <Alert>{error}</Alert>
      <form onSubmit={onSubmit}>
        <Field label="Product name">
          <input value={form.name} onChange={update("name")} required autoFocus />
        </Field>
        <div className="grid">
          <Field label="Selling price" hint="optional">
            <input
              value={form.selling_price}
              onChange={update("selling_price")}
              inputMode="decimal"
            />
          </Field>
          {can("cost:view") && (
            <Field label="Purchase price" hint="optional">
              <input
                value={form.purchase_price}
                onChange={update("purchase_price")}
                inputMode="decimal"
              />
            </Field>
          )}
          <Field label="Quantity in stock" hint="optional">
            <input
              value={form.opening_stock}
              onChange={update("opening_stock")}
              inputMode="decimal"
            />
          </Field>
          <Field label="Category" hint="optional">
            <input value={form.category_name} onChange={update("category_name")} />
          </Field>
          <Field label="Barcode" hint="optional">
            <input value={form.barcode} onChange={update("barcode")} />
          </Field>
        </div>
        <button type="submit" disabled={busy || !form.name.trim()}>
          {busy ? "Saving…" : "Save product"}
        </button>
      </form>
    </div>
  );
}
