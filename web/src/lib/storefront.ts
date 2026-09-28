/**
 * The public side: the marketplace, each shop's page, the visitor's cart and
 * the two ways to check out.
 *
 * Nothing here needs a sign-in. The cart lives in the visitor's browser and
 * reserves nothing. Checking out places one order per shop; requesting a
 * proforma sends each chosen shop its own request. Stock moves only when a
 * shop completes an order or converts a proforma (PRD 13, 14).
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { request } from "@/lib/api";

export type ShopSummary = {
  slug: string;
  display_name: string;
  accepts_orders: boolean;
  show_prices: boolean;
};

export type Shop = ShopSummary & {
  tagline: string | null;
  about: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  telegram_username: string | null;
  address: string | null;
  currency: string;
  checkout_note: string | null;
  categories: string[];
};

export type MarketShop = ShopSummary & {
  tagline: string | null;
  address: string | null;
  telegram_username: string | null;
  product_count: number;
  categories: string[];
};

export type Market = { shops: MarketShop[]; categories: string[]; currency: string };

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
  shop: ShopSummary;
};

export type MarketQuery = {
  q?: string;
  category?: string;
  shop?: string;
  min_price?: string;
  max_price?: string;
  in_stock?: boolean;
  sort?: "name" | "price_asc" | "price_desc" | "newest";
  limit?: number;
  offset?: number;
};

export type CheckoutPart = {
  kind: "order" | "proforma";
  shop: {
    slug: string;
    display_name: string;
    contact_phone: string | null;
    contact_email: string | null;
    telegram_username: string | null;
  } | null;
  number: string;
  status: string;
  next_step: string;
  currency: string;
  total_amount: string | null;
  lines: Array<{ description: string; quantity: string; unit_price: string | null; line_total: string | null }>;
  // order parts
  can_cancel?: boolean;
  token?: string;
  payment_method?: string;
  delivery_method?: string;
  delivery_location?: string | null;
  seller_note?: string | null;
  subtotal?: string;
  tax_total?: string;
  delivery_charge?: string;
  // proforma parts
  url?: string;
  amounts_visible?: boolean;
};

export type CheckoutView = {
  token: string;
  kind: "order" | "proforma";
  created_at: string;
  customer: {
    name: string;
    phone: string;
    company: string | null;
    delivery_location: string | null;
    message: string | null;
  };
  parts: CheckoutPart[];
};

export type CheckoutResult = {
  token: string;
  url: string;
  kind: "order" | "proforma";
  parts: Array<{ kind: string; shop: { slug: string; display_name: string } | null; number: string; status: string }>;
  message: string;
};

export type ProformaView = {
  number: string;
  status: string;
  next_step: string;
  can_respond: boolean;
  amounts_visible: boolean;
  tracking_url: string | null;
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

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const pairs = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== "" && value !== false)
    .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`);
  return pairs.length ? `?${pairs.join("&")}` : "";
}

const anon = { anonymous: true } as const;

export const shopApi = {
  market: () => request<Market>("/public/market", anon),
  marketProducts: (params: MarketQuery = {}) =>
    request<{ items: PublicProduct[]; total: number }>(`/public/market/products${qs(params)}`, anon),
  shop: (slug: string) => request<Shop>(`/public/shops/${slug}`, anon),
  products: (slug: string, params: { q?: string; category?: string; limit?: number; offset?: number } = {}) =>
    request<{ items: PublicProduct[]; total: number }>(`/public/shops/${slug}/products${qs(params)}`, anon),
  product: (slug: string, id: string) =>
    request<PublicProduct & { currency: string }>(`/public/shops/${slug}/products/${id}`, anon),
  enquire: (slug: string, body: Record<string, unknown>) =>
    request<{ reference: string }>(`/public/shops/${slug}/enquiries`, { method: "POST", ...anon, body }),
  checkoutOrders: (body: Record<string, unknown>) =>
    request<CheckoutResult>("/public/checkout/orders", { method: "POST", ...anon, body }),
  checkoutProformas: (body: Record<string, unknown>) =>
    request<CheckoutResult>("/public/checkout/proforma-requests", { method: "POST", ...anon, body }),
  track: (token: string) => request<CheckoutView>(`/public/checkout/${token}`, anon),
  cancelOrder: (token: string, reason?: string) =>
    request<{ number: string; status: string; message: string }>(`/public/orders/${token}/cancel`, {
      method: "POST",
      ...anon,
      body: { reason: reason || undefined },
    }),
  quotation: (token: string) => request<ProformaView>(`/public/quotations/${token}`, anon),
  respond: (token: string, accept: boolean) =>
    request<{ message: string; status: string }>(`/public/quotations/${token}/respond?accept=${accept}`, {
      method: "POST",
      ...anon,
    }),
};

/** A variant a visitor can add straight from a product card. */
export function defaultVariant(product: PublicProduct): PublicVariant | null {
  return product.variants.find((v) => v.is_default) ?? product.variants[0] ?? null;
}

// --------------------------------------------------------------------------- //
// The cart, across shops
// --------------------------------------------------------------------------- //

export type CartLine = {
  variantId: string;
  productId: string;
  name: string;
  variantName: string | null;
  unit: string;
  price: string | null;
  imageUrl: string | null;
  quantity: number;
  shop: ShopSummary;
};

export type CartGroup = { shop: ShopSummary; lines: CartLine[]; total: number | null };

const CART_KEY = "estock.cart";
const CART_EVENT = "estock:cart";

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
    // Private mode or a full store: the cart simply does not persist.
  }
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

