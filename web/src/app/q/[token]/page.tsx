"use client";

/**
 * A shared proforma, viewed by the customer. It is explicitly not a receipt,
 * and accepting it records intent only — no sale, no stock movement (PRD 14).
 */

import { use, useEffect, useState } from "react";

import { Alert } from "@/components/ui";
import { request } from "@/lib/api";
import { money, shortDate } from "@/lib/format";

type Proforma = {
  number: string;
  status: string;
  issued_on: string;
  valid_until: string | null;
  seller: { name: string | null; phone: string | null; address: string | null; tin: string | null };
  customer: {
    name: string;
    phone: string | null;
    company: string | null;
    delivery_location: string | null;
  };
  currency: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  delivery_charge: string;
  total_amount: string;
  terms: string | null;
  note: string | null;
  lines: Array<{
    description: string;
    quantity: string;
    unit_price: string;
    discount_amount: string;
    tax_amount: string;
    line_total: string;
  }>;
  disclaimer: string;
};

export default function ProformaPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [proforma, setProforma] = useState<Proforma | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [responded, setResponded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request<Proforma>(`/public/quotations/${token}`, { anonymous: true })
      .then(setProforma)
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "This link is no longer valid"),
      );
  }, [token]);

  async function respond(accept: boolean) {
    setBusy(true);
    try {
      const result = await request<{ message: string; status: string }>(
        `/public/quotations/${token}/respond?accept=${accept}`,
        { method: "POST", anonymous: true },
      );
      setResponded(result.message);
      setProforma((current) =>
        current ? { ...current, status: result.status } : current,
      );
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

  const open = proforma.status === "sent" || proforma.status === "draft";

  return (
    <main style={{ maxWidth: 760, margin: "32px auto", padding: "0 16px 60px" }}>
      <div className="card">
        <div className="page-head">
          <div>
            <h1>Proforma {proforma.number}</h1>
            <p>
              Issued {shortDate(proforma.issued_on)}
              {proforma.valid_until
                ? ` · valid until ${shortDate(proforma.valid_until)}`
                : ""}
            </p>
          </div>
          <span className={`badge ${proforma.status === "accepted" ? "ok" : ""}`}>
            {proforma.status.replace(/_/g, " ")}
          </span>
        </div>

        <div className="grid" style={{ marginBottom: 14 }}>
          <div>
            <div className="label muted" style={{ fontSize: "0.78rem" }}>
              FROM
            </div>
            <strong>{proforma.seller.name}</strong>
            <div className="muted" style={{ fontSize: "0.88rem" }}>
              {[proforma.seller.address, proforma.seller.phone]
                .filter(Boolean)
                .join(" · ")}
              {proforma.seller.tin ? ` · TIN ${proforma.seller.tin}` : ""}
            </div>
          </div>
          <div>
            <div className="label muted" style={{ fontSize: "0.78rem" }}>
              FOR
            </div>
            <strong>{proforma.customer.company || proforma.customer.name}</strong>
            <div className="muted" style={{ fontSize: "0.88rem" }}>
              {[proforma.customer.phone, proforma.customer.delivery_location]
                .filter(Boolean)
                .join(" · ")}
            </div>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Qty</th>
                <th className="num">Unit price</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {proforma.lines.map((line, index) => (
                <tr key={`${line.description}-${index}`}>
                  <td>{line.description}</td>
                  <td className="num">{line.quantity}</td>
                  <td className="num">{money(line.unit_price, proforma.currency)}</td>
                  <td className="num">{money(line.line_total, proforma.currency)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3} className="num muted">
                  Subtotal
                </td>
                <td className="num">{money(proforma.subtotal, proforma.currency)}</td>
              </tr>
              {Number(proforma.discount_total) > 0 && (
                <tr>
                  <td colSpan={3} className="num muted">
                    Discount
                  </td>
                  <td className="num">
                    −{money(proforma.discount_total, proforma.currency)}
                  </td>
                </tr>
              )}
              {Number(proforma.tax_total) > 0 && (
                <tr>
                  <td colSpan={3} className="num muted">
                    Tax
                  </td>
                  <td className="num">{money(proforma.tax_total, proforma.currency)}</td>
                </tr>
              )}
              {Number(proforma.delivery_charge) > 0 && (
                <tr>
                  <td colSpan={3} className="num muted">
                    Delivery
                  </td>
                  <td className="num">
                    {money(proforma.delivery_charge, proforma.currency)}
                  </td>
                </tr>
              )}
              <tr>
                <td colSpan={3} className="num">
                  <strong>Total</strong>
                </td>
                <td className="num">
                  <strong>{money(proforma.total_amount, proforma.currency)}</strong>
                </td>
              </tr>
            </tfoot>
          </table>
        </div>

        {proforma.terms && (
          <p className="muted" style={{ fontSize: "0.88rem" }}>
            {proforma.terms}
          </p>
        )}

        {responded ? (
          <Alert kind="ok">{responded}</Alert>
        ) : (
          open && (
            <div className="row" style={{ marginTop: 14 }}>
              <button type="button" disabled={busy} onClick={() => void respond(true)}>
                Accept this quotation
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => void respond(false)}
              >
                Not right now
              </button>
            </div>
          )
        )}

        <p className="muted" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
          {proforma.disclaimer}
        </p>
      </div>

      <p className="muted" style={{ textAlign: "center", fontSize: "0.82rem" }}>
        <button type="button" className="link" onClick={() => window.print()}>
          Print or save as PDF
        </button>
      </p>
    </main>
  );
}
