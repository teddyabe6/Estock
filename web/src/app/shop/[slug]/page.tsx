"use client";

/**
 * One shop's page on the marketplace. Browse its products by category or
 * search, add to the shared cart, ask a question. Nothing here reserves stock
 * (PRD 13).
 */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useState } from "react";

import { EnquiryForm, ProductCard, SellerContact, StorefrontShell } from "@/components/Storefront";
import { Alert, Empty } from "@/components/ui";
import { shopApi, type PublicProduct, type Shop } from "@/lib/storefront";

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
  const category = search.get("category") ?? "";
  const [query, setQuery] = useState(search.get("q") ?? "");
  const [shop, setShop] = useState<Shop | null>(null);
  const [products, setProducts] = useState<PublicProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
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
        .products(slug, { q: query.trim() || undefined, category: category || undefined, limit: 100 })
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
  }, [slug, query, category]);

  function pickCategory(name: string) {
    router.replace(`/shop/${slug}${name ? `?category=${encodeURIComponent(name)}` : ""}`);
  }

  if (error) {
    return (
      <main style={{ maxWidth: 720, margin: "10vh auto", padding: "0 16px" }}>
        <Alert>{error}</Alert>
      </main>
    );
  }

  return (
    <StorefrontShell title={shop?.display_name ?? "Loading…"} subtitle={shop?.tagline} homeHref={`/shop/${slug}`} contact={shop}>
      {shop && (shop.about || shop.address || shop.contact_phone) && (
        <section className="store-intro">
          {shop.about && <p style={{ marginTop: 0 }}>{shop.about}</p>}
          {!shop.accepts_orders && (
            <p className="muted" style={{ fontSize: "0.88rem" }}>
              This shop takes proforma requests rather than direct orders.
            </p>
          )}
          <SellerContact shop={shop} />
        </section>
      )}

      <div className="search-row">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search this shop"
          aria-label="Search products"
        />
        <button type="button" className="secondary" onClick={() => setAsking((v) => !v)}>
          {asking ? "Close" : "Ask a question"}
        </button>
      </div>

      {asking && <EnquiryForm slug={slug} onDone={() => setAsking(false)} />}

      {shop && shop.categories.length > 0 && (
        <div className="chips" role="tablist" aria-label="Categories">
          <button type="button" className={`chip${category ? "" : " is-active"}`} onClick={() => pickCategory("")}>
            All
          </button>
          {shop.categories.map((name) => (
            <button
              key={name}
              type="button"
              className={`chip${category.toLowerCase() === name.toLowerCase() ? " is-active" : ""}`}
              onClick={() => pickCategory(name)}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {products === null ? (
        <p className="muted">Loading products…</p>
      ) : products.length === 0 ? (
        <Empty title={query || category ? "Nothing matches" : "Nothing to show yet"}>
          <p>
            {query || category
              ? "Try another word or category."
              : "This shop has not published any products yet."}
          </p>
        </Empty>
      ) : (
        <div className="product-grid">
          {products.map((product) => (
            <ProductCard key={product.id} product={product} currency={currency} />
          ))}
        </div>
      )}
    </StorefrontShell>
  );
}
