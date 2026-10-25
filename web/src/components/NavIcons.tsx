/**
 * The icons for the phone's bottom tab bar.
 *
 * Drawn here rather than pulled from an icon package: seven small outlines do
 * not justify a dependency, and a bar that waits on a sprite or an icon font
 * shows its labels jumping about on a slow connection — which is most of them.
 *
 * Each one is a 24×24 stroke in currentColor, so the tab the visitor is on
 * needs no second copy of the icon in the brand colour.
 */

import type { ReactNode } from "react";

export type NavIconName =
  | "home"
  | "sales"
  | "products"
  | "stock"
  | "shop"
  | "reports"
  | "more";

const PATHS: Record<NavIconName, ReactNode> = {
  home: (
    <>
      <path d="M3 10.6 12 3.4l9 7.2" />
      <path d="M5.4 9.4V20.6h13.2V9.4" />
      <path d="M10 20.6v-5.2h4v5.2" />
    </>
  ),
  // A receipt, torn off at the bottom.
  sales: (
    <>
      <path d="M6.5 3.4h11v17.2l-2.2-1.6-2.3 1.6-2.3-1.6-2.2 1.6V3.4Z" />
      <path d="M9.6 8.4h4.8M9.6 12h4.8" />
    </>
  ),
  products: (
    <>
      <path d="M20.5 12.4 12.4 20.5a1.6 1.6 0 0 1-2.3 0L3.5 13.9V3.5h10.4l6.6 6.6a1.6 1.6 0 0 1 0 2.3Z" />
      <circle cx="7.7" cy="7.7" r="1.2" />
    </>
  ),
  // A carton, seen from the corner.
  stock: (
    <>
      <path d="M12 3.6 20.4 8v8L12 20.4 3.6 16V8Z" />
      <path d="m3.6 8 8.4 4.4L20.4 8" />
      <path d="M12 12.4v8" />
    </>
  ),
  // A shopfront under its awning.
  shop: (
    <>
      <path d="M3.8 9.2h16.4l-1.3-5.4H5.1L3.8 9.2Z" />
      <path d="M5.4 9.2v11.4h13.2V9.2" />
      <path d="M10 20.6v-5.4h4v5.4" />
    </>
  ),
  reports: <path d="M5.4 20.6V11M12 20.6V4.4M18.6 20.6v-6.4" />,
  more: (
    <>
      <circle cx="5.2" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="18.8" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
};

export function NavIcon({ name }: { name: NavIconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
