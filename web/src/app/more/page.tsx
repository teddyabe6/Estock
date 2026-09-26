"use client";

import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { PageHead } from "@/components/ui";
import { useSession } from "@/lib/session";

/** Everything that does not earn a place in the primary navigation (PRD 7). */
export default function MorePage() {
  return (
    <AppShell>
      <More />
    </AppShell>
  );
}

function More() {
  const { session, can, signOut } = useSession();
  const items = [
    {
      href: "/credit",
      label: "Credit",
      sub: "Receivables, payables, payments and follow-up",
      show: can("credit:view"),
    },
    {
      href: "/contacts",
      label: "Customers & suppliers",
      sub: "Contact details, history and balances",
      show: can("customer:view") || can("supplier:view"),
    },
    {
      href: "/notifications",
      label: "Notifications",
      sub: "Reminders, low-stock alerts and new enquiries",
      show: true,
    },
    {
      href: "/settings",
      label: "Settings",
      sub: "Business details, branches, team, pricing and subscription",
      show: can("business:view"),
    },
  ].filter((item) => item.show);

  return (
    <>
      <PageHead
        title="More"
        subtitle={session ? `${session.user.full_name} · ${session.role.replace("_", " ")}` : ""}
      />
      <div className="card">
        <ul className="menu-list">
          {items.map((item) => (
            <li key={item.href}>
              <Link href={item.href}>
                {item.label}
                <span className="sub">{item.sub}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
      <div className="card">
        <button type="button" className="secondary" onClick={signOut}>
          Sign out
        </button>
      </div>
    </>
  );
}
