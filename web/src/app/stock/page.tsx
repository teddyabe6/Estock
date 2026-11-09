"use client";

/**
 * Stock: what is on hand, receiving from suppliers (with supplier credit),
 * adjustments, transfers between branches and the movement ledger (PRD 9,
 * 11.2, A3). Every change here is a traceable movement with a reason.
 */

import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  Alert,
  Badge,
  Empty,
  Field,
  FilterBar,
  GroupRow,
  PageHead,
  Pager,
  Pick,
  PickList,
  Picker,
  SortableHead,
  Tabs,
} from "@/components/ui";
import {
  api,
  type BranchStockSetup,
  type Category,
  type OpeningSheet,
  type Movement,
  type OverviewSort,
  type Page,
  type Product,
  type StockLevel,
  type StockLocation,
  type StockOverview,
  type StockSort,
  type Supplier,
  type Transfer,
  type TransferBranch,
} from "@/lib/api";
import { dateTime, money, quantity } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

const TABS = [
  "overview",
  "levels",
  "opening",
  "receive",
  "adjust",
  "transfers",
  "movements",
] as const;

type Tab = (typeof TABS)[number];

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
  const { can, canWrite, session } = useSession();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(() => {
    // Any tab may be linked to, so a notification or a bookmark can point at
    // the ledger as readily as at the list.
    const asked = params.get("tab") as Tab | null;
    return asked && TABS.includes(asked) ? asked : "levels";
  });
  const [error, setError] = useState<string | null>(null);
  // null until the first answer comes back: "no branch needs counting" and
  // "we have not asked yet" are different things, and the guide must not open
  // on the wrong branch while it waits.
  const [awaiting, setAwaiting] = useState<BranchStockSetup[] | null>(null);
  // The cross-branch matrix only says anything when there is more than one
  // branch to compare, so a single-shop business never sees the tab.
  const manyBranches = (session?.branches.length ?? 0) > 1;
  const mayCount = canWrite && can("stock:adjust");

  const loadAwaiting = useCallback(() => {
    if (!can("stock:view")) {
      setAwaiting([]);
      return;
    }
    api.stockSetup().then(setAwaiting).catch(() => setAwaiting([]));
  }, [can]);

  useEffect(() => loadAwaiting(), [loadAwaiting]);

  const tabs = useMemo(
    () =>
      [
        { value: "overview" as const, label: "All branches", show: manyBranches },
        { value: "levels" as const, label: "On hand", show: true },
        // Offered while there is a branch to count, and whenever somebody has
        // followed a link here, so the guide is never a dead end.
        {
          value: "opening" as const,
          label: "Opening stock",
          show: mayCount && ((awaiting?.length ?? 0) > 0 || tab === "opening"),
        },
        { value: "receive" as const, label: "Receive stock", show: canWrite && can("stock:receive") && can("purchase:create") },
        { value: "adjust" as const, label: "Adjust", show: canWrite && can("stock:adjust") },
        { value: "transfers" as const, label: "Transfers", show: can("stock:transfer") },
        { value: "movements" as const, label: "History", show: true },
      ].filter((t) => t.show),
    [can, canWrite, manyBranches, mayCount, awaiting, tab],
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
      {mayCount && tab !== "opening" && awaiting && awaiting.length > 0 && (
        <div className="alert warn" role="status" style={{ marginBottom: 12 }}>
          <strong>
            {awaiting.length === 1
              ? `${awaiting[0].branch_name} has no stock recorded yet.`
              : `${awaiting.length} branches have no stock recorded yet.`}
          </strong>{" "}
          The products are already there — the quantities are not.{" "}
          <button type="button" className="link" onClick={() => setTab("opening")}>
            Record what is on the shelves
          </button>
        </div>
      )}
      <Tabs value={tab} options={tabs} onChange={setTab} />
      {tab === "overview" && <Overview />}
      {tab === "levels" && <Levels initialLow={params.get("view") === "low"} />}
      {tab === "opening" &&
        (awaiting === null ? (
          <p className="muted">Loading…</p>
        ) : (
          <Opening
            awaiting={awaiting}
            initialBranch={params.get("branch")}
            onRecorded={loadAwaiting}
          />
        ))}
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

/**
 * The shop's categories, for the filter and the headings.
 *
 * Fetched once per view that needs it and left empty on failure, because a
 * filter nobody can fill is worth hiding, not worth an error.
 */
function useCategories() {
  const [categories, setCategories] = useState<Category[]>([]);
  useEffect(() => {
    api
      .categories()
      .then((all) => setCategories(all.filter((c) => c.is_active)))
      .catch(() => setCategories([]));
  }, []);
  return categories;
}

/**
 * An order a list can be put in, as one choice.
 *
 * Column and direction together rather than two controls: "most held first"
 * is a thing somebody wants, where "total, descending" is two things they
 * have to assemble.
 */
type Ordering<T extends string> = { value: string; label: string; sort: T; direction: "asc" | "desc" };

function ordering<T extends string>(list: ReadonlyArray<Ordering<T>>, value: string) {
  return list.find((option) => option.value === value) ?? list[0];
}

const LEVEL_ORDERS: ReadonlyArray<Ordering<StockSort>> = [
  { value: "product", label: "Product A–Z", sort: "product", direction: "asc" },
  { value: "urgent", label: "Most urgent first", sort: "status", direction: "asc" },
  { value: "fewest", label: "Fewest on hand", sort: "quantity", direction: "asc" },
  { value: "most", label: "Most on hand", sort: "quantity", direction: "desc" },
  { value: "branch", label: "By branch", sort: "branch", direction: "asc" },
  { value: "category", label: "By category", sort: "category", direction: "asc" },
];

const OVERVIEW_ORDERS: ReadonlyArray<Ordering<OverviewSort>> = [
  { value: "product", label: "Product A–Z", sort: "product", direction: "asc" },
  { value: "most", label: "Most held", sort: "total", direction: "desc" },
  { value: "fewest", label: "Least held", sort: "total", direction: "asc" },
  { value: "category", label: "By category", sort: "category", direction: "asc" },
];

/** The statuses worth filtering a stock list down to. */
const STATUS_FILTERS = [
  { value: "", label: "Any status" },
  { value: "low", label: "Needs attention" },
  { value: "out_of_stock", label: "Out of stock" },
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
  { value: "ok", label: "Ok" },
] as const;

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

  function take(product: Product) {
    onPick(product);
    setSearch("");
    setResults([]);
  }

  return (
    <div>
      <Field label={label} hint="name, SKU or barcode">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            // A scanner types fast and finishes with Enter, and Enter in a
            // search box should never submit the form around it.
            if (e.key !== "Enter") return;
            e.preventDefault();
            if (results[0]) take(results[0]);
          }}
          placeholder="Start typing…"
        />
      </Field>
      {results.length > 0 && (
        <PickList>
          {results.map((product) => (
            <Pick
              key={product.id}
              onPick={() => take(product)}
              name={product.name}
              meta={
                product.track_stock
                  ? `· ${quantity(product.quantity_on_hand)} on hand`
                  : "· not stocked"
              }
            />
          ))}
        </PickList>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Across every branch
// --------------------------------------------------------------------------- //

const OVERVIEW_PAGE = 100;

/**
 * One row per product, one column per branch: where the stock actually is,
 * rather than how much of it there is. The totals under the table cover the
 * whole catalogue, not just the page, so paging never changes the figure the
 * owner came for.
 */
function Overview() {
  const { session } = useSession();
  const categories = useCategories();
  const [data, setData] = useState<StockOverview | null>(null);
  const [branchId, setBranchId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [search, setSearch] = useState("");
  const [order, setOrder] = useState("product");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const chosen = ordering(OVERVIEW_ORDERS, order);

  // Narrowing the list invalidates where you were in it: page four of the
  // old answer is not page four of the new one.
  useEffect(() => {
    setOffset(0);
  }, [search, branchId, categoryId, order]);

  useEffect(() => {
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .stockOverview({
          branch_id: branchId || undefined,
          category_id: categoryId || undefined,
          q: search || undefined,
          sort: chosen.sort,
          direction: chosen.direction,
          limit: OVERVIEW_PAGE,
          offset,
        })
        .then((result) => {
          setData(result);
          setError(null);
        })
        .catch((cause) => setError(describeError(cause, "Could not load the overview")))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(timer);
  }, [branchId, categoryId, search, chosen.sort, chosen.direction, offset]);

  const branches = session?.branches ?? [];
  const shown = data?.branches ?? [];
  const columns = shown.length + 3;
  const narrowed = Boolean(search || categoryId || branchId);

  /** The same state the order picker drives, from the heading. */
  function headSort(by: OverviewSort) {
    const flipped = chosen.sort === by && chosen.direction === "asc" ? "desc" : "asc";
    const match = OVERVIEW_ORDERS.find((o) => o.sort === by && o.direction === flipped);
    setOrder((match ?? OVERVIEW_ORDERS.find((o) => o.sort === by) ?? chosen).value);
  }

  return (
    <div className="card">
      <div className="card-title">Stock across the business</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Every stocked product against every branch you can see. A branch that has nothing
        recorded yet still gets a column, holding zero.
      </p>
      <Alert>{error}</Alert>
      <FilterBar>
        <label className="field filter wide">
          <span>Search</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Product name…"
          />
        </label>
        {branches.length > 1 && (
          <Picker
            label="Branch"
            value={branchId}
            onChange={setBranchId}
            options={[
              { value: "", label: "All branches" },
              ...branches.map((branch) => ({ value: branch.id, label: branch.name })),
            ]}
          />
        )}
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
        <Picker label="Order" value={order} onChange={setOrder} options={OVERVIEW_ORDERS} />
      </FilterBar>

      {data && data.rows.length === 0 && !loading ? (
        <Empty title={narrowed ? "Nothing matches that" : "No stocked products yet"}>
          <p>
            {narrowed
              ? "Try part of the product name, or widen the filters."
              : "Add products, then record what each branch actually has."}
          </p>
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <SortableHead
                  label="Product"
                  by="product"
                  sort={chosen.sort}
                  direction={chosen.direction}
                  onSort={headSort}
                />
                {shown.map((branch) => (
                  <th key={branch.branch_id} className="num">
                    {branch.name}
                  </th>
                ))}
                <SortableHead
                  label="All branches"
                  by="total"
                  className="num"
                  sort={chosen.sort}
                  direction={chosen.direction}
                  onSort={headSort}
                />
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(data?.rows ?? []).map((row, index) => {
                const previous = index > 0 ? (data?.rows ?? [])[index - 1] : undefined;
                const heading =
                  chosen.sort === "category" &&
                  (index === 0 || previous?.category_name !== row.category_name)
                    ? (row.category_name ?? "No category")
                    : null;
                return (
                  <Fragment key={row.variant_id}>
                    {heading && <GroupRow label={heading} span={columns} />}
                    <tr>
                      <td>
                        {row.name}
                        {row.sku && (
                          <div className="muted" style={{ fontSize: "0.8rem" }}>
                            {row.sku}
                          </div>
                        )}
                      </td>
                      {shown.map((branch) => {
                        const held = row.quantities[branch.branch_id] ?? "0";
                        return (
                          <td
                            key={branch.branch_id}
                            className={Number(held) === 0 ? "num muted" : "num"}
                          >
                            {quantity(held)}
                          </td>
                        );
                      })}
                      <td className="num">
                        <strong>{quantity(row.total)}</strong>
                      </td>
                      <td className="nowrap">
                        <Badge status={row.status} />
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
            {data && (
              <tfoot>
                <tr>
                  <td>
                    Total held
                    <div className="muted" style={{ fontSize: "0.8rem" }}>
                      {data.total} product{data.total === 1 ? "" : "s"}
                    </div>
                  </td>
                  {shown.map((branch) => (
                    <td key={branch.branch_id} className="num">
                      {quantity(branch.total)}
                    </td>
                  ))}
                  <td className="num">
                    <strong>{quantity(data.grand_total)}</strong>
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}

      {data && (
        <Pager
          total={data.total}
          limit={OVERVIEW_PAGE}
          offset={offset}
          onOffset={setOffset}
          noun="products"
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// On hand
// --------------------------------------------------------------------------- //

const LEVELS_PAGE = 50;

/**
 * One row per product per branch: how much is on hand, and whether that is
 * enough (PRD 9).
 *
 * A shop with a few hundred products across a few branches has a few
 * thousand rows here, so the list is narrowed before it is read and read a
 * page at a time.  Grouping is done by asking the server for the rows in
 * that order and drawing a heading when the value changes, which is the
 * only kind of grouping that survives a page boundary.
 */
function Levels({ initialLow }: { initialLow: boolean }) {
  const { session } = useSession();
  const categories = useCategories();
  const [page, setPage] = useState<Page<StockLevel> | null>(null);
  const [search, setSearch] = useState("");
  const [branchId, setBranchId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [status, setStatus] = useState(initialLow ? "low" : "");
  const [order, setOrder] = useState(initialLow ? "urgent" : "product");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const chosen = ordering(LEVEL_ORDERS, order);
  const branches = session?.branches ?? [];

  useEffect(() => {
    setOffset(0);
  }, [search, branchId, categoryId, status, order]);

  useEffect(() => {
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .stockLevels({
          q: search || undefined,
          branch_id: branchId || undefined,
          category_id: categoryId || undefined,
          status: status || undefined,
          sort: chosen.sort,
          direction: chosen.direction,
          limit: LEVELS_PAGE,
          offset,
        })
        .then((result) => {
          setPage(result);
          setError(null);
        })
        .catch((cause) => setError(describeError(cause, "Could not load stock")))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(timer);
  }, [search, branchId, categoryId, status, chosen.sort, chosen.direction, offset]);

  function headSort(by: StockSort) {
    const flipped = chosen.sort === by && chosen.direction === "asc" ? "desc" : "asc";
    const match = LEVEL_ORDERS.find((o) => o.sort === by && o.direction === flipped);
    setOrder((match ?? LEVEL_ORDERS.find((o) => o.sort === by) ?? chosen).value);
  }

  /** What a row sits under, when the list is grouped at all. */
  function grouped(row: StockLevel): string | null {
    if (chosen.sort === "branch") return row.branch_name ?? "No branch";
    if (chosen.sort === "category") return row.category_name ?? "No category";
    return null;
  }

  const rows = page?.items ?? [];
  const narrowed = Boolean(search || branchId || categoryId || status);

  return (
    <div className="card">
      <Alert>{error}</Alert>
      <FilterBar>
        <label className="field filter wide">
          <span>Search</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Product name…"
          />
        </label>
        {branches.length > 1 && (
          <Picker
            label="Branch"
            value={branchId}
            onChange={setBranchId}
            options={[
              { value: "", label: "All branches" },
              ...branches.map((branch) => ({ value: branch.id, label: branch.name })),
            ]}
          />
        )}
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
        <Picker label="Status" value={status} onChange={setStatus} options={STATUS_FILTERS} />
        <Picker label="Order" value={order} onChange={setOrder} options={LEVEL_ORDERS} />
      </FilterBar>

      {rows.length === 0 && !loading ? (
        <Empty title={narrowed ? "Nothing matches that" : "No stock recorded"}>
          <p>
            {narrowed
              ? "Widen the filters, or clear the search."
              : "Add products with an opening quantity, or receive stock from a supplier."}
          </p>
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <SortableHead
                  label="Product"
                  by="product"
                  sort={chosen.sort}
                  direction={chosen.direction}
                  onSort={headSort}
                />
                <SortableHead
                  label="Branch"
                  by="branch"
                  sort={chosen.sort}
                  direction={chosen.direction}
                  onSort={headSort}
                />
                <SortableHead
                  label="On hand"
                  by="quantity"
                  className="num"
                  sort={chosen.sort}
                  direction={chosen.direction}
                  onSort={headSort}
                />
                <th className="num">Min</th>
                <th className="num">Reorder at</th>
                <SortableHead
                  label="Status"
                  by="status"
                  sort={chosen.sort}
                  direction={chosen.direction}
                  onSort={headSort}
                />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const heading = grouped(row);
                const previous = index > 0 ? grouped(rows[index - 1]) : null;
                return (
                  <Fragment key={`${row.variant_id}-${row.branch_id}`}>
                    {heading && (index === 0 || heading !== previous) && (
                      <GroupRow label={heading} span={6} />
                    )}
                    <tr>
                      <td>
                        {row.name}
                        {row.category_name && chosen.sort !== "category" && (
                          <div className="muted" style={{ fontSize: "0.8rem" }}>
                            {row.category_name}
                          </div>
                        )}
                      </td>
                      {/* Under a branch heading the column would say it
                          again on every row. */}
                      <td className="muted">
                        {chosen.sort === "branch" ? "" : (row.branch_name ?? "—")}
                      </td>
                      <td className="num">{quantity(row.quantity)}</td>
                      <td className="num muted">{quantity(row.min_stock)}</td>
                      <td className="num muted">{quantity(row.reorder_level)}</td>
                      <td className="nowrap">
                        <Badge status={row.status} />
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {page && (
        <Pager
          total={page.total}
          limit={LEVELS_PAGE}
          offset={offset}
          onOffset={setOffset}
          noun="lines"
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Opening stock: what a branch actually has on its shelves
// --------------------------------------------------------------------------- //

const SHEET_PAGE = 100;

/**
 * A new branch starts with every product and none of the quantities. This asks
 * for the quantities, one shelf at a time: type what is there, and the ledger
 * gets the difference. Edits survive searching and paging, so a long catalogue
 * can be walked in whatever order the shelves are in and saved once.
 */
function Opening({
  awaiting,
  initialBranch,
  onRecorded,
}: {
  awaiting: BranchStockSetup[];
  initialBranch: string | null;
  onRecorded: () => void;
}) {
  const { session } = useSession();
  const branches = useMemo(() => session?.branches ?? [], [session]);
  const [branchId, setBranchId] = useState(
    () => initialBranch || awaiting[0]?.branch_id || branches[0]?.id || "",
  );
  const [sheet, setSheet] = useState<OpeningSheet | null>(null);
  const [counted, setCounted] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitKey, setSubmitKey] = useState(() => crypto.randomUUID());
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    if (!branchId && branches.length > 0) setBranchId(branches[0].id);
  }, [branches, branchId]);

  // A different branch is a different count; typed quantities do not carry over.
  useEffect(() => {
    setCounted({});
    setLoaded({});
    setOffset(0);
    setDone(null);
  }, [branchId]);

  useEffect(() => {
    if (!branchId) return;
    const timer = setTimeout(() => {
      api
        .openingSheet({ branch_id: branchId, q: search || undefined, limit: SHEET_PAGE, offset })
        .then((result) => {
          setSheet(result);
          setError(null);
          setLoaded((all) => ({
            ...all,
            ...Object.fromEntries(result.rows.map((row) => [row.variant_id, row.quantity])),
          }));
        })
        .catch((cause) => setError(describeError(cause, "Could not load the products")));
    }, 200);
    return () => clearTimeout(timer);
  }, [branchId, search, offset, reloads]);

  // Quantities belong to the branch they were counted at. While the sheet on
  // screen is still another branch's, there is nothing safe to save.
  const ready = sheet !== null && sheet.branch_id === branchId;

  // Only what somebody actually typed, and only where it differs from what the
  // branch is already recorded as holding.
  const changes = Object.entries(counted).filter(([variantId, value]) => {
    if (value.trim() === "" || Number.isNaN(Number(value))) return false;
    return Number(value) !== Number(loaded[variantId] ?? "0");
  });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (changes.length === 0 || !ready) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.recordOpeningStock({
        branch_id: branchId,
        lines: changes.map(([variant_id, quantity]) => ({ variant_id, quantity })),
        idempotency_key: submitKey,
      });
      setDone(
        `Recorded ${result.recorded} product${result.recorded === 1 ? "" : "s"} at ${
          sheet?.branch_name ?? "this branch"
        }.` + (result.unchanged > 0 ? ` ${result.unchanged} were already right.` : ""),
      );
      setCounted({});
      setSubmitKey(crypto.randomUUID());
      setReloads((n) => n + 1);
      onRecorded();
    } catch (cause) {
      setError(describeError(cause, "Could not record the quantities"));
    } finally {
      setBusy(false);
    }
  }

  if (branches.length === 0) {
    return (
      <div className="card">
        <Alert kind="warn">No branch to count. Add one under Settings first.</Alert>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">Record what is on the shelves</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Type the quantity you can actually count for each product and leave the rest alone.
        Each figure becomes a stock movement with your name on it, so a mistake can be traced
        and corrected rather than overwritten.
      </p>
      <Alert>{error}</Alert>
      {done && (
        <div className="alert ok" role="status">
          {done}
        </div>
      )}

      <div className="row" style={{ marginBottom: 8 }}>
        <div style={{ minWidth: 180 }}>
          <Field label="Branch">
            <select value={branchId} onChange={(e) => setBranchId(e.target.value)}>
              {branches.map((branch) => (
                <option key={branch.id} value={branch.id}>
                  {branch.name}
                  {awaiting.some((b) => b.branch_id === branch.id) ? " — nothing recorded" : ""}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div style={{ flex: 1, minWidth: 180 }}>
          <Field label="Find a product" hint="optional — typed quantities are kept">
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
              placeholder="Product name…"
            />
          </Field>
        </div>
      </div>

      {ready && (
        <p className="muted" style={{ fontSize: "0.88rem", marginTop: 0 }}>
          Recording against <strong>{sheet.location_name}</strong> · {sheet.recorded} of{" "}
          {sheet.product_count} product{sheet.product_count === 1 ? " has" : "s have"} a quantity
          here
        </p>
      )}

      {ready && sheet.rows.length === 0 ? (
        <Empty title={search ? "Nothing matches that" : "No products to count"}>
          <p>{search ? "Try part of the product name." : "Add products to your catalogue first."}</p>
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th className="num">Recorded now</th>
                <th className="num">Counted</th>
              </tr>
            </thead>
            <tbody>
              {(ready ? sheet.rows : []).map((row) => (
                <tr key={row.variant_id}>
                  <td>
                    {row.name}
                    <div className="muted" style={{ fontSize: "0.8rem" }}>
                      {row.sku ? `${row.sku} · ` : ""}
                      {row.unit}
                    </div>
                  </td>
                  <td className="num muted">{quantity(row.quantity)}</td>
                  <td className="num">
                    <input
                      style={{ width: 100, textAlign: "right" }}
                      inputMode="decimal"
                      aria-label={`Counted quantity for ${row.name}`}
                      placeholder={row.quantity}
                      value={counted[row.variant_id] ?? ""}
                      onChange={(e) =>
                        setCounted((all) => ({ ...all, [row.variant_id]: e.target.value }))
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {ready && sheet.total > SHEET_PAGE && (
        <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
          <button
            type="button"
            className="secondary"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - SHEET_PAGE))}
          >
            Previous
          </button>
          <span className="muted" style={{ fontSize: "0.88rem" }}>
            {offset + 1}–{Math.min(offset + SHEET_PAGE, sheet.total)} of {sheet.total}
          </span>
          <button
            type="button"
            className="secondary"
            disabled={offset + SHEET_PAGE >= sheet.total}
            onClick={() => setOffset((o) => o + SHEET_PAGE)}
          >
            Next
          </button>
        </div>
      )}

      <div className="row" style={{ marginTop: 12 }}>
        <button type="submit" disabled={busy || !ready || changes.length === 0}>
          {busy
            ? "Saving…"
            : !ready
              ? "Loading…"
              : changes.length === 0
                ? "Nothing to save yet"
                : `Save ${changes.length} quantit${changes.length === 1 ? "y" : "ies"}`}
        </button>
        {changes.length > 0 && (
          <button type="button" className="secondary" onClick={() => setCounted({})}>
            Clear what I typed
          </button>
        )}
      </div>
    </form>
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
// Between branches: sending stock, and asking for it
// --------------------------------------------------------------------------- //

type Decision = { transfer: Transfer; action: "approve" | "reject" | "cancel" };

/**
 * One list for both directions. A branch with stock to spare sends it; a branch
 * that has run out asks, and the owner decides. Requests and transfers are the
 * same record at different stages, so what was asked for, allowed, refused and
 * actually moved reads as a single history.
 */
function Transfers() {
  const { can, canWrite } = useSession();
  const locations = useLocations();
  const [branches, setBranches] = useState<TransferBranch[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<"none" | "request" | "send">("none");
  const [receiving, setReceiving] = useState<Transfer | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const mayMove = canWrite && can("stock:transfer");
  const mayDecide = canWrite && can("stock:transfer_approve");

  const load = useCallback(async () => {
    try {
      setTransfers(await api.transfers({ limit: 200 }));
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load transfers"));
    }
  }, []);

  useEffect(() => {
    void load();
    if (can("stock:transfer")) {
      api.transferBranches().then(setBranches).catch(() => setBranches([]));
    }
  }, [load, can]);

  const mine = new Set(branches.filter((b) => b.is_mine).map((b) => b.branch_id));
  const toDecide = mayDecide ? transfers.filter((t) => t.status === "requested") : [];
  // An approved request is the asking branch's to take up or turn down.
  const toAccept = transfers.filter(
    (t) => t.status === "approved" && (t.to_branch_id === null || mine.has(t.to_branch_id)),
  );

  async function act(action: () => Promise<unknown>) {
    try {
      await action();
      setReceiving(null);
      setDecision(null);
      await load();
    } catch (cause) {
      setError(describeError(cause, "Could not update the transfer"));
    }
  }

  const where = (transfer: Transfer) =>
    `${transfer.from_branch_name ?? transfer.from_location_name ?? "…"} → ${
      transfer.to_branch_name ?? transfer.to_location_name ?? "…"
    }`;

  const lines = (transfer: Transfer) =>
    transfer.lines.map((line) => (
      <div key={line.id} style={{ fontSize: "0.88rem" }}>
        {line.name ?? "Product"} × {quantity(line.quantity_sent)}
        {line.quantity_received !== null && line.quantity_received !== line.quantity_sent && (
          <span className="badge warn" style={{ marginLeft: 6 }}>
            received {quantity(line.quantity_received)}
          </span>
        )}
      </div>
    ));

  return (
    <>
      <Alert>{error}</Alert>
      {mayMove && form === "none" && (
        <div className="row" style={{ marginBottom: 12 }}>
          <button type="button" onClick={() => setForm("request")}>
            Ask another branch for stock
          </button>
          <button type="button" className="secondary" onClick={() => setForm("send")}>
            Send stock to another branch
          </button>
        </div>
      )}
      {form === "request" && (
        <RequestStock
          branches={branches}
          onDone={(saved) => {
            setForm("none");
            if (saved) void load();
          }}
        />
      )}
      {form === "send" && (
        <NewTransfer
          locations={locations}
          onDone={() => {
            setForm("none");
            void load();
          }}
        />
      )}
      {receiving && (
        <ReceiveTransfer
          transfer={receiving}
          onSubmit={(received) => act(() => api.receiveTransfer(receiving.id, received))}
          onCancel={() => setReceiving(null)}
        />
      )}
      {decision && (
        <DecisionForm
          decision={decision}
          onSubmit={(note) =>
            act(() => {
              if (decision.action === "approve") return api.approveTransfer(decision.transfer.id, note);
              if (decision.action === "reject") return api.rejectTransfer(decision.transfer.id, note);
              return api.cancelTransfer(decision.transfer.id, note);
            })
          }
          onCancel={() => setDecision(null)}
        />
      )}

      {toDecide.length > 0 && (
        <div className="card">
          <div className="card-title">Waiting for your decision ({toDecide.length})</div>
          <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
            Approving does not move anything yet — the branch that asked still has to accept.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Reference</th>
                  <th>From → to</th>
                  <th>Asked for</th>
                  <th>Why</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {toDecide.map((transfer) => (
                  <tr key={transfer.id}>
                    <td className="nowrap">{transfer.reference}</td>
                    <td>{where(transfer)}</td>
                    <td>{lines(transfer)}</td>
                    <td className="muted">
                      {transfer.note ?? "—"}
                      <div style={{ fontSize: "0.8rem" }}>
                        {transfer.requested_by_name ?? "someone"}
                        {transfer.requested_at ? `, ${dateTime(transfer.requested_at)}` : ""}
                      </div>
                    </td>
                    <td className="num nowrap">
                      <button
                        type="button"
                        className="link"
                        onClick={() => setDecision({ transfer, action: "approve" })}
                      >
                        Approve
                      </button>
                      <span className="muted"> · </span>
                      <button
                        type="button"
                        className="link"
                        onClick={() => setDecision({ transfer, action: "reject" })}
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {mayMove && toAccept.length > 0 && (
        <div className="card">
          <div className="card-title">Approved — yours to accept ({toAccept.length})</div>
          <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
            Accepting moves the stock now: it leaves the other branch and arrives at yours in one
            step. Turn it down instead if you no longer need it.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Reference</th>
                  <th>From → to</th>
                  <th>Approved</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {toAccept.map((transfer) => (
                  <tr key={transfer.id}>
                    <td className="nowrap">{transfer.reference}</td>
                    <td>
                      {where(transfer)}
                      {lines(transfer)}
                    </td>
                    <td className="muted">
                      {transfer.decided_by_name ?? "—"}
                      {transfer.decided_at && (
                        <div style={{ fontSize: "0.8rem" }}>{dateTime(transfer.decided_at)}</div>
                      )}
                      {transfer.decision_note && (
                        <div style={{ fontSize: "0.8rem" }}>{transfer.decision_note}</div>
                      )}
                    </td>
                    <td className="num nowrap">
                      <button
                        type="button"
                        className="link"
                        onClick={() => act(() => api.acceptTransfer(transfer.id))}
                      >
                        Accept
                      </button>
                      <span className="muted"> · </span>
                      <button
                        type="button"
                        className="link"
                        onClick={() => setDecision({ transfer, action: "cancel" })}
                      >
                        Turn down
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-title">Transfers and requests</div>
        <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
          Everything asked for, allowed, refused and moved between branches. Stock sent the other
          way — by a branch with some to spare — leaves on dispatch and arrives on receipt, and
          anything received short is posted as a loss so every unit is accounted for.
        </p>
        {transfers.length === 0 ? (
          <Empty title="Nothing between branches yet" />
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
                {transfers.map((transfer) => (
                  <tr key={transfer.id}>
                    <td className="nowrap">{transfer.reference}</td>
                    <td>{where(transfer)}</td>
                    <td>{lines(transfer)}</td>
                    <td className="nowrap">
                      <Badge status={transfer.status} />
                      {transfer.decision_note && (
                        <div className="muted" style={{ fontSize: "0.8rem" }}>
                          {transfer.decision_note}
                        </div>
                      )}
                    </td>
                    <td className="num nowrap">
                      {mayMove && transfer.status === "draft" && (
                        <button
                          type="button"
                          className="link"
                          onClick={() => act(() => api.dispatchTransfer(transfer.id))}
                        >
                          Dispatch
                        </button>
                      )}
                      {mayMove && transfer.status === "dispatched" && (
                        <button type="button" className="link" onClick={() => setReceiving(transfer)}>
                          Receive
                        </button>
                      )}
                      {/* An approved request is called off from its own panel
                          above, where "turn down" is the word for it. */}
                      {mayMove && (transfer.status === "draft" || transfer.status === "requested") && (
                        <>
                          {transfer.status === "draft" && <span className="muted"> · </span>}
                          <button
                            type="button"
                            className="link"
                            onClick={() => setDecision({ transfer, action: "cancel" })}
                          >
                            Cancel
                          </button>
                        </>
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

/** Ask another branch for stock: source, products, quantities and why. */
function RequestStock({
  branches,
  onDone,
}: {
  branches: TransferBranch[];
  onDone: (saved: boolean) => void;
}) {
  const ours = useMemo(
    () => branches.filter((b) => b.is_mine && b.location_id),
    [branches],
  );
  const [to, setTo] = useState("");
  const [from, setFrom] = useState("");
  const [lines, setLines] = useState<Array<{ variantId: string; name: string; quantity: string }>>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setTo((current) => current || ours[0]?.branch_id || "");
  }, [ours]);

  // You cannot ask a branch for stock it would be sending to itself.
  const sources = useMemo(
    () => branches.filter((b) => b.branch_id !== to && b.location_id),
    [branches, to],
  );
  useEffect(() => {
    setFrom((current) =>
      sources.some((b) => b.branch_id === current) ? current : sources[0]?.branch_id || "",
    );
  }, [sources]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const source = branches.find((b) => b.branch_id === from);
    const destination = branches.find((b) => b.branch_id === to);
    if (!source?.location_id || !destination?.location_id) return;
    setBusy(true);
    setError(null);
    try {
      await api.requestTransfer({
        from_location_id: source.location_id,
        to_location_id: destination.location_id,
        lines: lines.map((l) => ({ variant_id: l.variantId, quantity: l.quantity })),
        note: note || undefined,
      });
      onDone(true);
    } catch (cause) {
      setError(describeError(cause, "Could not send the request"));
    } finally {
      setBusy(false);
    }
  }

  if (branches.length < 2 || ours.length === 0) {
    return (
      <div className="card">
        <Alert kind="warn">
          A request needs two branches, one of them yours. Add a branch under Settings first.
        </Alert>
        <button type="button" className="secondary" onClick={() => onDone(false)}>
          Close
        </button>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">Ask another branch for stock</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Ask for what you need. Nothing moves until the owner approves it and you accept — and
        whoever decides can see what every branch holds, so you do not have to.
      </p>
      <Alert>{error}</Alert>
      <div className="grid">
        <Field label="Ask">
          <select value={from} onChange={(e) => setFrom(e.target.value)}>
            {sources.map((branch) => (
              <option key={branch.branch_id} value={branch.branch_id}>
                {branch.branch_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="For">
          <select value={to} onChange={(e) => setTo(e.target.value)}>
            {ours.map((branch) => (
              <option key={branch.branch_id} value={branch.branch_id}>
                {branch.branch_name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <ProductPicker
        onPick={(product) => {
          const variant = product.variants[0];
          if (variant && !lines.some((l) => l.variantId === variant.id)) {
            setLines((all) => [
              ...all,
              { variantId: variant.id, name: product.name, quantity: "1" },
            ]);
          }
        }}
      />
      {lines.map((line) => (
        <div key={line.variantId} className="row" style={{ marginBottom: 8 }}>
          <span style={{ flex: 1 }}>{line.name}</span>
          <input
            style={{ width: 100, textAlign: "right" }}
            inputMode="decimal"
            aria-label={`Quantity of ${line.name}`}
            value={line.quantity}
            onChange={(e) =>
              setLines((all) =>
                all.map((l) =>
                  l.variantId === line.variantId ? { ...l, quantity: e.target.value } : l,
                ),
              )
            }
          />
          <button
            type="button"
            className="link"
            onClick={() => setLines((all) => all.filter((l) => l.variantId !== line.variantId))}
          >
            Remove
          </button>
        </div>
      ))}
      <Field label="Why you need it" hint="optional, but it is what the owner reads">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. sold out before lunch"
        />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy || lines.length === 0 || !from || from === to}>
          {busy ? "Sending…" : "Send the request"}
        </button>
        <button type="button" className="secondary" onClick={() => onDone(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** The note that goes with a decision. A refusal needs one; the rest may have one. */
function DecisionForm({
  decision,
  onSubmit,
  onCancel,
}: {
  decision: Decision;
  onSubmit: (note: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const required = decision.action === "reject";
  const titles = {
    approve: `Approve ${decision.transfer.reference}`,
    reject: `Turn down ${decision.transfer.reference}`,
    cancel: `Cancel ${decision.transfer.reference}`,
  };
  const hints = {
    approve: "Nothing moves yet — the branch that asked still has to accept.",
    reject: "Say why. Whoever asked will read it.",
    cancel: "Nothing has moved, so nothing is reversed.",
  };

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        void onSubmit(note).finally(() => setBusy(false));
      }}
    >
      <div className="card-title">{titles[decision.action]}</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        {hints[decision.action]}
      </p>
      <Field label={required ? "Reason" : "Note"} hint={required ? undefined : "optional"}>
        <input value={note} onChange={(e) => setNote(e.target.value)} autoFocus />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy || (required && !note.trim())}>
          {busy ? "Saving…" : titles[decision.action]}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Back
        </button>
      </div>
    </form>
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
  onSubmit,
  onCancel,
}: {
  transfer: Transfer;
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
            {line.name ?? "Product"} <span className="muted">(sent {quantity(line.quantity_sent)})</span>
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

const LEDGER_PAGE = 50;

/** Why stock moved, as a shopkeeper would say it. */
const LEDGER_REASONS = [
  { value: "", label: "Any reason" },
  { value: "sale", label: "Sold" },
  { value: "sale_return", label: "Came back" },
  { value: "sale_void", label: "Sale voided" },
  { value: "purchase", label: "Received" },
  { value: "purchase_return", label: "Returned to supplier" },
  { value: "transfer_out", label: "Sent to a branch" },
  { value: "transfer_in", label: "Had from a branch" },
  { value: "count_adjustment", label: "Counted" },
  { value: "adjustment", label: "Adjusted" },
  { value: "damage", label: "Damaged" },
  { value: "loss", label: "Lost" },
  { value: "opening", label: "Opening stock" },
] as const;

/**
 * The stock ledger: every change, with who, when and why (PRD 9).
 *
 * Never trimmed and never reordered — an append-only record read newest
 * first — so the only way through it is to narrow it and page it.  The
 * names come from the server: resolving them here would mean holding the
 * whole catalogue, and a catalogue fetched one page deep mislabels
 * everything past it.
 */
function Movements() {
  const { session } = useSession();
  const [page, setPage] = useState<Page<Movement> | null>(null);
  const [branchId, setBranchId] = useState("");
  const [reason, setReason] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const branches = session?.branches ?? [];

  useEffect(() => {
    setOffset(0);
  }, [branchId, reason, since, until]);

  useEffect(() => {
    setLoading(true);
    api
      .movements({
        branch_id: branchId || undefined,
        reason: reason || undefined,
        since: since || undefined,
        until: until || undefined,
        limit: LEDGER_PAGE,
        offset,
      })
      .then((result) => {
        setPage(result);
        setError(null);
      })
      .catch((cause) => setError(describeError(cause, "Could not load the ledger")))
      .finally(() => setLoading(false));
  }, [branchId, reason, since, until, offset]);

  const rows = page?.items ?? [];
  const narrowed = Boolean(branchId || reason || since || until);

  return (
    <div className="card">
      <div className="card-title">Movements</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Every change to stock, newest first. Nothing here is edited or removed — a mistake is
        corrected by a movement that undoes it, and both stay on the record.
      </p>
      <Alert>{error}</Alert>
      <FilterBar>
        {branches.length > 1 && (
          <Picker
            label="Branch"
            value={branchId}
            onChange={setBranchId}
            options={[
              { value: "", label: "All branches" },
              ...branches.map((branch) => ({ value: branch.id, label: branch.name })),
            ]}
          />
        )}
        <Picker label="Reason" value={reason} onChange={setReason} options={LEDGER_REASONS} />
        <label className="field filter">
          <span>From</span>
          <input type="date" value={since} max={until || undefined} onChange={(e) => setSince(e.target.value)} />
        </label>
        <label className="field filter">
          <span>To</span>
          <input type="date" value={until} min={since || undefined} onChange={(e) => setUntil(e.target.value)} />
        </label>
        {narrowed && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setBranchId("");
              setReason("");
              setSince("");
              setUntil("");
            }}
          >
            Clear
          </button>
        )}
      </FilterBar>

      {rows.length === 0 && !loading ? (
        <Empty title={narrowed ? "Nothing moved in that window" : "Nothing has moved yet"}>
          {narrowed ? <p>Widen the dates, or clear the filters.</p> : undefined}
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Product</th>
                {branches.length > 1 && <th>Branch</th>}
                <th>Reason</th>
                <th className="num">Change</th>
                <th className="num">After</th>
                <th>Who</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id}>
                  <td className="muted nowrap">{dateTime(m.occurred_at)}</td>
                  <td>
                    {m.product_name ?? "Product"}
                    {m.note && (
                      <div className="muted" style={{ fontSize: "0.8rem" }}>
                        {m.note}
                      </div>
                    )}
                  </td>
                  {branches.length > 1 && <td className="muted">{m.branch_name ?? "—"}</td>}
                  <td className="nowrap">
                    <Badge status={m.reason} />
                  </td>
                  <td className="num">
                    {Number(m.quantity) > 0 ? "+" : ""}
                    {quantity(m.quantity)}
                  </td>
                  <td className="num muted">{quantity(m.balance_after)}</td>
                  <td className="muted nowrap">{m.by_name ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {page && (
        <Pager
          total={page.total}
          limit={LEDGER_PAGE}
          offset={offset}
          onOffset={setOffset}
          noun="movements"
        />
      )}
    </div>
  );
}
