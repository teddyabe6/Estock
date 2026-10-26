"use client";

/**
 * The marketplace catalogue: every shop's listed products, searchable and
 * filterable, with one basket that may span shops.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { MarketFilters, MarketNotice, MarketProductCard, MarketShell } from "@/components/Market";
import { Alert, Empty } from "@/components/ui";
import { describeError } from "@/lib/session";
import {
  defaultMarketVariant,
  marketApi,
  useMarketBasket,
  useMyMarketRequests,
  type MarketProduct,
  type MarketShop,
  type MarketSort,
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
  const minPrice = params.get("min") ?? "";
  const maxPrice = params.get("max") ?? "";
  const sort = (params.get("sort") ?? "name") as MarketSort;

  const [search, setSearch] = useState(params.get("q") ?? "");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [products, setProducts] = useState<MarketProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState<string[]>([]);
  const [shops, setShops] = useState<MarketShop[]>([]);
  const [range, setRange] = useState<[string | null, string | null]>([
    null,
    null,
  ]);
  const [loading, setLoading] = useState(true);
  const [filtersOpen, setFiltersOpen] = useState(false);
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
          min_price: minPrice || undefined,
          max_price: maxPrice || undefined,
          sort: sort === "name" ? undefined : sort,
          limit: PAGE,
        });
        if (controller.signal.aborted) return;
        setProducts(page.items);
        setTotal(page.total);
        setRange(page.price_range);
        setError(null);
      } catch (cause) {
        if (!controller.signal.aborted) setError(describeError(cause));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [query, categoryFilter, shopFilter, minPrice, maxPrice, sort]);

  /** Filters live in the URL, so a narrowed marketplace can be shared. */
  const setFilters = useCallback(
    (changes: Record<string, string>) => {
      const next = new URLSearchParams(params.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      router.replace(`/market${next.toString() ? `?${next}` : ""}`);
    },
    [params, router],
  );

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

      {myRequests.length > 0 ? (
        <details className="my-requests">
          <summary>Your requests ({myRequests.length})</summary>
          <ul>
            {myRequests.map((entry) => (
              <li key={entry.token}>
                <Link href={`/market/requests/${entry.token}`}>
                  {entry.reference}
                </Link>
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

      <div className="shop-layout">
        <MarketFilters
          shops={shops}
          shop={shopFilter}
          onShop={(slug) => setFilters({ shop: slug })}
          categories={categories}
          category={categoryFilter}
          onCategory={(name) => setFilters({ category: name })}
          range={range}
          minPrice={minPrice}
          maxPrice={maxPrice}
          onPrice={(min, max) => setFilters({ min, max })}
          sort={sort}
          onSort={(value) =>
            setFilters({ sort: value === "name" ? "" : value })
          }
          resultCount={loading ? null : total}
          open={filtersOpen}
          onToggle={() => setFiltersOpen((v) => !v)}
        />

        <div className="shop-results">
          {loading ? (
            <p className="muted">Loading products…</p>
          ) : products.length === 0 ? (
            <Empty title="Nothing matches that yet">
              <p className="muted">
                Try a different word, or clear the filters.
              </p>
            </Empty>
          ) : (
            <>
              <p className="muted small result-count">
                {total} product{total === 1 ? "" : "s"}
                {total > products.length
                  ? ` · showing the first ${products.length}`
                  : ""}
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
        </div>
      </div>

      <MarketNotice />
    </MarketShell>
  );
}
