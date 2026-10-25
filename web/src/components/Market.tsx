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

import { ProductImage, PublicShell, Stepper } from "@/components/Storefront";
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
    <PublicShell
      brandHref="/market"
      brandName="Marketplace"
      tagline="Products from every shop on the platform, in one place."
      basketHref="/market/basket"
      basketCount={basketCount}
      bar={
        showBar && basketCount > 0 ? (
          <div className="basket-bar no-print" role="status">
            <div>
              <strong>
                {basketCount} item{basketCount === 1 ? "" : "s"}
              </strong>
              <div className="muted" style={{ fontSize: "0.85rem" }}>
                From {shopCount} shop{shopCount === 1 ? "" : "s"}
                {basketTotal !== null ? ` · about ${money(basketTotal)}` : ""}
              </div>
            </div>
            <Link href="/market/basket" className="btn">
              Ask for prices
            </Link>
          </div>
        ) : null
      }
      footer={<div>Marketplace by Estock</div>}
    >
      {children}
    </PublicShell>
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
      <Link href={`/market/p/${product.id}`} className="thumb-link">
        <ProductImage src={product.image_url} name={product.name} />
      </Link>
      <div className="body">
        {product.brand ? <div className="label muted">{product.brand}</div> : null}
        <Link href={`/market/p/${product.id}`} className="name">
          {product.name}
        </Link>
        <div className="price">
          {askForPrice ? (
            <span className="muted">Ask for a price</span>
          ) : (
            <>
              {money(variant!.price!)}
              <span className="muted unit"> / {product.unit_of_measure}</span>
            </>
          )}
        </div>
        <div className="product-foot">
          <ShopBadge shop={product.shop} />
          {!product.in_stock ? <span className="badge warn">Out of stock</span> : null}
        </div>
        <div className="actions">
          {quantity > 0 ? (
            <Stepper value={quantity} onChange={onSetQuantity} />
          ) : (
            <button type="button" onClick={onAdd} disabled={!variant}>
              Add
            </button>
          )}
        </div>
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
