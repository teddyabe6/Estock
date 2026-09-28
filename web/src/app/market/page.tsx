"use client";

/**
 * The marketplace: every open shop's published products in one place, with
 * filters by shop, category, price and availability. Add to one cart across
 * shops, then check out or request proformas (PRD 13).
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ProductCard, StorefrontShell } from "@/components/Storefront";
import { Empty } from "@/components/ui";
import { shortDate } from "@/lib/format";
import { shopApi, useMyCheckouts, type Market, type MarketQuery, type PublicProduct } from "@/lib/storefront";

export default function MarketPage() {
  return (
    <Suspense fallback={null}>
      <Marketplace />
    </Suspense>
  );
}

const SORTS: Array<{ value: NonNullable<MarketQuery["sort"]>; label: string }> = [
  { value: "name", label: "Name" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
  { value: "newest", label: "Newest" },
];

function Marketplace() {
  const router = useRouter();
  const search = useSearchParams();
  const category = search.get("category") ?? "";
  const shop = search.get("shop") ?? "";
  const sort = (search.get("sort") as MarketQuery["sort"]) ?? "name";
  const inStock = search.get("in_stock") === "1";
  const [query, setQuery] = useState(search.get("q") ?? "");
  const [minPrice, setMinPrice] = useState(search.get("min_price") ?? "");
  const [maxPrice, setMaxPrice] = useState(search.get("max_price") ?? "");
  const [market, setMarket] = useState<Market | null>(null);
  const [products, setProducts] = useState<PublicProduct[] | null>(null);
  const [total, setTotal] = useState(0);
  const [showShops, setShowShops] = useState(false);
  const checkouts = useMyCheckouts();
  const currency = market?.currency ?? "ETB";

  useEffect(() => {
    shopApi.market().then(setMarket).catch(() => setMarket({ shops: [], categories: [], currency: "ETB" }));
  }, []);

  useEffect(() => {
    let stale = false;
    const timer = setTimeout(() => {
      shopApi
        .marketProducts({
          q: query.trim() || undefined,
          category: category || undefined,
          shop: shop || undefined,
          min_price: minPrice || undefined,
          max_price: maxPrice || undefined,
          in_stock: inStock,
          sort,
          limit: 100,
        })
        .then((page) => {
          if (stale) return;
          setProducts(page.items);
          setTotal(page.total);
        })
        .catch(() => {
          if (!stale) setProducts([]);
        });
    }, 200);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [query, category, shop, minPrice, maxPrice, inStock, sort]);

  function setParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(search.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    const text = next.toString();
    router.replace(`/market${text ? `?${text}` : ""}`);
  }

  const activeShop = market?.shops.find((s) => s.slug === shop) ?? null;

  return (
    <StorefrontShell title="Marketplace" subtitle="Order from any shop, or ask several for a proforma">
      <div className="search-row">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search every shop"
          aria-label="Search products"
        />
        <button type="button" className="secondary" onClick={() => setShowShops((v) => !v)}>
          {showShops ? "Hide shops" : `Shops (${market?.shops.length ?? "…"})`}
        </button>
      </div>

      {showShops && market && (
        <div className="shop-list">
          {market.shops.map((s) => (
            <article key={s.slug} className={`card shop-card${shop === s.slug ? " is-active" : ""}`}>
              <div className="card-title" style={{ marginBottom: 2 }}>
                <Link href={`/shop/${s.slug}`}>{s.display_name}</Link>
              </div>
              {s.tagline && <div className="muted" style={{ fontSize: "0.88rem" }}>{s.tagline}</div>}
              <div className="muted" style={{ fontSize: "0.82rem", marginTop: 6 }}>
                {s.product_count} product{s.product_count === 1 ? "" : "s"}
                {s.categories.length ? ` · ${s.categories.join(", ")}` : ""}
                {!s.accepts_orders ? " · proforma requests only" : ""}
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <button type="button" className="secondary" onClick={() => setParams({ shop: shop === s.slug ? null : s.slug })}>
                  {shop === s.slug ? "Show all shops" : "Only this shop"}
                </button>
                <Link href={`/shop/${s.slug}`} className="btn secondary">
                  Visit shop
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}

      {market && market.categories.length > 0 && (
        <div className="chips" role="tablist" aria-label="Categories">
          <button type="button" className={`chip${category ? "" : " is-active"}`} onClick={() => setParams({ category: null })}>
            All
          </button>
          {market.categories.map((name) => (
            <button
              key={name}
              type="button"
              className={`chip${category.toLowerCase() === name.toLowerCase() ? " is-active" : ""}`}
              onClick={() => setParams({ category: name })}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      <div className="filters">
        <label className="filter">
          <span>Min price</span>
          <input value={minPrice} onChange={(e) => setMinPrice(e.target.value)} inputMode="decimal" placeholder="0" />
        </label>
        <label className="filter">
          <span>Max price</span>
          <input value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} inputMode="decimal" placeholder="any" />
        </label>
        <label className="filter">
          <span>Sort</span>
          <select value={sort} onChange={(e) => setParams({ sort: e.target.value === "name" ? null : e.target.value })}>
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="filter check">
          <input type="checkbox" checked={inStock} onChange={(e) => setParams({ in_stock: e.target.checked ? "1" : null })} />
          <span>In stock only</span>
        </label>
        {activeShop && (
          <button type="button" className="chip is-active" onClick={() => setParams({ shop: null })}>
            {activeShop.display_name} ✕
          </button>
        )}
      </div>

      {products === null ? (
        <p className="muted">Loading products…</p>
      ) : products.length === 0 ? (
        <Empty title="Nothing matches">
          <p>Try another word, category or price range.</p>
        </Empty>
      ) : (
        <>
          <p className="muted" style={{ fontSize: "0.85rem", margin: "4px 0 10px" }}>
            {total} product{total === 1 ? "" : "s"}
          </p>
          <div className="product-grid">
            {products.map((product) => (
              <ProductCard key={product.id} product={product} currency={currency} showShop />
            ))}
          </div>
        </>
      )}

      {checkouts.items.length > 0 && (
        <section className="card" style={{ marginTop: 20 }}>
          <div className="card-title">Your orders and requests</div>
          <ul className="menu-list">
            {checkouts.items.map((item) => (
              <li key={item.token}>
                <Link href={`/track/${item.token}`}>
                  {item.kind === "order" ? "Order" : "Proforma request"} · {item.numbers.join(", ")}
                  <span className="sub">{shortDate(item.at)} · open to see the status</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </StorefrontShell>
  );
}
