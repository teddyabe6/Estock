"use client";

/**
 * The catalogue: quick add, edit, publish online, and the spreadsheet import
 * (upload → map → preview → confirm) from PRD 8.
 */

import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  Alert,
  Badge,
  Drawer,
  Empty,
  Field,
  FilterBar,
  GroupRow,
  PageHead,
  Pager,
  Picker,
  SortableHead,
  Toggle,
  nextOrder,
  ordering,
} from "@/components/ui";
import {
  api,
  type Category,
  type ImportPreview,
  type ImportUpload,
  type Product,
  type ProductSort,
} from "@/lib/api";
import { money, quantity } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

const PAGE = 50;

/**
 * An order as one choice rather than a column and a direction to assemble.
 * By category is an order too: ask for it that way and a category's
 * products arrive together, which is all grouping is.
 */
const ORDERS = [
  { value: "name", label: "Name A–Z", sort: "name", direction: "asc" },
  { value: "name-down", label: "Name Z–A", sort: "name", direction: "desc" },
  { value: "dearest", label: "Dearest first", sort: "price", direction: "desc" },
  { value: "cheapest", label: "Cheapest first", sort: "price", direction: "asc" },
  { value: "most", label: "Most on hand", sort: "stock", direction: "desc" },
  { value: "fewest", label: "Fewest on hand", sort: "stock", direction: "asc" },
  { value: "category", label: "By category", sort: "category", direction: "asc" },
] as const satisfies ReadonlyArray<{
  value: string;
  label: string;
  sort: ProductSort;
  direction: "asc" | "desc";
}>;

/** Whether a product is on the shop's own storefront. */
const ONLINE = [
  { value: "", label: "On and off the shop" },
  { value: "yes", label: "On the shop" },
  { value: "no", label: "Not on the shop" },
] as const;

export default function ProductsPage() {
  return (
    <AppShell>
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <Products />
      </Suspense>
    </AppShell>
  );
}

