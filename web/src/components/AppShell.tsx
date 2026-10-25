"use client";

/** The signed-in frame: short primary navigation and a session guard (PRD 7). */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { NavIcon } from "@/components/NavIcons";
import { getAdminToken } from "@/lib/admin";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

/**
 * Kept short on purpose, and in the order the PRD suggests for the web:
 * Home, Sales, Products, Stock, Online Shop, Reports and More. Each entry is
 * hidden unless the user may use it; everything else lives under More.
 *
 * `phone` marks the five the PRD suggests for a phone (7): Home, Sales, Stock,
 * Shop and More. The other two are not taken away — on a phone they step back
 * into More, which is what More is for. The icon is drawn only there, where
 * the bar sits at the bottom of the screen and a bare label is too thin a
 * thing to aim a thumb at.
 */
const NAV = [
  { href: "/", label: "Home", permission: null, icon: "home", phone: true },
  { href: "/sales", label: "Sales", permission: "sale:view", icon: "sales", phone: true },
  { href: "/products", label: "Products", permission: "product:view", icon: "products", phone: false },
  { href: "/stock", label: "Stock", permission: "stock:view", icon: "stock", phone: true },
  { href: "/shop", label: "Shop", permission: "shop:view", icon: "shop", phone: true },
  { href: "/reports", label: "Reports", permission: "report:sales", icon: "reports", phone: false },
  { href: "/more", label: "More", permission: null, icon: "more", phone: true },
] as const;

/** Routes reached from More, so the More tab stays highlighted while on them. */
const MORE_ROUTES = ["/more", "/credit", "/contacts", "/notifications", "/settings"];

export function AppShell({ children }: { children: ReactNode }) {
  const { session, loading, signOut, can } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [unread, setUnread] = useState(0);
  const [isOperator, setIsOperator] = useState(false);

  useEffect(() => {
    if (!loading && !session) router.replace("/sign-in");
  }, [loading, session, router]);

  /**
   * Show the way back to the console only to somebody who is signed in to it.
   *
   * A shop owner has no business seeing a link to the operator's console, and
   * would only click it and meet a sign-in that is not theirs. An operator who
   * went into a shop through support access, though, needs a way out —
   * otherwise the only route back is remembering the URL.
   *
   * Read in an effect because localStorage does not exist while rendering on
   * the server, and checked on each navigation in case they signed out of the
   * console in another tab.
   */
  useEffect(() => {
    setIsOperator(Boolean(getAdminToken()));
  }, [pathname]);

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
    <div className="shell has-tabbar">
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
          {isOperator && (
            <Link href="/admin" className="btn secondary console-link">
              Console
            </Link>
          )}
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

      <nav className="nav tabbar" aria-label="Primary">
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            data-phone={item.phone ? "yes" : "no"}
            aria-current={isCurrent(item.href) ? "page" : undefined}
          >
            <NavIcon name={item.icon} />
            <span>{item.label}</span>
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
