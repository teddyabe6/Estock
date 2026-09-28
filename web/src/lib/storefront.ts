/**
 * The public shop: types, calls and the visitor's basket.
 *
 * Nothing here needs a sign-in. The basket lives in the visitor's browser and
 * reserves nothing; it only becomes a numbered proforma request when they
 * check out, and even then stock moves only when the seller converts the
 * proforma to a sale (PRD 13, 14).
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { request } from "@/lib/api";

export type Shop = {
  slug: string;
  display_name: string;
  tagline: string | null;
  about: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  telegram_username: string | null;
  address: string | null;
  currency: string;
  show_prices: boolean;
  checkout_note: string | null;
  categories: string[];
};

export type PublicVariant = {
  id: string;
  name: string | null;
  is_default: boolean;
  price: string | null;
  in_stock: boolean;
};

export type PublicProduct = {
  id: string;
  name: string;
  description: string | null;
  brand: string | null;
  category: string | null;
  unit_of_measure: string;
  price: string | null;
  in_stock: boolean;
  image_url: string | null;
  variants: PublicVariant[];
};

export type ProformaRequestResult = {
  number: string;
  status: string;
  token: string;
  url: string;
  item_count: number;
  total_amount: string | null;
  currency: string;
  message: string;
};

export type ProformaView = {
  number: string;
  status: string;
  next_step: string;
  can_respond: boolean;
  amounts_visible: boolean;
  issued_on: string;
  valid_until: string | null;
  seller: { name: string | null; phone: string | null; address: string | null; tin: string | null };
  shop: {
    slug: string;
    display_name: string;
    contact_phone: string | null;
    contact_email: string | null;
    telegram_username: string | null;
  } | null;
  customer: {
    name: string;
    phone: string | null;
    company: string | null;
    delivery_location: string | null;
  };
  customer_message: string | null;
  currency: string;
  subtotal: string | null;
  discount_total: string | null;
  tax_total: string | null;
  delivery_charge: string | null;
  total_amount: string | null;
  terms: string | null;
  note: string | null;
  lines: Array<{
    description: string;
    quantity: string;
    unit_price: string | null;
    discount_amount: string | null;
    tax_amount: string | null;
    line_total: string | null;
  }>;
  disclaimer: string;
};

function qs(params: Record<string, string | number | undefined>): string {
  const pairs = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== "")
    .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`);
  return pairs.length ? `?${pairs.join("&")}` : "";
}

export const shopApi = {
  shop: (slug: string) => request<Shop>(`/public/shops/${slug}`, { anonymous: true }),
  products: (slug: string, params: { q?: string; category?: string; limit?: number; offset?: number } = {}) =>
    request<{ items: PublicProduct[]; total: number }>(`/public/shops/${slug}/products${qs(params)}`, {
      anonymous: true,
    }),
  product: (slug: string, id: string) =>
    request<PublicProduct & { currency: string }>(`/public/shops/${slug}/products/${id}`, {
      anonymous: true,
    }),
  requestProforma: (slug: string, body: Record<string, unknown>) =>
    request<ProformaRequestResult>(`/public/shops/${slug}/proforma-requests`, {
      method: "POST",
      anonymous: true,
      body,
    }),
  enquire: (slug: string, body: Record<string, unknown>) =>
    request<{ reference: string }>(`/public/shops/${slug}/enquiries`, {
      method: "POST",
      anonymous: true,
      body,
    }),
  quotation: (token: string) =>
    request<ProformaView>(`/public/quotations/${token}`, { anonymous: true }),
  respond: (token: string, accept: boolean) =>
    request<{ message: string; status: string }>(`/public/quotations/${token}/respond?accept=${accept}`, {
      method: "POST",
      anonymous: true,
    }),
};

/** A variant a visitor can add straight from a product card. */
export function defaultVariant(product: PublicProduct): PublicVariant | null {
  return product.variants.find((v) => v.is_default) ?? product.variants[0] ?? null;
}

