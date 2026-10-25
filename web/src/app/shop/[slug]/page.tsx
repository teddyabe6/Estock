"use client";

/**
 * The public shop. Browse by category or search, add to a basket, and request
 * a proforma from it. Nothing here reserves stock (PRD 13).
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";

import {
  EnquiryForm,
  ProductCard,
  SellerContact,
  ShopFilters,
  StorefrontShell,
} from "@/components/Storefront";
import { Alert, Empty } from "@/components/ui";
import { shortDate } from "@/lib/format";
import {
  defaultVariant,
  proformaLabel,
  shopApi,
  useBasket,
  useMyRequests,
  type ProductSort,
  type PublicProduct,
  type Shop,
} from "@/lib/storefront";

export default function ShopPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return (
    <Suspense fallback={null}>
      <Catalogue slug={slug} />
    </Suspense>
  );
}

function Catalogue({ slug }: { slug: string }) {
  const router = useRouter();
  const search = useSearchParams();
  // The filters live in the URL, so a narrowed catalogue can be shared,
  // bookmarked and gone back to — the browser's back button is the one a
  // shopper reaches for after opening a product.
  const category = search.get("category") ?? "";
  const minPrice = search.get("min") ?? "";
  const maxPrice = search.get("max") ?? "";
  const sort = (search.get("sort") as ProductSort | null) ?? "name";
  const [query, setQuery] = useState(search.get("q") ?? "");
  const [shop, setShop] = useState<Shop | null>(null);
  const [products, setProducts] = useState<PublicProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const basket = useBasket(slug);
  const requests = useMyRequests(slug);
  const currency = shop?.currency ?? "ETB";

  useEffect(() => {
    shopApi
      .shop(slug)
      .then(setShop)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Shop not found"));
  }, [slug]);

  useEffect(() => {
    let stale = false;
    const timer = setTimeout(() => {
      shopApi
        .products(slug, {
          q: query.trim() || undefined,
          category: category || undefined,
          min_price: minPrice || undefined,
          max_price: maxPrice || undefined,
          sort: sort !== "name" ? sort : undefined,
          limit: 100,
        })
        .then((page) => {
          if (!stale) setProducts(page.items);
        })
        .catch(() => {
          if (!stale) setProducts([]);
        });
    }, 200);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [slug, query, category, minPrice, maxPrice, sort]);

  /** Change one filter, keeping the others, in the URL. */
  function setFilters(changes: Record<string, string>) {
    const next = new URLSearchParams(search.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    const qs = next.toString();
    router.replace(`/shop/${slug}${qs ? `?${qs}` : ""}`, { scroll: false });
  }

  function addToBasket(product: PublicProduct) {
    const variant = defaultVariant(product);
    if (!variant) return;
    basket.add({
      variantId: variant.id,
      productId: product.id,
      name: product.name,
      variantName: variant.name,
      unit: product.unit_of_measure,
      price: variant.price ?? product.price,
      imageUrl: product.image_url,
    });
  }

  if (error) {
    return (
      <main style={{ maxWidth: 720, margin: "10vh auto", padding: "0 16px" }}>
        <Alert>{error}</Alert>
      </main>
    );
  }

  return (
    <StorefrontShell slug={slug} shop={shop} basketCount={basket.count} basketTotal={basket.total}>
      {shop && (shop.about || shop.address || shop.contact_phone) && (
        <section className="store-intro">
          {shop.about && <p style={{ marginTop: 0 }}>{shop.about}</p>}
          <SellerContact shop={shop} />
        </section>
      )}

      <div className="search-row">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search products"
          aria-label="Search products"
        />
        <button type="button" className="secondary" onClick={() => setAsking((v) => !v)}>
          {asking ? "Close" : "Ask a question"}
        </button>
      </div>

      {asking && <EnquiryForm slug={slug} onDone={() => setAsking(false)} />}

      <div className="shop-layout">
        <ShopFilters
          categories={shop?.categories ?? []}
          category={category}
          onCategory={(name) => setFilters({ category: name })}
          range={shop?.price_range ?? [null, null]}
          minPrice={minPrice}
          maxPrice={maxPrice}
          onPrice={(min, max) => setFilters({ min, max })}
          sort={sort}
          onSort={(value) => setFilters({ sort: value === "name" ? "" : value })}
          currency={currency}
          resultCount={products?.length ?? null}
          open={filtersOpen}
          onToggle={() => setFiltersOpen((v) => !v)}
        />

        <div className="shop-results">
          {products === null ? (
            <p className="muted">Loading products…</p>
          ) : products.length === 0 ? (
            <Empty
              title={
                query || category || minPrice || maxPrice ? "Nothing matches" : "Nothing to show yet"
              }
            >
              <p>
                {query || category || minPrice || maxPrice
                  ? "Try a wider price range, another category, or a different word."
                  : "This shop has not published any products yet."}
              </p>
            </Empty>
          ) : (
            <div className="product-grid">
              {products.map((product) => {
                const variant = defaultVariant(product);
                return (
                  <ProductCard
                    key={product.id}
                    slug={slug}
                    product={product}
                    currency={currency}
                    inBasket={variant ? basket.quantityOf(variant.id) : 0}
                    onAdd={() => addToBasket(product)}
                    onChange={(quantity) => variant && basket.setQuantity(variant.id, quantity)}
                  />
                );
              })}
            </div>
          )}
        </div>
      </div>

      {requests.items.length > 0 && (
        <section className="card" style={{ marginTop: 20 }}>
          <div className="card-title">Your proforma requests</div>
          <ul className="menu-list">
            {requests.items.map((item) => (
              <li key={item.token}>
                <Link href={`/q/${item.token}`}>
                  {item.number}
                  <span className="sub">
                    Requested {shortDate(item.at)} · {proformaLabel("requested")} or later — open to see
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </StorefrontShell>
  );
}
