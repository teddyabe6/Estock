"use client";

/**
 * One product on the marketplace, with its own shareable link.
 *
 * Says plainly which shop it belongs to, because on a marketplace that is the
 * thing a buyer most needs to know.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { MarketNotice, MarketProductCard, MarketShell } from "@/components/Market";
import { ProductImage, Stepper } from "@/components/Storefront";
import { Alert, Empty } from "@/components/ui";
import { money } from "@/lib/format";
import { describeError } from "@/lib/session";
import {
  defaultMarketVariant,
  marketApi,
  useMarketBasket,
  type MarketProduct,
  type MarketVariant,
} from "@/lib/market";

export default function MarketProductPage() {
  const params = useParams<{ productId: string }>();
  const productId = params.productId;

  const [product, setProduct] = useState<MarketProduct | null>(null);
  const [variant, setVariant] = useState<MarketVariant | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [related, setRelated] = useState<MarketProduct[]>([]);
  const basket = useMarketBasket();

  useEffect(() => {
    void (async () => {
      try {
        const found = await marketApi.product(productId);
        setProduct(found);
        setVariant(defaultMarketVariant(found));
        // Separately, and allowed to fail: the product itself is the page,
        // and what other shops charge is the reason to stay on it.
        marketApi
          .related(productId)
          .then((page) => setRelated(page.items))
          .catch(() => setRelated([]));
      } catch (cause) {
        setError(describeError(cause));
      } finally {
        setLoading(false);
      }
    })();
  }, [productId]);

  if (loading) {
    return (
      <MarketShell basketCount={basket.count} shopCount={basket.shopCount} basketTotal={basket.total}>
        <p className="muted">Loading…</p>
      </MarketShell>
    );
  }

  if (error || !product) {
    return (
      <MarketShell basketCount={basket.count} shopCount={basket.shopCount} basketTotal={basket.total}>
        {error ? <Alert>{error}</Alert> : null}
        <Empty title="This product is not available">
          <p className="muted">
            It may have been taken off the marketplace. <Link href="/market">Browse everything</Link>.
          </p>
        </Empty>
      </MarketShell>
    );
  }

  const inBasket = variant ? basket.quantityOf(variant.id) : 0;
  const hasOptions = product.variants.length > 1;

  return (
    <MarketShell
      basketCount={basket.count}
      shopCount={basket.shopCount}
      basketTotal={basket.total}
    >
      <nav className="crumbs">
        <Link href="/market">Marketplace</Link>
        {" / "}
        <Link href={`/market?shop=${encodeURIComponent(product.shop.slug)}`}>
          {product.shop.name}
        </Link>
      </nav>

      <div className="product-detail">
        <ProductImage src={product.image_url} name={product.name} className="thumb hero" />

        <div className="product-info">
          <h1>{product.name}</h1>
          {product.brand ? <p className="muted">{product.brand}</p> : null}

          <p className="sold-by">
            Sold by{" "}
            <Link href={`/market?shop=${encodeURIComponent(product.shop.slug)}`}>
              <strong>{product.shop.name}</strong>
            </Link>
            {product.shop.address ? <span className="muted"> · {product.shop.address}</span> : null}
          </p>

          <p className="price large">
            {variant?.price ? (
              <>
                {money(variant.price)}
                <span className="muted small"> / {product.unit_of_measure}</span>
              </>
            ) : (
              <span className="muted">Ask this shop for a price</span>
            )}
          </p>

          {!product.in_stock ? (
            <Alert kind="warn">
              This shop shows none in stock. You can still ask — they may be
              able to order it.
            </Alert>
          ) : null}

          {hasOptions ? (
            <div className="variant-picker" role="group" aria-label="Options">
              {product.variants.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className={`chip${variant?.id === option.id ? " active" : ""}`}
                  onClick={() => setVariant(option)}
                >
                  {option.name ?? "Standard"}
                  {option.price ? <span className="muted small"> · {money(option.price)}</span> : null}
                </button>
              ))}
            </div>
          ) : null}

          <div className="row">
            {inBasket > 0 ? (
              <>
                <Stepper
                  value={inBasket}
                  onChange={(next) => variant && basket.setQuantity(variant.id, next)}
                />
                <Link href="/market/basket" className="btn">
                  Go to basket
                </Link>
              </>
            ) : (
              <button
                type="button"
                disabled={!variant}
                onClick={() => {
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
              >
                Add to basket
              </button>
            )}
          </div>

          {product.description ? (
            <div className="product-description">
              <h2>About this product</h2>
              <p>{product.description}</p>
            </div>
          ) : null}

          {product.shop.has_own_page ? (
            <p className="muted small">
              <Link href={`/shop/${product.shop.slug}`}>
                See everything from {product.shop.name}
              </Link>
            </p>
          ) : null}
        </div>
      </div>

      {related.length > 0 ? (
        <section className="related">
          <h2>The same sort of thing at other shops</h2>
          <p className="muted small">
            The same item elsewhere first, cheapest of those at the top, then other
            things those shops sell in this category. Add any of them and ask every
            shop at once — each replies with its own price.
          </p>
          <div className="product-grid">
            {related.map((item) => {
              const option = defaultMarketVariant(item);
              return (
                <MarketProductCard
                  key={item.id}
                  product={item}
                  quantity={option ? basket.quantityOf(option.id) : 0}
                  onAdd={() => {
                    if (!option) return;
                    basket.add({
                      variantId: option.id,
                      productId: item.id,
                      name: item.name,
                      variantName: option.name,
                      unit: item.unit_of_measure,
                      price: option.price,
                      imageUrl: item.image_url,
                      shopSlug: item.shop.slug,
                      shopName: item.shop.name,
                    });
                  }}
                  onSetQuantity={(next) => {
                    if (option) basket.setQuantity(option.id, next);
                  }}
                />
              );
            })}
          </div>
        </section>
      ) : null}

      <MarketNotice />
    </MarketShell>
  );
}
