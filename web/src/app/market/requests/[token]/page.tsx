"use client";

/**
 * The buyer's tracking page for a cross-shop request.
 *
 * One row per shop: who has answered, what they quoted, and a link to that
 * shop's own proforma where the buyer accepts or declines. Acceptance is
 * per-shop on purpose — taking one price and leaving another is the whole
 * point of asking several.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { MarketShell } from "@/components/Market";
import { Alert, Empty } from "@/components/ui";
import { money } from "@/lib/format";
import { describeError } from "@/lib/session";
import { marketApi, requestStatusLabel, type MarketRequestView } from "@/lib/market";
import { proformaLabel, proformaTone } from "@/lib/storefront";

export default function MarketRequestPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [view, setView] = useState<MarketRequestView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setView(await marketApi.trackRequest(token));
      setError(null);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function withdraw() {
    if (!window.confirm("Withdraw this request? Shops that have not answered will be told.")) {
      return;
    }
    setBusy(true);
    try {
      setView(await marketApi.withdrawRequest(token));
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <MarketShell basketCount={0} shopCount={0} basketTotal={null} showBar={false}>
        <p className="muted">Loading your request…</p>
      </MarketShell>
    );
  }

  if (!view) {
    return (
      <MarketShell basketCount={0} shopCount={0} basketTotal={null} showBar={false}>
        {error ? <Alert>{error}</Alert> : null}
        <Empty title="This link is not valid">
          <p className="muted">
            Check the link, or <Link href="/market">start a new request</Link>.
          </p>
        </Empty>
      </MarketShell>
    );
  }

  const waiting = view.shop_count - view.answered_count;
  const canWithdraw = view.status === "open" && waiting > 0;

  return (
    <MarketShell basketCount={0} shopCount={0} basketTotal={null} showBar={false}>
      <nav className="crumbs">
        <Link href="/market">Marketplace</Link>
        {" / "}
        <span>{view.reference}</span>
      </nav>

      <h1>Request {view.reference}</h1>
      <p className="muted">
        {requestStatusLabel(view.status)} · {view.answered_count} of {view.shop_count}{" "}
        shop{view.shop_count === 1 ? "" : "s"} answered
      </p>

      {error ? <Alert>{error}</Alert> : null}

      {view.status === "open" && waiting > 0 ? (
        <Alert kind="warn">
          {waiting} shop{waiting === 1 ? " has" : "s have"} not replied yet. Keep
          this link — it updates as they answer. Nothing has been ordered.
        </Alert>
      ) : null}

      <ul className="request-shops">
        {view.shops.map((row) => (
          <li key={row.number} className="request-shop">
            <div className="request-shop-head">
              <div>
                <strong>{row.shop}</strong>
                <span className="muted small">
                  {" "}
                  · {row.item_count} item{row.item_count === 1 ? "" : "s"} · {row.number}
                </span>
              </div>
              <span className={`badge ${proformaTone(row.status)}`}>
                {proformaLabel(row.status)}
              </span>
            </div>

            <div className="request-shop-body">
              {row.answered && row.total_amount ? (
                <p className="price">
                  {money(row.total_amount)}
                  <span className="muted small"> {row.currency}</span>
                  {row.valid_until ? (
                    <span className="muted small"> · valid until {row.valid_until}</span>
                  ) : null}
                </p>
              ) : row.status === "requested" ? (
                <p className="muted">Waiting for this shop to price it.</p>
              ) : (
                <p className="muted">No price from this shop.</p>
              )}

              {row.token ? (
                <Link href={`/q/${row.token}`} className="btn">
                  {row.status === "sent" ? "See and accept" : "Open proforma"}
                </Link>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      {view.delivery_location || view.message ? (
        <section className="request-details">
          <h2>What you told them</h2>
          {view.delivery_location ? (
            <p>
              <span className="muted">Deliver to:</span> {view.delivery_location}
            </p>
          ) : null}
          {view.message ? (
            <p>
              <span className="muted">Note:</span> {view.message}
            </p>
          ) : null}
        </section>
      ) : null}

      {canWithdraw ? (
        <button type="button" className="btn ghost" onClick={withdraw} disabled={busy}>
          {busy ? "Withdrawing…" : "Withdraw this request"}
        </button>
      ) : null}

      <p className="disclaimer">
        This is a request for prices, not an order. Nothing is reserved, and no
        stock moves until you accept a shop&apos;s quotation and they confirm
        the sale.
      </p>
    </MarketShell>
  );
}
