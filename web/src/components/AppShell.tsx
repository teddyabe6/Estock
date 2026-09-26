"use client";

/** The signed-in frame: short primary navigation and a session guard (PRD 7). */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

/**
 * Kept short on purpose, and in the order the PRD suggests for the web:
 * Home, Sales, Products, Stock, Online Shop, Reports and More. Each entry is
 * hidden unless the user may use it; everything else lives under More.
 */
const NAV = [
  { href: "/", label: "Home", permission: null },
  { href: "/sales", label: "Sales", permission: "sale:view" },
  { href: "/products", label: "Products", permission: "product:view" },
  { href: "/stock", label: "Stock", permission: "stock:view" },
  { href: "/shop", label: "Shop", permission: "shop:view" },
  { href: "/reports", label: "Reports", permission: "report:sales" },
  { href: "/more", label: "More", permission: null },
] as const;

/** Routes reached from More, so the More tab stays highlighted while on them. */
const MORE_ROUTES = ["/more", "/credit", "/contacts", "/notifications", "/settings"];

export function AppShell({ children }: { children: ReactNode }) {
  const { session, loading, signOut, can } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!loading && !session) router.replace("/sign-in");
  }, [loading, session, router]);

  // The unread badge: a light poll, so a reminder or an enquiry shows up
  // without a page reload (PRD 11.4 — in-app is the first channel).
  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    const poll = () =>
      api
        .notifications({ unread_only: true, limit: 1 })
        .then((page) => {
          if (!cancelled) setUnread(page.unread);
        })
        .catch(() => undefined);
    void poll();
    const timer = setInterval(poll, 60_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [session, pathname]);

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
  const isCurrent = (href: string) => {
    if (href === "/") return pathname === "/";
    if (href === "/more") return MORE_ROUTES.some((route) => pathname.startsWith(route));
    return pathname.startsWith(href);
  };

  return (
    <div className="shell">
      <header className="topbar">
        <Link href="/" className="brand">
          {session.tenant_name}
        </Link>
        <div className="row">
          <Link
            href="/notifications"
            className="bell"
            aria-label={unread ? `${unread} unread notifications` : "Notifications"}
          >
            <span aria-hidden>🔔</span>
            {unread > 0 && <span className="bell-count">{unread > 99 ? "99+" : unread}</span>}
          </Link>
          <div className="who">
            {session.user.full_name}
            <br />
            <span className="muted">
              {session.is_support ? "support (read-only)" : session.role.replace("_", " ")}
            </span>
          </div>
          <button type="button" className="secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      <nav className="nav" aria-label="Primary">
        {items.map((item) => (
          <Link key={item.href} href={item.href} aria-current={isCurrent(item.href) ? "page" : undefined}>
            {item.label}
          </Link>
        ))}
      </nav>

      {session.is_support && (
        <div style={{ padding: "0 var(--gutter)", marginTop: 12 }}>
          <div className="alert warn" role="status">
            Platform support session: you can look at this business but not change anything.
            The access is recorded in the business&apos;s audit log.
          </div>
        </div>
      )}

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
