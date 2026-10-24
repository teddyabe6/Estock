/**
 * The central marketplace: every shop's listed products, in one catalogue.
 *
 * No sign-in anywhere here. The basket lives in the visitor's browser and
 * reserves nothing; checking out asks each shop in it for a price, and even
 * then stock only moves when a shop converts its own proforma to a sale.
 *
 * The one thing this basket does that a single shop's does not: every line
 * remembers which shop it came from, because checkout has to be grouped by
 * shop before it is sent.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { request } from "@/lib/api";

export type MarketShop = {
  id: string;
  slug: string;
  name: string;
  tagline: string | null;
  address: string | null;
  phone: string | null;
  /** True when the shop also runs its own page, so we can link to it. */
  has_own_page: boolean;
};

export type MarketVariant = {
  id: string;
  name: string | null;
  is_default: boolean;
  price: string | null;
  in_stock: boolean;
};

export type MarketProduct = {
  id: string;
  name: string;
  description: string | null;
  brand: string | null;
  category: string | null;
  unit_of_measure: string;
  price: string | null;
  in_stock: boolean;
  image_url: string | null;
  shop: MarketShop;
  variants: MarketVariant[];
};

export type MarketRequestResult = {
  reference: string;
  token: string;
  url: string;
  shop_count: number;
  message: string;
};

export type MarketRequestShopRow = {
  shop: string;
  shop_slug: string | null;
  number: string;
  status: string;
  answered: boolean;
  item_count: number;
  total_amount: string | null;
  currency: string;
  valid_until: string | null;
  /** The shop's own proforma link, where the buyer accepts or declines. */
  token: string | null;
};

export type MarketRequestView = {
  reference: string;
  status: string;
  submitted_at: string | null;
  contact_name: string;
  delivery_location: string | null;
  message: string | null;
  shop_count: number;
  answered_count: number;
  shops: MarketRequestShopRow[];
};

