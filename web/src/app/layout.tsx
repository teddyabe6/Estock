import type { Metadata } from "next";

import { StackedTables } from "@/components/StackedTables";
import { SessionProvider } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "Estock",
  description:
    "Shop management, inventory, sales, credit and online catalogue for Ethiopian businesses.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Browser extensions write their own attributes onto <html> and <body>
  // before React starts (LastPass: data-lastpass-safe-prompts-active;
  // Grammarly: data-gr-ext-installed), and React then reports the page as not
  // matching what the server sent. suppressHydrationWarning ignores that for
  // these two tags' own attributes only; everything inside is still checked.
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <SessionProvider>{children}</SessionProvider>
        <StackedTables />
      </body>
    </html>
  );
}