function Products() {
  const { session, can, canWrite } = useSession();
  const params = useSearchParams();
  const [items, setItems] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState(() => params.get("q") ?? "");
  const [categoryId, setCategoryId] = useState("");
  const [online, setOnline] = useState("");
  const [archived, setArchived] = useState(false);
  const [order, setOrder] = useState("name");
  const [offset, setOffset] = useState(0);
  const [categories, setCategories] = useState<Category[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(params.get("add") === "1");
  const [importing, setImporting] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);

  const chosen = ordering(ORDERS, order);

  useEffect(() => {
    api
      .categories()
      .then((all) => setCategories(all.filter((c) => c.is_active)))
      .catch(() => setCategories([]));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await api.products({
        q: search || undefined,
        category_id: categoryId || undefined,
        published: online === "" ? undefined : online === "yes",
        include_inactive: archived || undefined,
        sort: chosen.sort,
        direction: chosen.direction,
        limit: PAGE,
        offset,
      });
      setItems(page.items);
      setTotal(page.total);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load products"));
    } finally {
      setLoading(false);
    }
  }, [search, categoryId, online, archived, chosen.sort, chosen.direction, offset]);

  useEffect(() => {
    // Debounce so typing does not fire a request per keystroke.
    const timer = setTimeout(() => void load(), 250);
    return () => clearTimeout(timer);
  }, [load]);

  // Narrowing the list invalidates where you were in it.
  useEffect(() => {
    setOffset(0);
  }, [search, categoryId, online, archived, order]);

  const headSort = (by: ProductSort) => setOrder(nextOrder(ORDERS, chosen, by).value);

  const currency = session?.currency ?? "ETB";
  const showCost = can("cost:view");
  const manage = canWrite && can("product:manage");
  const narrowed = Boolean(search || categoryId || online || archived);

  async function togglePublish(product: Product) {
    try {
      const updated = await api.publishProduct(product.id, !product.is_published);
      setItems((all) => all.map((p) => (p.id === product.id ? updated : p)));
    } catch (cause) {
      setError(describeError(cause, "Could not change online availability"));
    }
  }

  return (
    <>
      <PageHead
        title="Products"
        subtitle={loading ? "Loading…" : `${total} product${total === 1 ? "" : "s"}`}
        actions={
          manage ? (
            <>
              {can("product:import") && (
                <button type="button" className="secondary" onClick={() => setImporting((v) => !v)}>
                  {importing ? "Close import" : "Import spreadsheet"}
                </button>
              )}
              <button type="button" onClick={() => setAdding((value) => !value)}>
                {adding ? "Cancel" : "Add product"}
              </button>
            </>
          ) : null
        }
      />

      <Alert>{error}</Alert>

      {adding && (
        <AddProduct
          onDone={() => {
            setAdding(false);
            void load();
          }}
        />
      )}

      {importing && (
        <ImportWizard
          onDone={() => {
            setImporting(false);
            void load();
          }}
        />
      )}

      <div className="card">
        <FilterBar
          active={
            [categoryId, online, archived ? "archived" : "", order === "name" ? "" : order]
              .filter(Boolean).length
          }
          primary={
            <label className="field filter wide">
              <span>
                Search <em className="hint">name, SKU or barcode</em>
              </span>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Start typing…"
              />
            </label>
          }
        >
          {categories.length > 0 && (
            <Picker
              label="Category"
              value={categoryId}
              onChange={setCategoryId}
              options={[
                { value: "", label: "Every category" },
                ...categories.map((c) => ({ value: c.id, label: c.name })),
              ]}
            />
          )}
          {can("shop:view") && (
            <Picker label="Online" value={online} onChange={setOnline} options={ONLINE} />
          )}
          <Picker
            label="Shown"
            value={archived ? "all" : "selling"}
            onChange={(value) => setArchived(value === "all")}
            options={[
              { value: "selling", label: "Still selling" },
              { value: "all", label: "Including archived" },
            ]}
          />
          <Picker label="Order" value={order} onChange={setOrder} options={ORDERS} />
        </FilterBar>

        {items.length === 0 && !loading ? (
          <Empty title={narrowed ? "Nothing matches that" : "No products yet"}>
            <p>
              {narrowed
                ? "Widen the filters, or clear the search."
                : "Add your first product, or import a spreadsheet."}
            </p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <SortableHead
                    label="Name"
                    by="name"
                    sort={chosen.sort}
                    direction={chosen.direction}
                    onSort={headSort}
                  />
                  <SortableHead
                    label="Category"
                    by="category"
                    sort={chosen.sort}
                    direction={chosen.direction}
                    onSort={headSort}
                  />
                  <SortableHead
                    label="Price"
                    by="price"
                    className="num"
                    sort={chosen.sort}
                    direction={chosen.direction}
                    onSort={headSort}
                  />
                  {showCost && <th className="num">Cost</th>}
                  <SortableHead
                    label="On hand"
                    by="stock"
                    className="num"
                    sort={chosen.sort}
                    direction={chosen.direction}
                    onSort={headSort}
                  />
                  <th>Status</th>
                  {(manage || can("shop:manage")) && <th />}
                </tr>
              </thead>
              <tbody>
                {items.map((product, index) => {
                  const variant = product.variants[0];
                  const heading =
                    chosen.sort === "category" &&
                    (index === 0 ||
                      items[index - 1].category_name !== product.category_name)
                      ? (product.category_name ?? "No category")
                      : null;
                  return (
                    <Fragment key={product.id}>
                      {heading && (
                        <GroupRow
                          label={heading}
                          span={5 + (showCost ? 1 : 0) + (manage || can("shop:manage") ? 1 : 0)}
                        />
                      )}
                      <tr>
                      <td>
                        {manage ? (
                          <button type="button" className="link" onClick={() => setEditing(product)}>
                            {product.name}
                          </button>
                        ) : (
                          product.name
                        )}
                        {product.is_published && (
                          <>
                            {" "}
                            <span className="badge ok">online</span>
                          </>
                        )}
                        {/* Only worth saying once the archived ones are
                            being shown; until then every row is selling. */}
                        {archived && product.is_active === false && (
                          <>
                            {" "}
                            <span className="badge">archived</span>
                          </>
                        )}
                        {product.sku && (
                          <div className="muted" style={{ fontSize: "0.8rem" }}>
                            {product.sku}
                          </div>
                        )}
                      </td>
                      {/* Under its own heading the category would be the
                          same word on every row of the group. */}
                      <td className="muted">
                        {chosen.sort === "category" ? "" : (product.category_name ?? "—")}
                      </td>
                      <td className="num">{money(variant?.selling_price, currency)}</td>
                      {showCost && (
                        <td className="num">{money(variant?.average_cost ?? variant?.landed_cost, currency)}</td>
                      )}
                      <td className="num">{product.track_stock ? quantity(product.quantity_on_hand) : "—"}</td>
                      <td>
                        {product.stock_status ? (
                          <Badge status={product.stock_status} />
                        ) : (
                          <span className="muted">not stocked</span>
                        )}
                      </td>
                      {(manage || can("shop:manage")) && (
                        <td className="num nowrap">
                          {canWrite && can("shop:manage") && (
                            <button type="button" className="link" onClick={() => void togglePublish(product)}>
                              {product.is_published ? "Take offline" : "Publish online"}
                            </button>
                          )}
                        </td>
                      )}
                      </tr>
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <Pager
          total={total}
          limit={PAGE}
          offset={offset}
          onOffset={setOffset}
          noun="products"
        />
      </div>

      {editing && (
        <EditProduct
          product={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
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
    sku: "",
    unit_of_measure: "pcs",
  });
  const [more, setMore] = useState(false);
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
        sku: form.sku || undefined,
        unit_of_measure: form.unit_of_measure || "pcs",
      });
      onDone();
    } catch (cause) {
      setError(describeError(cause, "Could not save the product"));
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
            <input value={form.selling_price} onChange={update("selling_price")} inputMode="decimal" />
          </Field>
          {can("cost:view") && (
            <Field label="Purchase price" hint="optional">
              <input value={form.purchase_price} onChange={update("purchase_price")} inputMode="decimal" />
            </Field>
          )}
          <Field label="Quantity in stock" hint="optional">
            <input value={form.opening_stock} onChange={update("opening_stock")} inputMode="decimal" />
          </Field>
          <Field label="Category" hint="optional">
            <input value={form.category_name} onChange={update("category_name")} />
          </Field>
        </div>
        {more ? (
          <div className="grid">
            <Field label="Barcode" hint="optional">
              <input value={form.barcode} onChange={update("barcode")} />
            </Field>
            <Field label="SKU / code" hint="optional">
              <input value={form.sku} onChange={update("sku")} />
            </Field>
            <Field label="Unit" hint="pcs, kg, bag, …">
              <input value={form.unit_of_measure} onChange={update("unit_of_measure")} />
            </Field>
          </div>
        ) : (
          <p>
            <button type="button" className="link" onClick={() => setMore(true)}>
              More details (barcode, code, unit)
            </button>
          </p>
        )}
        <button type="submit" disabled={busy || !form.name.trim()}>
          {busy ? "Saving…" : "Save product"}
        </button>
      </form>
    </div>
  );
}

/** Everything that was optional at creation can be completed here (PRD 8.1). */
function EditProduct({
  product,
  onClose,
  onSaved,
}: {
  product: Product;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { session, can, canWrite } = useSession();
  const currency = session?.currency ?? "ETB";
  const variant = product.variants[0];
  const [form, setForm] = useState({
    name: product.name,
    category_name: product.category_name ?? "",
    sku: product.sku ?? "",
    barcode: variant?.barcode ?? "",
    unit_of_measure: product.unit_of_measure,
    description: product.description ?? "",
    selling_price: variant?.selling_price ?? "",
    purchase_price: variant?.purchase_price ?? "",
    transport_cost: variant?.transport_cost ?? "",
    other_costs: variant?.other_costs ?? "",
    min_stock: variant?.min_stock ?? "",
    reorder_level: variant?.reorder_level ?? "",
    tax_rate: variant?.tax_rate ?? "",
    track_stock: product.track_stock,
    is_active: product.is_active ?? true,
  });
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [image, setImage] = useState<string | null>(product.image_url ?? null);
  const [imageBusy, setImageBusy] = useState(false);

  async function changeImage(file: File | null) {
    if (!file) return;
    setImageBusy(true);
    setError(null);
    try {
      const updated = await api.uploadProductImage(product.id, file);
      setImage(updated.image_url ?? null);
    } catch (cause) {
      setError(describeError(cause, "Could not upload the photo"));
    } finally {
      setImageBusy(false);
    }
  }

  async function removeImage() {
    setImageBusy(true);
    setError(null);
    try {
      await api.deleteProductImage(product.id);
      setImage(null);
    } catch (cause) {
      setError(describeError(cause, "Could not remove the photo"));
    } finally {
      setImageBusy(false);
    }
  }

  function update(key: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [key]: event.target.value }));
  }

  const cost = Number(form.purchase_price || 0) + Number(form.transport_cost || 0) + Number(form.other_costs || 0);

  async function suggest() {
    try {
      const result = await api.suggestPrice(String(cost), variant?.id);
      setSuggestion(`${money(result.suggested_price, currency)} — ${result.explanation}`);
      setForm((prev) => ({ ...prev, selling_price: result.suggested_price }));
    } catch (cause) {
      setError(describeError(cause, "No pricing rule is set yet"));
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.updateProduct(product.id, {
        name: form.name,
        category_name: form.category_name || null,
        sku: form.sku || null,
        barcode: form.barcode,
        unit_of_measure: form.unit_of_measure || "pcs",
        description: form.description || null,
        track_stock: form.track_stock,
        is_active: form.is_active,
      });
      if (variant) {
        const body: Record<string, unknown> = {
          selling_price: form.selling_price || null,
          min_stock: form.min_stock || null,
          reorder_level: form.reorder_level || null,
          tax_rate: form.tax_rate || null,
        };
        if (can("cost:view")) {
          body.purchase_price = form.purchase_price || null;
          body.transport_cost = form.transport_cost || null;
          body.other_costs = form.other_costs || null;
        }
        await api.updateVariant(variant.id, body);
      }
      onSaved();
    } catch (cause) {
      setError(describeError(cause, "Could not save the product"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer title={product.name} onClose={onClose}>
      <Alert>{error}</Alert>
      <form onSubmit={save}>
        <Field label="Product name">
          <input value={form.name} onChange={update("name")} required />
        </Field>
        <div className="grid">
          <Field label="Category">
            <input value={form.category_name} onChange={update("category_name")} />
          </Field>
          <Field label="Unit">
            <input value={form.unit_of_measure} onChange={update("unit_of_measure")} />
          </Field>
          <Field label="SKU / code">
            <input value={form.sku} onChange={update("sku")} />
          </Field>
          <Field label="Barcode">
            <input value={form.barcode} onChange={update("barcode")} />
          </Field>
        </div>
        <Field label="Description" hint="shown in the online shop">
          <textarea rows={2} value={form.description} onChange={update("description")} />
        </Field>

        <div className="card">
          <div className="card-title">Photo</div>
          <div className="row" style={{ alignItems: "flex-start" }}>
            <div className="thumb small" style={{ width: 88, height: 88 }}>
              {image ? (
                // eslint-disable-next-line @next/next/no-img-element -- served by the API
                <img src={image} alt={product.name} />
              ) : (
                <span className="initial">{product.name.charAt(0).toUpperCase()}</span>
              )}
            </div>
            <div style={{ flex: 1, minWidth: 200 }}>
              <p className="muted" style={{ margin: "0 0 8px", fontSize: "0.85rem" }}>
                Shown on the product card and page in your online shop. JPEG, PNG or WebP.
              </p>
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                disabled={imageBusy || !canWrite}
                onChange={(e) => void changeImage(e.target.files?.[0] ?? null)}
              />
              {image && (
                <p style={{ margin: "8px 0 0" }}>
                  <button type="button" className="link" disabled={imageBusy} onClick={() => void removeImage()}>
                    Remove photo
                  </button>
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-title">Pricing</div>
          <div className="grid">
            {can("cost:view") && (
              <>
                <Field label="Purchase price">
                  <input value={form.purchase_price} onChange={update("purchase_price")} inputMode="decimal" />
                </Field>
                <Field label="Transport per unit">
                  <input value={form.transport_cost} onChange={update("transport_cost")} inputMode="decimal" />
                </Field>
                <Field label="Other costs per unit">
                  <input value={form.other_costs} onChange={update("other_costs")} inputMode="decimal" />
                </Field>
              </>
            )}
            <Field label="Selling price">
              <input value={form.selling_price} onChange={update("selling_price")} inputMode="decimal" />
            </Field>
            <Field label="Tax rate" hint="0.15 for 15%; blank uses the business default">
              <input value={form.tax_rate} onChange={update("tax_rate")} inputMode="decimal" />
            </Field>
          </div>
          {can("cost:view") && cost > 0 && (
            <p style={{ marginTop: 0 }}>
              <button type="button" className="link" onClick={() => void suggest()}>
                Suggest a price from the landed cost of {money(cost, currency)}
              </button>
              {suggestion && <span className="muted"> · {suggestion}</span>}
            </p>
          )}
          {variant?.average_cost && can("cost:view") && (
            <p className="muted" style={{ fontSize: "0.85rem", margin: 0 }}>
              Average cost from receipts: {money(variant.average_cost, currency)} — this is what profit
              reports use.
            </p>
          )}
        </div>

        <div className="card">
          <div className="card-title">Stock control</div>
          <Toggle
            label="Track stock for this product"
            hint="turn off for services"
            checked={form.track_stock}
            onChange={(checked) => setForm((prev) => ({ ...prev, track_stock: checked }))}
          />
          <div className="grid">
            <Field label="Minimum stock" hint="critical below this">
              <input value={form.min_stock} onChange={update("min_stock")} inputMode="decimal" />
            </Field>
            <Field label="Reorder level" hint="warning below this">
              <input value={form.reorder_level} onChange={update("reorder_level")} inputMode="decimal" />
            </Field>
          </div>
          <Toggle
            label="Active"
            hint="an inactive product cannot be sold but keeps its history"
            checked={form.is_active}
            onChange={(checked) => setForm((prev) => ({ ...prev, is_active: checked }))}
          />
        </div>

        <div className="row">
          <button type="submit" disabled={busy || !canWrite}>
            {busy ? "Saving…" : "Save changes"}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Drawer>
  );
}

/** Upload → map columns → preview → confirm, with a result summary (PRD 8.3). */
function ImportWizard({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<ImportUpload | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [skipErrors, setSkipErrors] = useState(true);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function uploadFile() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const uploaded = await api.importUpload(file);
      setUploadResult(uploaded);
      setMapping(uploaded.suggested_mapping);
      setPreview(null);
    } catch (cause) {
      setError(describeError(cause, "Could not read the file"));
    } finally {
      setBusy(false);
    }
  }

  async function validate() {
    if (!uploadResult) return;
    setBusy(true);
    setError(null);
    try {
      const cleaned = Object.fromEntries(Object.entries(mapping).filter(([, v]) => v));
      setPreview(await api.importValidate(uploadResult.job_id, cleaned));
    } catch (cause) {
      setError(describeError(cause, "Could not check the file"));
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!uploadResult) return;
    setBusy(true);
    setError(null);
    try {
      const done = await api.importCommit(uploadResult.job_id, skipErrors);
      setResult(
        `Imported ${done.created_products} product(s)` +
          (done.skipped_rows ? `, skipped ${done.skipped_rows} row(s) with problems` : "") +
          ".",
      );
    } catch (cause) {
      setError(describeError(cause, "Could not import"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">Import products from a spreadsheet</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Excel (.xlsx) or CSV, up to 5,000 rows. Nothing is written until every row has been checked.{" "}
        <button type="button" className="link" onClick={() => api.importTemplate().catch((c) => setError(describeError(c)))}>
          Download the template
        </button>
      </p>
      <Alert>{error}</Alert>

      {result ? (
        <>
          <Alert kind="ok">{result}</Alert>
          <button type="button" onClick={onDone}>
            Done
          </button>
        </>
      ) : !uploadResult ? (
        <div className="row">
          <input
            type="file"
            accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            style={{ width: "auto" }}
          />
          <button type="button" disabled={!file || busy} onClick={() => void uploadFile()}>
            {busy ? "Reading…" : "Upload"}
          </button>
        </div>
      ) : (
        <>
          <p className="muted" style={{ fontSize: "0.9rem" }}>
            {uploadResult.filename}: {uploadResult.total_rows} row(s). Match each column to a field; a product
            name is required.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Column in your file</th>
                  <th>Becomes</th>
                </tr>
              </thead>
              <tbody>
                {uploadResult.detected_headers.filter(Boolean).map((header) => (
                  <tr key={header}>
                    <td>{header}</td>
                    <td>
                      <select
                        value={mapping[header] ?? ""}
                        onChange={(e) => setMapping((m) => ({ ...m, [header]: e.target.value }))}
                      >
                        <option value="">— ignore —</option>
                        {uploadResult.available_fields.map((field) => (
                          <option key={field.field} value={field.field}>
                            {field.label}
                            {field.required ? " (required)" : ""}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" disabled={busy} onClick={() => void validate()}>
              {busy ? "Checking…" : "Check the rows"}
            </button>
            <button type="button" className="secondary" onClick={() => setUploadResult(null)}>
              Choose another file
            </button>
          </div>

          {preview && (
            <div style={{ marginTop: 14 }}>
              <div className="grid">
                <div className="stat">
                  <div className="label">Rows</div>
                  <div className="value">{preview.total_rows}</div>
                </div>
                <div className="stat">
                  <div className="label">Ready</div>
                  <div className="value">{preview.valid_rows}</div>
                </div>
                <div className={preview.error_rows ? "stat is-warn" : "stat"}>
                  <div className="label">Need attention</div>
                  <div className="value">{preview.error_rows}</div>
                </div>
              </div>
              {preview.issues.length > 0 && (
                <div className="table-wrap" style={{ marginTop: 10 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Row</th>
                        <th>Column</th>
                        <th>Problem</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.issues.slice(0, 50).map((issue, index) => (
                        <tr key={`${issue.row_number}-${issue.code}-${index}`}>
                          <td className="num">{issue.row_number}</td>
                          <td className="muted">{issue.column ?? "—"}</td>
                          <td>{issue.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {preview.sample.length > 0 && (
                <p className="muted" style={{ fontSize: "0.85rem" }}>
                  First rows: {preview.sample.slice(0, 3).map((row) => row.name).join(", ")}
                  {preview.sample.length > 3 ? ", …" : ""}
                </p>
              )}
              {preview.error_rows > 0 && (
                <Toggle
                  label="Skip the rows with problems and import the rest"
                  hint="or fix the file and upload it again"
                  checked={skipErrors}
                  onChange={setSkipErrors}
                />
              )}
              <button
                type="button"
                disabled={busy || preview.valid_rows === 0 || (preview.error_rows > 0 && !skipErrors)}
                onClick={() => void commit()}
              >
                {busy ? "Importing…" : `Import ${preview.valid_rows} product(s)`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
