"use client";

/**
 * The marketplace catalogue: every shop's listed products, searchable and
 * filterable, with one basket that may span shops.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { MarketNotice, MarketProductCard, MarketShell } from "@/components/Market";
import { Alert, Empty } from "@/components/ui";
import { describeError } from "@/lib/session";
import {
  defaultMarketVariant,
  marketApi,
  useMarketBasket,
  useMyMarketRequests,
  type MarketProduct,
  type MarketShop,
} from "@/lib/market";

const PAGE = 24;

export default function MarketPage() {
  return (
    <Suspense fallback={<p className="muted">Loading the marketplace…</p>}>
      <Market />
    </Suspense>
  );
}

function Market() {
  const params = useSearchParams();
  const router = useRouter();
  const shopFilter = params.get("shop") ?? "";
  const categoryFilter = params.get("category") ?? "";

  const [search, setSearch] = useState(params.get("q") ?? "");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [products, setProducts] = useState<MarketProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState<string[]>([]);
  const [shops, setShops] = useState<MarketShop[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const basket = useMarketBasket();
  const { items: myRequests } = useMyMarketRequests();

  // Typing searches, but not on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    void (async () => {
      try {
        const [cats, directory] = await Promise.all([
          marketApi.categories(),
          marketApi.shops(),
        ]);
        setCategories(cats.categories);
        setShops(directory.shops);
      } catch {
        // Filters are a convenience; the catalogue still works without them.
      }
    })();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void (async () => {
      try {
        const page = await marketApi.products({
          q: query || undefined,
          category: categoryFilter || undefined,
          shop: shopFilter || undefined,
          limit: PAGE,
        });
        if (controller.signal.aborted) return;
        setProducts(page.items);
        setTotal(page.total);
        setError(null);
      } catch (cause) {
        if (!controller.signal.aborted) setError(describeError(cause));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [query, categoryFilter, shopFilter]);

  const setFilter = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      router.replace(`/market${next.toString() ? `?${next}` : ""}`);
    },
    [params, router],
  );

  const activeShop = shops.find((s) => s.slug === shopFilter) ?? null;

  return (
    <MarketShell
      basketCount={basket.count}
      shopCount={basket.shopCount}
      basketTotal={basket.total}
    >
      <div className="shop-search">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search every shop…"
          aria-label="Search the marketplace"
        />
      </div>

      {categories.length > 0 ? (
        <div className="chips" role="group" aria-label="Categories">
          <button
            type="button"
            className={`chip${categoryFilter ? "" : " active"}`}
            onClick={() => setFilter("category", "")}
          >
            All
          </button>
          {categories.map((name) => (
            <button
              key={name}
              type="button"
              className={`chip${categoryFilter === name ? " active" : ""}`}
              onClick={() => setFilter("category", categoryFilter === name ? "" : name)}
            >
              {name}
            </button>
          ))}
        </div>
      ) : null}

      {activeShop ? (
        <div className="filter-note">
          <span>
            Showing only <strong>{activeShop.name}</strong>
            {activeShop.address ? ` · ${activeShop.address}` : ""}
          </span>
          <button type="button" className="btn ghost" onClick={() => setFilter("shop", "")}>
            Show every shop
          </button>
        </div>
      ) : shops.length > 1 ? (
        <details className="shop-directory">
          <summary>{shops.length} shops on the marketplace</summary>
          <ul>
            {shops.map((shop) => (
              <li key={shop.slug}>
                <button type="button" className="link" onClick={() => setFilter("shop", shop.slug)}>
                  {shop.name}
                </button>
                {shop.tagline ? <span className="muted small"> — {shop.tagline}</span> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {myRequests.length > 0 ? (
        <details className="my-requests">
          <summary>Your requests ({myRequests.length})</summary>
          <ul>
            {myRequests.map((entry) => (
              <li key={entry.token}>
                <Link href={`/market/requests/${entry.token}`}>{entry.reference}</Link>
                <span className="muted small">
                  {" "}
                  · {entry.shopCount} shop{entry.shopCount === 1 ? "" : "s"}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {error ? <Alert>{error}</Alert> : null}

      {loading ? (
        <p className="muted">Loading products…</p>
      ) : products.length === 0 ? (
        <Empty title="Nothing matches that yet">
          <p className="muted">Try a different word, or clear the filters.</p>
        </Empty>
      ) : (
        <>
          <p className="muted small result-count">
            {total} product{total === 1 ? "" : "s"}
            {total > products.length ? ` · showing the first ${products.length}` : ""}
          </p>
          <div className="product-grid">
            {products.map((product) => {
              const variant = defaultMarketVariant(product);
              return (
                <MarketProductCard
                  key={product.id}
                  product={product}
                  quantity={variant ? basket.quantityOf(variant.id) : 0}
                  onAdd={() => {
                    if (!variant) return;
                    basket.add({
                      variantId: variant.id,
                      productId: product.id,
                      name: product.name,
                      variantName: variant.name,
                      unit: product.unit_of_measure,
                      price: variant.price,
                      imageUrl: product.image_url,
                      shopSlug: product.shop.slug,
                      shopName: product.shop.name,
                    });
                  }}
                  onSetQuantity={(next) => {
                    if (variant) basket.setQuantity(variant.id, next);
                  }}
                />
              );
            })}
          </div>
        </>
      )}

      <MarketNotice />
    </MarketShell>
  );
}
