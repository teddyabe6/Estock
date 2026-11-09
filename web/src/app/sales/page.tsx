"use client";

/**
 * Every sale, newest first (PRD 10).
 *
 * A shop that takes fifty sales a day has fifteen thousand a year here, so
 * the list is narrowed before it is read and read a page at a time.  A
 * voided sale is kept rather than deleted, so it stays findable — under the
 * status filter, where it is not in the way of the question somebody
 * usually opens this to ask.
 */

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  Alert,
  Badge,
  Empty,
  FilterBar,
  GroupRow,
  PageHead,
  Pager,
  Picker,
  SortableHead,
} from "@/components/ui";
import { api, type Page, type Sale, type SaleSort } from "@/lib/api";
import { amount, dateTime } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

const PAGE = 50;

/**
 * An order as one choice rather than a column and a direction to assemble:
 * "biggest first" is a thing somebody wants.
 */
const ORDERS = [
  { value: "newest", label: "Newest first", sort: "when", direction: "desc" },
  { value: "oldest", label: "Oldest first", sort: "when", direction: "asc" },
  { value: "biggest", label: "Biggest first", sort: "total", direction: "desc" },
  { value: "smallest", label: "Smallest first", sort: "total", direction: "asc" },
  { value: "branch", label: "By branch", sort: "branch", direction: "asc" },
] as const satisfies ReadonlyArray<{
  value: string;
  label: string;
  sort: SaleSort;
  direction: "asc" | "desc";
}>;

const STATUSES = [
  { value: "completed", label: "Completed" },
  { value: "voided", label: "Voided" },
  { value: "all", label: "Both" },
] as const;

export default function SalesPage() {
  return (
    <AppShell>
      <Sales />
    </AppShell>
  );
}

function Sales() {
  const { session, can, canWrite } = useSession();
  const [page, setPage] = useState<Page<Sale> | null>(null);
  const [search, setSearch] = useState("");
  const [branchId, setBranchId] = useState("");
  const [status, setStatus] = useState<"completed" | "voided" | "all">("completed");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [order, setOrder] = useState("newest");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const chosen = ORDERS.find((o) => o.value === order) ?? ORDERS[0];
  const branches = session?.branches ?? [];
  const currency = session?.currency ?? "ETB";

  // Narrowing the list invalidates where you were in it.
  useEffect(() => {
    setOffset(0);
  }, [search, branchId, status, from, to, order]);

  useEffect(() => {
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .sales({
          q: search || undefined,
          branch_id: branchId || undefined,
          status,
          date_from: from || undefined,
          date_to: to || undefined,
          sort: chosen.sort,
          direction: chosen.direction,
          limit: PAGE,
          offset,
        })
        .then((result) => {
          setPage(result);
          setError(null);
        })
        .catch((cause) => setError(describeError(cause, "Could not load sales")))
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(timer);
  }, [search, branchId, status, from, to, chosen.sort, chosen.direction, offset]);

  function headSort(by: SaleSort) {
    const flipped = chosen.sort === by && chosen.direction === "desc" ? "asc" : "desc";
    const match = ORDERS.find((o) => o.sort === by && o.direction === flipped);
    setOrder((match ?? ORDERS.find((o) => o.sort === by) ?? chosen).value);
  }

  const nameOf = (id: string) => branches.find((b) => b.id === id)?.name ?? "Another branch";
  const rows = page?.items ?? [];
  const narrowed = Boolean(search || branchId || from || to || status !== "completed");

  return (
    <>
      <PageHead
        title="Sales"
        subtitle={loading && !page ? "Loading…" : `${page?.total ?? 0} recorded`}
        actions={
          canWrite && can("sale:create") ? (
            <Link href="/sales/new">
              <button type="button">New sale</button>
            </Link>
          ) : null
        }
      />

      <Alert>{error}</Alert>

      <div className="card">
        <FilterBar>
          <label className="field filter wide">
            <span>
              Search <em className="hint">number or customer</em>
            </span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="S-2026-000012, or a name…"
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
          <Picker
            label="Status"
            value={status}
            onChange={(value) => setStatus(value as typeof status)}
            options={STATUSES}
          />
          <label className="field filter">
            <span>From</span>
            <input
              type="date"
              value={from}
              max={to || undefined}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label className="field filter">
            <span>To</span>
            <input
              type="date"
              value={to}
              min={from || undefined}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
          <Picker label="Order" value={order} onChange={setOrder} options={ORDERS} />
        </FilterBar>

        {rows.length === 0 && !loading ? (
          <Empty title={narrowed ? "Nothing matches that" : "No sales yet"}>
            <p>
              {narrowed
                ? "Widen the dates, or clear the search."
                : "Your first sale will appear here."}
            </p>
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Number</th>
                  <SortableHead
                    label="When"
                    by="when"
                    sort={chosen.sort}
                    direction={chosen.direction}
                    onSort={headSort}
                  />
                  <SortableHead
                    label={`Total (${currency})`}
                    by="total"
                    className="num"
                    sort={chosen.sort}
                    direction={chosen.direction}
                    onSort={headSort}
                  />
                  <th className="num">Paid</th>
                  <th className="num">Balance</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((sale, index) => {
                  const heading =
                    chosen.sort === "branch" &&
                    (index === 0 || rows[index - 1].branch_id !== sale.branch_id)
                      ? nameOf(sale.branch_id)
                      : null;
                  return (
                    <Fragment key={sale.id}>
                      {heading && <GroupRow label={heading} span={6} />}
                      <tr>
                        <td className="nowrap">
                          <Link href={`/sales/${sale.id}`}>{sale.number}</Link>
                        </td>
                        <td className="muted nowrap">{dateTime(sale.sold_at)}</td>
                        <td className="num">{amount(sale.total_amount)}</td>
                        <td className="num">{amount(sale.amount_paid)}</td>
                        <td className="num">
                          {Number(sale.balance_due) > 0 ? (
                            <strong>{amount(sale.balance_due)}</strong>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td className="nowrap">
                          <Badge status={sale.status} />
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
            limit={PAGE}
            offset={offset}
            onOffset={setOffset}
            noun="sales"
          />
        )}
      </div>
    </>
  );
}