export function groupByShop(lines: CartLine[]): CartGroup[] {
  const groups = new Map<string, CartGroup>();
  for (const line of lines) {
    const group = groups.get(line.shop.slug) ?? { shop: line.shop, lines: [], total: 0 };
    group.lines.push(line);
    if (group.total !== null) {
      group.total = line.price === null ? null : group.total + Number(line.price) * line.quantity;
    }
    groups.set(line.shop.slug, group);
  }
  return [...groups.values()];
}

export function useCart() {
  const [lines, setLines] = useState<CartLine[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const sync = () => setLines(readJson<CartLine[]>(CART_KEY, []));
    sync();
    setLoaded(true);
    window.addEventListener(CART_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CART_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const persist = useCallback((next: CartLine[]) => {
    writeJson(CART_KEY, next);
    window.dispatchEvent(new Event(CART_EVENT));
  }, []);

  const add = useCallback(
    (line: Omit<CartLine, "quantity">, quantity = 1) => {
      const current = readJson<CartLine[]>(CART_KEY, []);
      const existing = current.find((l) => l.variantId === line.variantId);
      persist(
        existing
          ? current.map((l) =>
              l.variantId === line.variantId ? { ...l, ...line, quantity: round(l.quantity + quantity) } : l,
            )
          : [...current, { ...line, quantity: round(quantity) }],
      );
    },
    [persist],
  );

  const setQuantity = useCallback(
    (variantId: string, quantity: number) => {
      const current = readJson<CartLine[]>(CART_KEY, []);
      persist(
        quantity <= 0
          ? current.filter((l) => l.variantId !== variantId)
          : current.map((l) => (l.variantId === variantId ? { ...l, quantity: round(quantity) } : l)),
      );
    },
    [persist],
  );

  const remove = useCallback((variantId: string) => setQuantity(variantId, 0), [setQuantity]);
  const removeShop = useCallback(
    (slug: string) => persist(readJson<CartLine[]>(CART_KEY, []).filter((l) => l.shop.slug !== slug)),
    [persist],
  );
  const clear = useCallback(() => persist([]), [persist]);

  const count = useMemo(() => lines.reduce((sum, l) => sum + l.quantity, 0), [lines]);
  const total = useMemo(() => {
    if (lines.length === 0 || lines.some((l) => l.price === null)) return null;
    return lines.reduce((sum, l) => sum + Number(l.price) * l.quantity, 0);
  }, [lines]);
  const groups = useMemo(() => groupByShop(lines), [lines]);
  const quantityOf = useCallback(
    (variantId: string) => lines.find((l) => l.variantId === variantId)?.quantity ?? 0,
    [lines],
  );

  return { lines, groups, loaded, count, total, add, setQuantity, remove, removeShop, clear, quantityOf };
}

/** What a product card needs to drop a product into the cart. */
export function cartLineFor(product: PublicProduct, variant: PublicVariant): Omit<CartLine, "quantity"> {
  return {
    variantId: variant.id,
    productId: product.id,
    name: product.name,
    variantName: variant.name,
    unit: product.unit_of_measure,
    price: variant.price ?? product.price,
    imageUrl: product.image_url,
    shop: product.shop,
  };
}

// --------------------------------------------------------------------------- //
// The visitor's own checkouts, so they can find them again
// --------------------------------------------------------------------------- //

export type RememberedCheckout = { token: string; kind: "order" | "proforma"; numbers: string[]; at: string };

const CHECKOUTS_KEY = "estock.checkouts";

export function useMyCheckouts() {
  const [items, setItems] = useState<RememberedCheckout[]>([]);

  useEffect(() => {
    setItems(readJson<RememberedCheckout[]>(CHECKOUTS_KEY, []));
  }, []);

  const remember = useCallback((entry: Omit<RememberedCheckout, "at">) => {
    const current = readJson<RememberedCheckout[]>(CHECKOUTS_KEY, []).filter((r) => r.token !== entry.token);
    const next = [{ ...entry, at: new Date().toISOString() }, ...current].slice(0, 20);
    setItems(next);
    writeJson(CHECKOUTS_KEY, next);
  }, []);

  return { items, remember };
}

export const VISITOR_KEY = "estock.visitor";

export type VisitorDetails = {
  contact_name: string;
  contact_phone: string;
  contact_email: string;
  company: string;
  delivery_location: string;
};

export function loadVisitor(): Partial<VisitorDetails> {
  return readJson<Partial<VisitorDetails>>(VISITOR_KEY, {});
}

export function saveVisitor(details: VisitorDetails): void {
  writeJson(VISITOR_KEY, details);
}

// --------------------------------------------------------------------------- //
// Status wording
// --------------------------------------------------------------------------- //

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

export function orderTone(status: string): "ok" | "warn" | "danger" | "muted" {
  switch (status) {
    case "placed":
      return "warn";
    case "confirmed":
    case "ready":
    case "completed":
      return "ok";
    default:
      return "muted";
  }
}

export function orderLabel(status: string): string {
  switch (status) {
    case "placed":
      return "Waiting for the shop";
    case "confirmed":
      return "Confirmed";
    case "ready":
      return "Ready";
    case "completed":
      return "Completed";
    case "cancelled":
      return "Cancelled";
    default:
      return status.replace(/_/g, " ");
  }
}

export const PAYMENT_METHODS: Array<{ value: string; label: string }> = [
  { value: "cash", label: "Cash on delivery or pickup" },
  { value: "telebirr", label: "telebirr" },
  { value: "cbe_birr", label: "CBE Birr" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "mobile_money", label: "Mobile money" },
];

export function paymentLabel(value: string | undefined): string {
  return PAYMENT_METHODS.find((m) => m.value === value)?.label ?? (value ?? "").replace(/_/g, " ");
}