function qs(params: Record<string, string | number | undefined>): string {
  const pairs = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== "")
    .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`);
  return pairs.length ? `?${pairs.join("&")}` : "";
}

export const marketApi = {
  shops: () => request<{ shops: MarketShop[] }>("/market/shops", { anonymous: true }),
  categories: () =>
    request<{ categories: string[] }>("/market/categories", { anonymous: true }),
  products: (
    params: { q?: string; category?: string; shop?: string; limit?: number; offset?: number } = {},
  ) =>
    request<{ items: MarketProduct[]; total: number; limit: number; offset: number }>(
      `/market/products${qs(params)}`,
      { anonymous: true },
    ),
  product: (id: string) =>
    request<MarketProduct>(`/market/products/${id}`, { anonymous: true }),
  submitRequest: (body: Record<string, unknown>) =>
    request<MarketRequestResult>("/market/requests", {
      method: "POST",
      anonymous: true,
      body,
    }),
  trackRequest: (token: string) =>
    request<MarketRequestView>(`/market/requests/${token}`, { anonymous: true }),
  withdrawRequest: (token: string) =>
    request<MarketRequestView>(`/market/requests/${token}/withdraw`, {
      method: "POST",
      anonymous: true,
    }),
};

export function defaultMarketVariant(product: MarketProduct): MarketVariant | null {
  return product.variants.find((v) => v.is_default) ?? product.variants[0] ?? null;
}

// --------------------------------------------------------------------------- //
// The basket
// --------------------------------------------------------------------------- //

export type MarketBasketLine = {
  variantId: string;
  productId: string;
  name: string;
  variantName: string | null;
  unit: string;
  price: string | null;
  imageUrl: string | null;
  quantity: number;
  /** Which shop this came from — checkout is grouped by it. */
  shopSlug: string;
  shopName: string;
};

export type ShopGroup = {
  slug: string;
  name: string;
  lines: MarketBasketLine[];
  /** Null when any line in the group has no price to show. */
  total: number | null;
};

const BASKET_KEY = "estock.market.basket";
const REQUESTS_KEY = "estock.market.requests";

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

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

export function useMarketBasket() {
  const [lines, setLines] = useState<MarketBasketLine[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLines(readJson<MarketBasketLine[]>(BASKET_KEY, []));
    setLoaded(true);
  }, []);

  const persist = useCallback((next: MarketBasketLine[]) => {
    setLines(next);
    writeJson(BASKET_KEY, next);
  }, []);

  const add = useCallback(
    (line: Omit<MarketBasketLine, "quantity">, quantity = 1) => {
      const current = readJson<MarketBasketLine[]>(BASKET_KEY, []);
      const existing = current.find((l) => l.variantId === line.variantId);
      const next = existing
        ? current.map((l) =>
            l.variantId === line.variantId
              ? { ...l, ...line, quantity: round(l.quantity + quantity) }
              : l,
          )
        : [...current, { ...line, quantity: round(quantity) }];
      persist(next);
    },
    [persist],
  );

  const setQuantity = useCallback(
    (variantId: string, quantity: number) => {
      const current = readJson<MarketBasketLine[]>(BASKET_KEY, []);
      const next =
        quantity <= 0
          ? current.filter((l) => l.variantId !== variantId)
          : current.map((l) =>
              l.variantId === variantId ? { ...l, quantity: round(quantity) } : l,
            );
      persist(next);
    },
    [persist],
  );

  const remove = useCallback((variantId: string) => setQuantity(variantId, 0), [setQuantity]);
  const clear = useCallback(() => persist([]), [persist]);

  const count = useMemo(() => lines.reduce((sum, l) => sum + l.quantity, 0), [lines]);

  /** One group per shop, which is how checkout sends it and how it reads. */
  const groups = useMemo<ShopGroup[]>(() => {
    const byShop = new Map<string, ShopGroup>();
    for (const line of lines) {
      const group = byShop.get(line.shopSlug) ?? {
        slug: line.shopSlug,
        name: line.shopName,
        lines: [],
        total: 0,
      };
      group.lines.push(line);
      byShop.set(line.shopSlug, group);
    }
    return [...byShop.values()]
      .map((group) => ({
        ...group,
        total: group.lines.some((l) => l.price === null)
          ? null
          : group.lines.reduce((sum, l) => sum + Number(l.price) * l.quantity, 0),
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [lines]);

  const total = useMemo(() => {
    if (lines.length === 0 || lines.some((l) => l.price === null)) return null;
    return lines.reduce((sum, l) => sum + Number(l.price) * l.quantity, 0);
  }, [lines]);

  const quantityOf = useCallback(
    (variantId: string) => lines.find((l) => l.variantId === variantId)?.quantity ?? 0,
    [lines],
  );

  return {
    lines,
    groups,
    loaded,
    count,
    total,
    shopCount: groups.length,
    add,
    setQuantity,
    remove,
    clear,
    quantityOf,
  };
}

// --------------------------------------------------------------------------- //
// Requests made from this browser, so a visitor can find them again
// --------------------------------------------------------------------------- //

export type RememberedMarketRequest = {
  reference: string;
  token: string;
  shopCount: number;
  at: string;
};

export function useMyMarketRequests() {
  const [items, setItems] = useState<RememberedMarketRequest[]>([]);

  useEffect(() => {
    setItems(readJson<RememberedMarketRequest[]>(REQUESTS_KEY, []));
  }, []);

  const remember = useCallback((entry: Omit<RememberedMarketRequest, "at">) => {
    const current = readJson<RememberedMarketRequest[]>(REQUESTS_KEY, []).filter(
      (r) => r.token !== entry.token,
    );
    const next = [{ ...entry, at: new Date().toISOString() }, ...current].slice(0, 20);
    setItems(next);
    writeJson(REQUESTS_KEY, next);
  }, []);

  return { items, remember };
}

export function requestStatusLabel(status: string): string {
  switch (status) {
    case "open":
      return "Waiting for shops to price it";
    case "answered":
      return "Every shop has answered";
    case "accepted":
      return "You accepted a quotation";
    case "withdrawn":
      return "Withdrawn";
    default:
      return status.replace(/_/g, " ");
  }
}
