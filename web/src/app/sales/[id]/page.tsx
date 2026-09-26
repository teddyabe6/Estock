"use client";

/**
 * One sale: a printable receipt, its payments, and the void action for those
 * who hold it (PRD 10). Voiding never deletes — it posts compensating stock
 * movements and keeps the record.
 */

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, PageHead } from "@/components/ui";
import { api, type Receipt, type Sale } from "@/lib/api";
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
  const [busy, setBusy] = useState(false);

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

  async function voidSale() {
    const reason = window.prompt(
      "Why is this sale being voided? Stock goes back and the sale is kept as a record.",
    );
    if (!reason || reason.trim().length < 3) return;
    setBusy(true);
    try {
      await api.voidSale(id, reason.trim());
      await load();
    } catch (cause) {
      setError(describeError(cause, "Could not void the sale"));
    } finally {
      setBusy(false);
    }
  }

  if (!sale || !receipt) {
    return (
      <>
        <PageHead title="Sale" subtitle="Loading…" />
        <Alert>{error}</Alert>
      </>
    );
  }

  const currency = receipt.sale.currency;

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
              {sale.status === "completed" && canWrite && can("sale:void") && (
                <button type="button" className="secondary" disabled={busy} onClick={() => void voidSale()}>
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
              {receipt.payments.map((payment, index) => (
                <tr key={`${payment.method}-${index}`}>
                  <td colSpan={3} className="num muted">Paid by {payment.method.replace(/_/g, " ")}</td>
                  <td className="num">{amount(payment.amount)}</td>
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
              <div className="value">{money(sale.cost_total, currency)}</div>
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
