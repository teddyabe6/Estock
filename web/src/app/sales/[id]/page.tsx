"use client";

/**
 * One sale: a printable receipt, its payments, what has come back off it, and
 * the two ways to undo it (PRD 10).
 *
 * Taking goods back keeps the sale and gives part of it back; voiding
 * reverses all of it. Neither deletes anything — both post compensating
 * movements and leave the record standing.
 */

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Field, PageHead } from "@/components/ui";
import { api, type Receipt, type ReturnableLine, type Sale } from "@/lib/api";
import { amount, dateTime, money, quantity } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

export default function SalePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <AppShell>
      <SaleDetail id={id} />
    </AppShell>
  );
}

function SaleDetail({ id }: { id: string }) {
  const { can, canWrite } = useSession();
  const [sale, setSale] = useState<Sale | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Which of the two undo forms is open, if either. */
  const [panel, setPanel] = useState<"return" | "void" | null>(null);

  const load = useCallback(async () => {
    try {
      const [saleResult, receiptResult] = await Promise.all([api.sale(id), api.receipt(id)]);
      setSale(saleResult);
      setReceipt(receiptResult);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load this sale"));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!sale || !receipt) {
    return (
      <>
        <PageHead title="Sale" subtitle="Loading…" />
        <Alert>{error}</Alert>
      </>
    );
  }

  const currency = receipt.sale.currency;
  // Gross profit comes back net of returns, so the cost standing beside it
  // has to be too: otherwise a sale that came back in full reads as cost
  // with no revenue behind it.
  const returnedCost = (sale.returns ?? []).reduce(
    (total, each) => total + Number(each.cost_total ?? 0),
    0,
  );
  const costKept = Number(sale.cost_total ?? 0) - returnedCost;

  return (
    <>
      <div className="no-print">
        <PageHead
          title={`Sale ${sale.number}`}
          subtitle={
            <>
              {dateTime(sale.sold_at)} · <Badge status={sale.status} />
            </>
          }
          actions={
            <>
              <Link href="/sales">
                <button type="button" className="secondary">
                  All sales
                </button>
              </Link>
              <button type="button" className="secondary" onClick={() => window.print()}>
                Print receipt
              </button>
              {sale.status === "completed" && canWrite && can("sale:refund") && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPanel(panel === "return" ? null : "return")}
                >
                  Take goods back
                </button>
              )}
              {sale.status === "completed" && canWrite && can("sale:void") && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPanel(panel === "void" ? null : "void")}
                >
                  Void sale
                </button>
              )}
            </>
          }
        />
        <Alert>{error}</Alert>
        {sale.status === "voided" && (
          <Alert kind="warn">
            This sale was voided. Its stock went back and the record is kept for the audit trail.
          </Alert>
        )}
        {panel === "return" && (
          <TakeGoodsBack
            saleId={id}
            onDone={() => {
              setPanel(null);
              void load();
            }}
            onCancel={() => setPanel(null)}
          />
        )}
        {panel === "void" && (
          <VoidSale
            saleId={id}
            onDone={() => {
              setPanel(null);
              void load();
            }}
            onCancel={() => setPanel(null)}
          />
        )}
        {sale.returns.length > 0 && <CameBack sale={sale} />}
      </div>

      <div className="card receipt">
        <div className="centre">
          <strong>{receipt.business.name}</strong>
          <div className="muted" style={{ fontSize: "0.85rem" }}>
            {[receipt.branch.name, receipt.business.address, receipt.business.phone]
              .filter(Boolean)
              .join(" · ")}
          </div>
          {receipt.business.tin && (
            <div className="muted" style={{ fontSize: "0.85rem" }}>
              TIN {receipt.business.tin}
            </div>
          )}
        </div>
        <hr />
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span>{receipt.sale.number}</span>
          <span>{dateTime(receipt.sale.sold_at)}</span>
        </div>
        {receipt.customer && (
          <div className="muted" style={{ fontSize: "0.85rem" }}>
            Customer: {receipt.customer.name}
            {receipt.customer.phone ? ` · ${receipt.customer.phone}` : ""}
          </div>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Qty</th>
                <th className="num">Price</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {receipt.lines.map((line, index) => (
                <tr key={`${line.description}-${index}`}>
                  <td>
                    {line.description}
                    {Number(line.discount_amount) > 0 && (
                      <div className="muted" style={{ fontSize: "0.8rem" }}>
                        discount −{amount(line.discount_amount)}
                      </div>
                    )}
                  </td>
                  <td className="num">{quantity(line.quantity)}</td>
                  <td className="num">{amount(line.unit_price)}</td>
                  <td className="num">{amount(line.line_total)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              {Number(receipt.sale.discount_total) > 0 && (
                <tr>
                  <td colSpan={3} className="num muted">Discount</td>
                  <td className="num">−{amount(receipt.sale.discount_total)}</td>
                </tr>
              )}
              {Number(receipt.sale.tax_total) > 0 && (
                <tr>
                  <td colSpan={3} className="num muted">Tax</td>
                  <td className="num">{amount(receipt.sale.tax_total)}</td>
                </tr>
              )}
              <tr>
                <td colSpan={3} className="num"><strong>Total</strong></td>
                <td className="num"><strong>{money(receipt.sale.total_amount, currency)}</strong></td>
              </tr>
              {/* A refund is a payment on this sale too; listing it as money
                  taken would read as if the customer paid twice. */}
              {receipt.payments.map((payment, index) => (
                <tr key={`${payment.method}-${index}`}>
                  <td colSpan={3} className="num muted">
                    {payment.direction === "out" ? "Refunded by" : "Paid by"}{" "}
                    {payment.method.replace(/_/g, " ")}
                  </td>
                  <td className="num">
                    {payment.direction === "out" ? "−" : ""}
                    {amount(payment.amount)}
                  </td>
                </tr>
              ))}
              {Number(receipt.sale.balance_due) > 0 && (
                <tr>
                  <td colSpan={3} className="num"><strong>Balance on credit</strong></td>
                  <td className="num"><strong>{amount(receipt.sale.balance_due)}</strong></td>
                </tr>
              )}
            </tfoot>
          </table>
        </div>
        <p className="centre muted" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
          Thank you for your business.
        </p>
      </div>

      {sale.gross_profit !== undefined && sale.gross_profit !== null && (
        <div className="card no-print">
          <div className="card-title">For the books</div>
          <div className="grid">
            <div className="stat">
              <div className="label">Cost of goods</div>
              <div className="value">{money(costKept, currency)}</div>
              {returnedCost > 0 && (
                <div className="note">{money(returnedCost, currency)} of it came back</div>
              )}
            </div>
            <div className="stat">
              <div className="label">Gross profit</div>
              <div className="value">{money(sale.gross_profit, currency)}</div>
              <div className="note">Sale-time cost snapshots, excluding tax</div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/**
 * A customer bringing part of a sale back (PRD 1, 10).
 *
 * Driven by what each line can still give back, so the same goods cannot come
 * back twice. Stock, value and money all follow on the server from the sale's
 * own lines: an outstanding balance absorbs the value before any cash leaves
 * the till.
 */
function TakeGoodsBack({
  saleId,
  onDone,
  onCancel,
}: {
  saleId: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [lines, setLines] = useState<ReturnableLine[] | null>(null);
  /** What has been typed, and whether each line can be sold again. */
  const [coming, setComing] = useState<Record<string, string>>({});
  const [restock, setRestock] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    api
      .returnableLines(saleId)
      .then((result) => setLines(result.lines.filter((line) => Number(line.quantity_returnable) > 0)))
      .catch((cause) => setError(describeError(cause, "Could not load this sale's lines")));
  }, [saleId]);

  // Only what somebody typed, and never more than the line can give back.
  const chosen = Object.entries(coming).filter(([, value]) => Number(value) > 0);
  const over = (line: ReturnableLine) =>
    Number(coming[line.sale_line_id] ?? 0) > Number(line.quantity_returnable);
  const ready = chosen.length > 0 && reason.trim().length >= 3 && !(lines ?? []).some(over);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await api.recordReturn(saleId, {
        lines: chosen.map(([sale_line_id, qty]) => ({
          sale_line_id,
          quantity: qty,
          restock: restock[sale_line_id] ?? true,
        })),
        reason: reason.trim(),
        idempotency_key: idempotencyKey,
      });
      setIdempotencyKey(crypto.randomUUID());
      onDone();
    } catch (cause) {
      setError(describeError(cause, "Could not record the return"));
    } finally {
      setBusy(false);
    }
  }

  if (lines !== null && lines.length === 0) {
    return (
      <div className="card">
        <div className="card-title">Take goods back</div>
        <Alert kind="warn">Every line of this sale has already come back.</Alert>
        <button type="button" className="secondary" onClick={onCancel}>
          Close
        </button>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">Take goods back</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Enter how many of each are coming back. Anything not fit to sell again still comes back on
        the ledger and is then written off, so the loss has a reason. A customer who still owes on
        this sale has the value taken off what they owe before any cash is handed over.
      </p>
      <Alert>{error}</Alert>
      {lines === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Sold</th>
                <th className="num">Already back</th>
                <th className="num">Coming back</th>
                <th>Fit to sell again</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.sale_line_id}>
                  <td>
                    {line.description}
                    <div className="muted" style={{ fontSize: "0.8rem" }}>
                      {amount(line.unit_price)} each
                    </div>
                  </td>
                  <td className="num muted">{quantity(line.quantity_sold)}</td>
                  <td className="num muted">{quantity(line.quantity_returned)}</td>
                  <td className="num nowrap">
                    <input
                      style={{ width: 90, textAlign: "right" }}
                      inputMode="decimal"
                      aria-label={`Quantity of ${line.description} coming back`}
                      placeholder="0"
                      value={coming[line.sale_line_id] ?? ""}
                      onChange={(e) =>
                        setComing((all) => ({ ...all, [line.sale_line_id]: e.target.value }))
                      }
                    />{" "}
                    {/* Most returns are the whole line, so it is one click.
                        Plainly, not formatted: the field has to parse it
                        back, and a thousands separator would not. */}
                    <button
                      type="button"
                      className="link"
                      onClick={() =>
                        setComing((all) => ({
                          ...all,
                          [line.sale_line_id]: String(Number(line.quantity_returnable)),
                        }))
                      }
                    >
                      All
                    </button>
                    {over(line) && (
                      <div className="muted" style={{ fontSize: "0.8rem", color: "var(--danger)" }}>
                        Only {quantity(line.quantity_returnable)} can come back
                      </div>
                    )}
                  </td>
                  <td>
                    {/* The label says what the tick does rather than
                        repeating the header, so the consequence is on
                        screen before the return is saved. */}
                    <label className="toggle" style={{ padding: 0 }}>
                      <input
                        type="checkbox"
                        aria-label={`${line.description} is fit to sell again`}
                        checked={restock[line.sale_line_id] ?? true}
                        disabled={!(Number(coming[line.sale_line_id] ?? 0) > 0)}
                        onChange={(e) =>
                          setRestock((all) => ({ ...all, [line.sale_line_id]: e.target.checked }))
                        }
                      />
                      <span className="muted nowrap" style={{ fontSize: "0.82rem" }}>
                        {restock[line.sale_line_id] ?? true ? "back on the shelf" : "written off"}
                      </span>
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Field label="Why it is coming back" hint="the customer and the audit trail both see this">
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. wrong size" />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy || !ready}>
          {busy
            ? "Saving…"
            : chosen.length === 0
              ? "Enter what is coming back"
              : reason.trim().length < 3
                ? "Say why it is coming back"
                : `Take back ${chosen.length} line${chosen.length === 1 ? "" : "s"}`}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Reversing the whole sale, with the reason that goes on the record. */
function VoidSale({
  saleId,
  onDone,
  onCancel,
}: {
  saleId: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (reason.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      await api.voidSale(saleId, reason.trim());
      onDone();
    } catch (cause) {
      setError(describeError(cause, "Could not void the sale"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-title">Void this sale</div>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        The whole sale is reversed: the goods go back on the shelf and the sale is kept as a
        record. Nothing is deleted. To take back only part of it, use Take goods back instead.
      </p>
      <Alert>{error}</Alert>
      <Field label="Why">
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. rung up twice"
          autoFocus
        />
      </Field>
      <div className="row">
        <button type="submit" disabled={busy || reason.trim().length < 3}>
          {busy ? "Voiding…" : "Void the sale"}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** What has already come back off this sale. */
function CameBack({ sale }: { sale: Sale }) {
  return (
    <div className="card">
      <div className="card-title">Came back</div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Return</th>
              <th>When</th>
              <th>Items</th>
              <th>Why</th>
              <th className="num">Value</th>
              <th className="num">Given back</th>
            </tr>
          </thead>
          <tbody>
            {sale.returns.map((item) => (
              <tr key={item.id}>
                <td className="nowrap">{item.number}</td>
                <td className="muted nowrap">{dateTime(item.returned_at)}</td>
                <td>
                  {item.lines.map((line) => (
                    <div key={line.id} style={{ fontSize: "0.88rem" }}>
                      {line.description} × {quantity(line.quantity)}
                      {!line.restock && (
                        <span className="badge warn" style={{ marginLeft: 6 }}>
                          written off
                        </span>
                      )}
                    </div>
                  ))}
                </td>
                <td className="muted">{item.reason}</td>
                <td className="num">{amount(item.total_amount)}</td>
                <td className="num">
                  {/* Money handed over and value taken off a balance are not
                      the same thing, and a shop needs to tell them apart. */}
                  {Number(item.refunded_amount) > 0 && (
                    <div>{amount(item.refunded_amount)} refunded</div>
                  )}
                  {Number(item.credited_amount) > 0 && (
                    <div className="muted">{amount(item.credited_amount)} off what was owed</div>
                  )}
                  {Number(item.refunded_amount) === 0 && Number(item.credited_amount) === 0 && (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
