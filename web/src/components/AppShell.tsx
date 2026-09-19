"use client";

/** The signed-in frame: short primary navigation and a session guard (PRD 7). */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useSession } from "@/lib/session";

/** Kept short on purpose; each entry is hidden unless the user may use it. */
const NAV = [
  { href: "/", label: "Home", permission: null },
  { href: "/sales", label: "Sales", permission: "sale:view" },
  { href: "/products", label: "Products", permission: "product:view" },
  { href: "/stock", label: "Stock", permission: "stock:view" },
  { href: "/credit", label: "Credit", permission: "credit:view" },
  { href: "/reports", label: "Reports", permission: "report:sales" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const { session, loading, signOut, can } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !session) router.replace("/sign-in");
  }, [loading, session, router]);

  if (loading) {
    return (
      <div className="shell">
        <main>
          <p className="muted">Loading…</p>
        </main>
      </div>
    );
  }

  if (!session) return null;

  const items = NAV.filter((item) => !item.permission || can(item.permission));

  return (
    <div className="shell">
      <header className="topbar">
        <Link href="/" className="brand">
          {session.tenant_name}
        </Link>
        <div className="row">
          <div className="who">
            {session.user.full_name}
            <br />
            <span className="muted">{session.role.replace("_", " ")}</span>
          </div>
          <button type="button" className="secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      <nav className="nav" aria-label="Primary">
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={
              pathname === item.href ||
              (item.href !== "/" && pathname.startsWith(item.href))
                ? "page"
                : undefined
            }
          >
            {item.label}
          </Link>
        ))}
      </nav>

      {session.subscription.read_only && (
        <div style={{ padding: "0 var(--gutter)", marginTop: 12 }}>
          <div className="alert warn" role="status">
            {session.subscription.message ??
              "This account is read-only. Your data is safe — subscribe to record new transactions."}
          </div>
        </div>
      )}

      <main>{children}</main>
    </div>
  );
}