// --------------------------------------------------------------------------- //
// Basket
// --------------------------------------------------------------------------- //

export type BasketLine = {
  variantId: string;
  productId: string;
  name: string;
  variantName: string | null;
  unit: string;
  price: string | null;
  imageUrl: string | null;
  quantity: number;
};

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Private mode or a full store: the basket simply does not persist.
  }
}

export function useBasket(slug: string) {
  const key = `estock.basket.${slug}`;
  const [lines, setLines] = useState<BasketLine[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLines(readJson<BasketLine[]>(key, []));
    setLoaded(true);
  }, [key]);

  const persist = useCallback(
    (next: BasketLine[]) => {
      setLines(next);
      writeJson(key, next);
    },
    [key],
  );

  const add = useCallback(
    (line: Omit<BasketLine, "quantity">, quantity = 1) => {
      const current = readJson<BasketLine[]>(key, []);
      const existing = current.find((l) => l.variantId === line.variantId);
      const next = existing
        ? current.map((l) =>
            l.variantId === line.variantId ? { ...l, ...line, quantity: round(l.quantity + quantity) } : l,
          )
        : [...current, { ...line, quantity: round(quantity) }];
      persist(next);
    },
    [key, persist],
  );

  const setQuantity = useCallback(
    (variantId: string, quantity: number) => {
      const current = readJson<BasketLine[]>(key, []);
      const next =
        quantity <= 0
          ? current.filter((l) => l.variantId !== variantId)
          : current.map((l) => (l.variantId === variantId ? { ...l, quantity: round(quantity) } : l));
      persist(next);
    },
    [key, persist],
  );

  const remove = useCallback((variantId: string) => setQuantity(variantId, 0), [setQuantity]);
  const clear = useCallback(() => persist([]), [persist]);

  const count = useMemo(() => lines.reduce((sum, l) => sum + l.quantity, 0), [lines]);
  const total = useMemo(() => {
    if (lines.length === 0 || lines.some((l) => l.price === null)) return null;
    return lines.reduce((sum, l) => sum + Number(l.price) * l.quantity, 0);
  }, [lines]);

  const quantityOf = useCallback(
    (variantId: string) => lines.find((l) => l.variantId === variantId)?.quantity ?? 0,
    [lines],
  );

  return { lines, loaded, count, total, add, setQuantity, remove, clear, quantityOf };
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

// --------------------------------------------------------------------------- //
// The visitor's own requests, so they can find their proforma again
// --------------------------------------------------------------------------- //

export type RememberedRequest = { number: string; token: string; at: string };

export function useMyRequests(slug: string) {
  const key = `estock.requests.${slug}`;
  const [items, setItems] = useState<RememberedRequest[]>([]);

  useEffect(() => {
    setItems(readJson<RememberedRequest[]>(key, []));
  }, [key]);

  const remember = useCallback(
    (entry: Omit<RememberedRequest, "at">) => {
      const current = readJson<RememberedRequest[]>(key, []).filter((r) => r.token !== entry.token);
      const next = [{ ...entry, at: new Date().toISOString() }, ...current].slice(0, 20);
      setItems(next);
      writeJson(key, next);
    },
    [key],
  );

  return { items, remember };
}

export function proformaTone(status: string): "ok" | "warn" | "danger" | "muted" {
  switch (status) {
    case "requested":
      return "warn";
    case "sent":
    case "accepted":
    case "converted":
      return "ok";
    case "expired":
      return "danger";
    default:
      return "muted";
  }
}

export function proformaLabel(status: string): string {
  switch (status) {
    case "requested":
      return "Waiting for the seller";
    case "sent":
      return "Ready to accept";
    case "accepted":
      return "Accepted";
    case "declined":
      return "Declined";
    case "expired":
      return "Expired";
    case "converted":
      return "Completed";
    case "draft":
      return "Draft";
    default:
      return status.replace(/_/g, " ");
  }
}
