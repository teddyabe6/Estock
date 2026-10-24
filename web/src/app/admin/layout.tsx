import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AdminProvider } from "@/lib/adminSession";

export const metadata: Metadata = {
  title: "Estock Platform",
  description: "Operator console: shops, subscriptions, billing and activity.",
};

/**
 * The console gets its own provider so the operator's identity never touches
 * the shop session that may be open in the same browser.
 */
export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AdminProvider>{children}</AdminProvider>;
}
