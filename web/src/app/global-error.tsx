"use client";

/**
 * The last resort: a failure in the root layout itself, where the ordinary
 * error screen cannot render because the page shell is what broke.
 *
 * It has to carry its own <html> and <body>, and it cannot rely on the app's
 * stylesheet having loaded, so the few styles it needs are inline.
 */

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
          margin: 0,
          padding: "48px 16px",
          background: "#f6f7f9",
          color: "#16202c",
        }}
      >
        <div style={{ maxWidth: 520, margin: "0 auto" }}>
          <h1 style={{ fontSize: "1.3rem", marginTop: 0 }}>Estock could not start this page</h1>
          <p style={{ color: "#5b6876" }}>
            This is a fault in the app rather than anything you did. Reloading usually
            clears it.
          </p>
          <pre
            style={{
              background: "#fbeae9",
              color: "#b3261e",
              padding: 12,
              borderRadius: 8,
              whiteSpace: "pre-wrap",
              fontSize: "0.85rem",
            }}
          >
            {error.message || "No message was given."}
            {error.digest ? `\nReference ${error.digest}` : ""}
          </pre>
          <button
            type="button"
            onClick={reset}
            style={{
              background: "#0f766e",
              color: "#fff",
              border: 0,
              borderRadius: 8,
              padding: "10px 16px",
              fontSize: "1rem",
              cursor: "pointer",
            }}
          >
            Reload
          </button>
        </div>
      </body>
    </html>
  );
}
