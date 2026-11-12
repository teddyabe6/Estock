"use client";

/**
 * A shared proforma, viewed by the customer. It doubles as their order
 * tracking page: a request they made from the shop appears here first, the
 * priced proforma replaces it when the seller sends it, and accepting records
 * intent only — no sale, no stock movement (PRD 14).
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";

import { PaymentSlipForm } from "@/components/Storefront";
import { Alert } from "@/components/ui";
import { money, shortDate } from "@/lib/format";
import { paymentBadge, proformaLabel, proformaTone, shopApi, type ProformaView } from "@/lib/storefront";

const METHODS: Record<string, string> = {
  telebirr: "telebirr",
  cbe_birr: "CBE Birr",
  bank_transfer: "bank transfer",
  cash: "cash",
};

/** Where one slip has got to, in the customer's words. */
function slipStatus(status: string): { label: string; tone: "ok" | "warn" | "danger" } {
  switch (status) {
    case "accepted":
      return { label: "found by the seller", tone: "ok" };
    case "rejected":
      return { label: "not found", tone: "danger" };
    default:
      return { label: "being checked", tone: "warn" };
  }
}

export default function ProformaPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  return (
    <Suspense fallback={null}>
      <Proforma token={token} />
    </Suspense>
  );
}

function Proforma({ token }: { token: string }) {
  const search = useSearchParams();
  const justRequested = search.get("requested") === "1";
  const [proforma, setProforma] = useState<ProformaView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [responded, setResponded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [slipSent, setSlipSent] = useState<string | null>(null);
  /** Whether the buyer asked to send another slip while one is being checked. */
  const [another, setAnother] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    shopApi
      .quotation(token)
      .then(setProforma)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "This link is no longer valid"));
  }, [token, version]);

  async function respond(accept: boolean) {
    setBusy(true);
    try {
      const result = await shopApi.respond(token, accept);
      setResponded(result.message);
      setProforma((current) => (current ? { ...current, status: result.status, can_respond: false } : current));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send your answer");
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <main style={{ maxWidth: 720, margin: "10vh auto", padding: "0 16px" }}>
        <Alert>{error}</Alert>
      </main>
    );
  }

  if (!proforma) {
    return (
      <main style={{ maxWidth: 720, margin: "10vh auto", padding: "0 16px" }}>
        <p className="muted">Loading…</p>
      </main>
    );
  }

  const { currency } = proforma;
  const amount = (value: string | null) => (value === null ? "—" : money(value, currency));
  const phone = proforma.shop?.contact_phone?.replace(/[^\d+]/g, "");
  const title = proforma.status === "requested" ? "Proforma request" : "Proforma";
  const payment = proforma.payment ?? { state: null, items: [] };
  // A completed order says so; until then, where the money has got to says
  // more than "ready to accept" does.
  const badge =
    proforma.status === "converted" || proforma.status === "cancelled" ? null : paymentBadge(payment.state);
  const waiting = payment.state === "checking";
  const found = payment.items
    .filter((item) => item.status === "accepted")
    .reduce((sum, item) => sum + Number(item.amount_claimed ?? 0), 0);
  const owing =
    payment.state === "part_paid" && proforma.total_amount !== null
      ? (Number(proforma.total_amount) - found).toFixed(2)
      : null;

  return (
    <main style={{ maxWidth: 760, margin: "32px auto", padding: "0 16px 60px" }}>
      {justRequested && proforma.status === "requested" && (
        <Alert kind="ok">
          Thank you — your request {proforma.number} has reached {proforma.shop?.display_name ?? "the seller"}.
          Keep this link: your proforma will appear here once it is confirmed.
        </Alert>
      )}

      <div className="card">
        <div className="page-head">
          <div>
            <h1>
              {title} {proforma.number}
            </h1>
            <p>
              {proforma.status === "requested" ? "Requested" : "Issued"} {shortDate(proforma.issued_on)}
              {proforma.valid_until ? ` · valid until ${shortDate(proforma.valid_until)}` : ""}
            </p>
          </div>
          {badge ? (
            <span className={`badge ${badge.tone}`}>{badge.label}</span>
          ) : (
            <span className={`badge ${proformaTone(proforma.status)}`}>{proformaLabel(proforma.status)}</span>
          )}
        </div>

        {proforma.next_step && (
          <p className="next-step">{proforma.next_step}</p>
        )}

        <div className="grid" style={{ marginBottom: 14 }}>
          <div>
            <div className="label muted" style={{ fontSize: "0.78rem" }}>
              FROM
            </div>
            <strong>{proforma.seller.name}</strong>
            <div className="muted" style={{ fontSize: "0.88rem" }}>
              {[proforma.seller.address, proforma.seller.phone].filter(Boolean).join(" · ")}
              {proforma.seller.tin ? ` · TIN ${proforma.seller.tin}` : ""}
            </div>
          </div>
          <div>
            <div className="label muted" style={{ fontSize: "0.78rem" }}>
              FOR
            </div>
            <strong>{proforma.customer.company || proforma.customer.name}</strong>
            <div className="muted" style={{ fontSize: "0.88rem" }}>
              {[proforma.customer.phone, proforma.customer.delivery_location].filter(Boolean).join(" · ")}
            </div>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Qty</th>
                {proforma.amounts_visible && <th className="num">Unit price</th>}
                {proforma.amounts_visible && <th className="num">Total</th>}
              </tr>
            </thead>
            <tbody>
              {proforma.lines.map((line, index) => (
                <tr key={`${line.description}-${index}`}>
                  <td>{line.description}</td>
                  <td className="num">{Number(line.quantity).toLocaleString()}</td>
                  {proforma.amounts_visible && <td className="num">{amount(line.unit_price)}</td>}
                  {proforma.amounts_visible && <td className="num">{amount(line.line_total)}</td>}
                </tr>
              ))}
            </tbody>
            {proforma.amounts_visible && (
              <tfoot>
                <tr>
                  <td colSpan={3} className="num muted">
                    Subtotal
                  </td>
                  <td className="num">{amount(proforma.subtotal)}</td>
                </tr>
                {Number(proforma.discount_total) > 0 && (
                  <tr>
                    <td colSpan={3} className="num muted">
                      Discount
                    </td>
                    <td className="num">−{amount(proforma.discount_total)}</td>
                  </tr>
                )}
                {Number(proforma.tax_total) > 0 && (
                  <tr>
                    <td colSpan={3} className="num muted">
                      Tax
                    </td>
                    <td className="num">{amount(proforma.tax_total)}</td>
                  </tr>
                )}
                {Number(proforma.delivery_charge) > 0 && (
                  <tr>
                    <td colSpan={3} className="num muted">
                      Delivery
                    </td>
                    <td className="num">{amount(proforma.delivery_charge)}</td>
                  </tr>
                )}
                <tr>
                  <td colSpan={3} className="num">
                    <strong>{proforma.status === "requested" ? "Estimated total" : "Total"}</strong>
                  </td>
                  <td className="num">
                    <strong>{amount(proforma.total_amount)}</strong>
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
        {!proforma.amounts_visible && (
          <p className="muted" style={{ fontSize: "0.88rem" }}>
            Prices will appear here once the seller confirms your proforma.
          </p>
        )}

        {proforma.customer_message && (
          <p className="muted" style={{ fontSize: "0.88rem" }}>
            Your note: {proforma.customer_message}
          </p>
        )}
        {proforma.note && <p>{proforma.note}</p>}
        {proforma.terms && (
          <p className="muted" style={{ fontSize: "0.88rem" }}>
            {proforma.terms}
          </p>
        )}

        {responded ? (
          <Alert kind="ok">{responded}</Alert>
        ) : (
          proforma.can_respond && (
            <div className="row no-print" style={{ marginTop: 14 }}>
              <button type="button" disabled={busy} onClick={() => void respond(true)}>
                Accept this proforma
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={() => void respond(false)}>
                Not right now
              </button>
            </div>
          )
        )}

        <p className="muted" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
          {proforma.disclaimer}
        </p>
      </div>

      {/* Paying is a separate step from accepting: a buyer may accept and pay
          later, or pay first and accept on the same visit. Both are offered
          once the seller has sent a price. */}
      {/* What the buyer has sent, and what the seller said about it: this
          link is where they come back to find out. */}
      {payment.items.length > 0 && (
        <div className="card">
          <div className="card-title">Your payment</div>
          <ul className="plain-list" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {payment.items.map((item, index) => {
              const status = slipStatus(item.status);
              return (
                <li key={`${item.submitted_at}-${index}`} style={{ padding: "8px 0", borderTop: index ? "1px solid var(--border, #e5e7eb)" : undefined }}>
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
                    <strong>{item.amount_claimed ? money(item.amount_claimed, currency) : "Amount not given"}</strong>
                    <span className={`badge ${status.tone}`}>{status.label}</span>
                  </div>
                  <div className="muted" style={{ fontSize: "0.88rem" }}>
                    {[
                      item.method ? (METHODS[item.method] ?? item.method.replace(/_/g, " ")) : null,
                      item.reference ? `ref ${item.reference}` : null,
                      item.submitted_at ? `sent ${shortDate(item.submitted_at)}` : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                  {item.review_note && (
                    <div style={{ fontSize: "0.88rem" }}>The seller said: “{item.review_note}”</div>
                  )}
                </li>
              );
            })}
          </ul>
          {waiting && !another && !slipSent && proforma.can_send_payment && (
            <button type="button" className="secondary no-print" style={{ marginTop: 8 }} onClick={() => setAnother(true)}>
              Paid in two parts? Send another slip
            </button>
          )}
        </div>
      )}

      {proforma.can_send_payment && !slipSent && (!waiting || another) && (
        <PaymentSlipForm
          token={token}
          total={proforma.total_amount}
          owing={owing}
          currency={proforma.currency}
          shopName={proforma.shop?.display_name ?? proforma.seller.name}
          onSent={(message) => {
            setSlipSent(message);
            setAnother(false);
            // Read the page again, so the slip just sent is listed with the rest.
            setVersion((current) => current + 1);
          }}
        />
      )}
      {slipSent && (
        <div className="card no-print">
          <Alert kind="ok">{slipSent}</Alert>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setSlipSent(null);
              setAnother(true);
            }}
          >
            Send another slip
          </button>
        </div>
      )}

      {proforma.shop && (
        <div className="card no-print">
          <div className="card-title">Questions about this proforma?</div>
          <div className="row">
            {phone && (
              <a href={`tel:${phone}`} className="btn secondary">
                Call {proforma.shop.contact_phone}
              </a>
            )}
            {proforma.shop.telegram_username && (
              <a
                href={`https://t.me/${proforma.shop.telegram_username.replace(/^@/, "")}`}
                target="_blank"
                rel="noreferrer"
                className="btn secondary"
              >
                Message on Telegram
              </a>
            )}
            {proforma.shop.contact_email && (
              <a href={`mailto:${proforma.shop.contact_email}?subject=${encodeURIComponent(`Proforma ${proforma.number}`)}`} className="btn secondary">
                Email
              </a>
            )}
            <Link href={`/shop/${proforma.shop.slug}`} className="btn secondary">
              Back to {proforma.shop.display_name}
            </Link>
          </div>
        </div>
      )}

      <p className="muted no-print" style={{ textAlign: "center", fontSize: "0.82rem" }}>
        <button type="button" className="link" onClick={() => window.print()}>
          Print or save as PDF
        </button>
      </p>
    </main>
  );
}
