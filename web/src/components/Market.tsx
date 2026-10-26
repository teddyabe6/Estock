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
import { useEffect, useState, type ReactNode } from "react";

import { ProductImage, PublicShell, Stepper } from "@/components/Storefront";
import { money } from "@/lib/format";
import {
  defaultMarketVariant,
  type MarketProduct,
  type MarketShop,
  type MarketSort,
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

/**
 * The filter rail beside the marketplace catalogue.
 *
 * The same shape as a single shop's rail, with one group a shop cannot have:
 * which shop. A buyer here is choosing between sellers as much as between
 * products, so that belongs at the top with the rest of the narrowing rather
 * than in a list further down the page.
 *
 * The price group only appears when something on the marketplace carries a
 * price. Offering a range over a catalogue that quotes on request would be a
 * control that cannot do anything.
 */
export function MarketFilters({
  shops,
  shop,
  onShop,
  categories,
  category,
  onCategory,
  range,
  minPrice,
  maxPrice,
  onPrice,
  sort,
  onSort,
  resultCount,
  open,
  onToggle,
}: {
  shops: MarketShop[];
  shop: string;
  onShop: (slug: string) => void;
  categories: string[];
  category: string;
  onCategory: (name: string) => void;
  range: [string | null, string | null];
  minPrice: string;
  maxPrice: string;
  onPrice: (min: string, max: string) => void;
  sort: MarketSort;
  onSort: (value: MarketSort) => void;
  resultCount: number | null;
  open: boolean;
  onToggle: () => void;
}) {
  const [low, high] = range;
  const canFilterByPrice = low !== null && high !== null;
  const [draftMin, setDraftMin] = useState(minPrice);
  const [draftMax, setDraftMax] = useState(maxPrice);

  // Keep the inputs in step when the filters are cleared from outside.
  useEffect(() => {
    setDraftMin(minPrice);
    setDraftMax(maxPrice);
  }, [minPrice, maxPrice]);

  const active =
    (shop ? 1 : 0) +
    (category ? 1 : 0) +
    (minPrice ? 1 : 0) +
    (maxPrice ? 1 : 0) +
    (sort !== "name" ? 1 : 0);

  return (
    <>
      <button
        type="button"
        className="filters-toggle secondary"
        onClick={onToggle}
        aria-expanded={open}
      >
        {open ? "Hide filters" : "Filters"}
        {active > 0 && <span className="basket-count">{active}</span>}
      </button>

      <aside className={open ? "shop-filters is-open" : "shop-filters"} aria-label="Filters">
        <div className="filter-group">
          <h2>Sort by</h2>
          <select value={sort} onChange={(e) => onSort(e.target.value as MarketSort)}>
            <option value="name">Name</option>
            <option value="price_low">Price, low to high</option>
            <option value="price_high">Price, high to low</option>
          </select>
        </div>

        {shops.length > 1 && (
          <div className="filter-group">
            <h2>Shop</h2>
            <ul className="filter-list">
              <li>
                <button type="button" className={shop ? "" : "is-active"} onClick={() => onShop("")}>
                  Every shop
                </button>
              </li>
              {shops.map((entry) => (
                <li key={entry.slug}>
                  <button
                    type="button"
                    className={shop === entry.slug ? "is-active" : ""}
                    onClick={() => onShop(entry.slug)}
                  >
                    {entry.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {categories.length > 0 && (
          <div className="filter-group">
            <h2>Category</h2>
            <ul className="filter-list">
              <li>
                <button
                  type="button"
                  className={category ? "" : "is-active"}
                  onClick={() => onCategory("")}
                >
                  All products
                </button>
              </li>
              {categories.map((name) => (
                <li key={name}>
                  <button
                    type="button"
                    className={category.toLowerCase() === name.toLowerCase() ? "is-active" : ""}
                    onClick={() => onCategory(name)}
                  >
                    {name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {canFilterByPrice && (
          <form
            className="filter-group"
            onSubmit={(event) => {
              event.preventDefault();
              onPrice(draftMin.trim(), draftMax.trim());
            }}
          >
            <h2>Price</h2>
            <p className="muted" style={{ margin: "0 0 8px", fontSize: "0.82rem" }}>
              The marketplace runs from {money(low)} to {money(high)}.
            </p>
            <div className="price-inputs">
              <label>
                <span>From</span>
                <input
                  value={draftMin}
                  onChange={(e) => setDraftMin(e.target.value)}
                  inputMode="decimal"
                  placeholder={low ?? ""}
                  aria-label="Lowest price"
                />
              </label>
              <label>
                <span>To</span>
                <input
                  value={draftMax}
                  onChange={(e) => setDraftMax(e.target.value)}
                  inputMode="decimal"
                  placeholder={high ?? ""}
                  aria-label="Highest price"
                />
              </label>
            </div>
            <button type="submit" className="secondary">
              Apply
            </button>
          </form>
        )}

        {active > 0 && (
          <button
            type="button"
            className="link"
            onClick={() => {
              onShop("");
              onCategory("");
              onPrice("", "");
              onSort("name");
            }}
          >
            Clear filters
          </button>
        )}

        {resultCount !== null && (
          <p className="muted result-count">
            {resultCount} product{resultCount === 1 ? "" : "s"}
          </p>
        )}
      </aside>
    </>
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
