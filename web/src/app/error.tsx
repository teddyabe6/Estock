"use client";

/**
 * What a visitor sees when a screen fails.
 *
 * Without this, a thrown error leaves a blank page in production and a stack
 * of framework frames in development — neither of which tells anyone what
 * happened or what to do. A shopper who loses their basket page should be
 * able to get back to shopping in one click, and whoever is on support should
 * be able to read the actual message rather than guess at it.
 */

import Link from "next/link";
import { useEffect } from "react";

export default function ErrorScreen({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // The browser console keeps the real stack even when the page shows the
    // friendly version, so a bug report has something to quote.
    console.error("Screen failed:", error);
  }, [error]);

  return (
    <div className="auth">
      <div className="card">
        <h1>Something went wrong on this page</h1>
        <p className="sub">
          Nothing you have done is lost — your basket and any request you have already
          sent are safe. Try again, and if it keeps happening the message below is what
          to report.
        </p>

        <div className="alert error" role="alert">
          {error.message || "The page stopped unexpectedly."}
          {error.digest && (
            <div className="muted" style={{ marginTop: 6, fontSize: "0.82rem" }}>
              Reference {error.digest}
            </div>
          )}
        </div>

        <div className="row">
          <button type="button" onClick={reset}>
            Try again
          </button>
          <Link href="/market" className="btn secondary">
            Back to the marketplace
          </Link>
        </div>
      </div>
    </div>
  );
}
