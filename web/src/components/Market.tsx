"use client";

/**
 * Pieces of the central marketplace, shared by its catalogue, product,
 * basket and tracking pages. No sign-in anywhere here.
 *
 * The difference from a single shop's storefront: every product carries the
 * shop that listed it, and the basket bar counts shops as well as items —
 * because checking out means asking each of those shops separately.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { ProductImage, Stepper } from "@/components/Storefront";
import { money } from "@/lib/format";
import {
  defaultMarketVariant,
  type MarketProduct,
  type MarketShop,
} from "@/lib/market";

export function MarketShell({
  basketCount,
  shopCount,
  basketTotal,
  showBar = true,
  children,
}: {
  basketCount: number;
  shopCount: number;
  basketTotal: number | null;
  showBar?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="storefront">
      <header className="shop-head">
        <div>
          <Link href="/market" className="shop-name">
            Marketplace
          </Link>
          <p className="shop-tagline">
            Products from every shop on the platform, in one place.
          </p>
        </div>
        <Link href="/market/basket" className="basket-link">
          Basket{basketCount > 0 ? ` (${basketCount})` : ""}
        </Link>
      </header>

      {children}

      {showBar && basketCount > 0 ? (
        <div className="basket-bar" role="status">
          <div>
            <strong>
              {basketCount} item{basketCount === 1 ? "" : "s"}
            </strong>
            <span className="muted">
              {" from "}
              {shopCount} shop{shopCount === 1 ? "" : "s"}
              {basketTotal !== null ? ` · ${money(basketTotal)}` : ""}
            </span>
          </div>
          <Link href="/market/basket" className="btn primary">
            Ask for prices
          </Link>
        </div>
      ) : null}
    </div>
  );
}

export function ShopBadge({ shop }: { shop: MarketShop }) {
  return (
    <Link href={`/market?shop=${encodeURIComponent(shop.slug)}`} className="shop-badge">
      {shop.name}
    </Link>
  );
}

export function MarketProductCard({
  product,
  quantity,
  onAdd,
  onSetQuantity,
}: {
  product: MarketProduct;
  quantity: number;
  onAdd: () => void;
  onSetQuantity: (next: number) => void;
}) {
  const variant = defaultMarketVariant(product);
  const askForPrice = variant?.price === null || variant?.price === undefined;

  return (
    <article className="product-card">
      <Link href={`/market/p/${product.id}`} className="product-link">
        <ProductImage src={product.image_url} name={product.name} />
        <div className="product-body">
          <h3>{product.name}</h3>
          {product.brand ? <p className="muted small">{product.brand}</p> : null}
          <p className="price">
            {askForPrice ? (
              <span className="muted">Ask for a price</span>
            ) : (
              <>
                {money(variant!.price!)}
                <span className="muted small"> / {product.unit_of_measure}</span>
              </>
            )}
          </p>
        </div>
      </Link>
      <div className="product-foot">
        <ShopBadge shop={product.shop} />
        {!product.in_stock ? <span className="pill muted">Out of stock</span> : null}
      </div>
      <div className="product-actions">
        {quantity > 0 ? (
          <Stepper value={quantity} onChange={onSetQuantity} />
        ) : (
          <button type="button" className="btn" onClick={onAdd} disabled={!variant}>
            Add
          </button>
        )}
      </div>
    </article>
  );
}

export function MarketNotice() {
  return (
    <p className="disclaimer">
      Adding to your basket reserves nothing. When you ask for prices, each shop
      gets only its own part of your basket and replies with its own quotation.
      You can accept one shop&apos;s price and leave another&apos;s.
    </p>
  );
}
