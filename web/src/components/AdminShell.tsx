"use client";

/**
 * The platform console frame.
 *
 * Marked clearly as the operator's console rather than a shop, because the two
 * can be open in the same browser at once and confusing them would be
 * expensive: a status change here shuts a real business out.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAdmin } from "@/lib/adminSession";

const NAV = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/shops", label: "Shops" },
  { href: "/admin/billing", label: "Billing" },
  { href: "/admin/plans", label: "Plans" },
  { href: "/admin/settings", label: "Settings" },
  { href: "/admin/audit", label: "Activity" },
] as const;

export function AdminShell({ children }: { children: ReactNode }) {
  const { admin, loading, signOut } = useAdmin();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !admin) router.replace("/admin/sign-in");
  }, [loading, admin, router]);

  if (loading) {
    return (
      <div className="shell admin">
        <main>
          <p className="muted">Loading…</p>
        </main>
      </div>
    );
  }
  if (!admin) return null;

  const isCurrent = (href: string) =>
    href === "/admin" ? pathname === "/admin" : pathname.startsWith(href);

  return (
    <div className="shell admin">
      <header className="topbar">
        <div className="store-brand">
          <Link href="/admin" className="brand">
            Estock Platform
          </Link>
          <div className="who">Operator console</div>
        </div>
        <div className="row">
          <div className="who">
            {admin.full_name}
            <br />
            <span className="muted">{admin.email}</span>
          </div>
          <button type="button" className="secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      <nav className="nav" aria-label="Platform">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isCurrent(item.href) ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <main>{children}</main>

      <footer className="store-footer no-print">
        <div>
          You are signed in as the platform operator, not as a shop. Everything you
          change here is recorded in the affected shop&apos;s own audit log.
        </div>
      </footer>
    </div>
  );
}

/** A shop's status as a coloured word, with what it means on hover. */
export function ShopStatus({ status, note }: { status: string; note?: string }) {
  const tone =
    status === "active"
      ? "ok"
      : status === "trial"
        ? "warn"
        : status === "restricted"
          ? "warn"
          : "danger";
  return (
    <span className={`badge ${tone}`} title={note}>
      {status}
    </span>
  );
}

/** An invoice's derived status as a coloured word. */
export function InvoiceStatus({ status }: { status: string }) {
  const tone =
    status === "paid"
      ? "ok"
      : status === "overdue"
        ? "danger"
        : status === "void"
          ? "muted"
          : "warn";
  return <span className={`badge ${tone}`}>{status.replace(/_/g, " ")}</span>;
}
