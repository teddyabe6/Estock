"use client";

/**
 * One product, with its own shareable link: photo, description, price,
 * options, availability and the seller's contact details (PRD 13).
 */

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { EnquiryForm, ProductImage, SellerContact, Stepper, StorefrontShell } from "@/components/Storefront";
import { Alert } from "@/components/ui";
import { money } from "@/lib/format";
import { shopApi, useBasket, type PublicProduct, type PublicVariant, type Shop } from "@/lib/storefront";

export default function ProductPage({
  params,
}: {
  params: Promise<{ slug: string; productId: string }>;
}) {
  const { slug, productId } = use(params);
  const [shop, setShop] = useState<Shop | null>(null);
  const [product, setProduct] = useState<PublicProduct | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [variant, setVariant] = useState<PublicVariant | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [added, setAdded] = useState(false);
  const [asking, setAsking] = useState(false);
  const [shared, setShared] = useState(false);
  const basket = useBasket(slug);
  const currency = shop?.currency ?? "ETB";

  useEffect(() => {
    Promise.all([shopApi.shop(slug), shopApi.product(slug, productId)])
      .then(([s, p]) => {
        setShop(s);
        setProduct(p);
        setVariant(p.variants.find((v) => v.is_default && v.in_stock) ?? p.variants.find((v) => v.in_stock) ?? p.variants[0] ?? null);
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "This product is not available"));
  }, [slug, productId]);

  function add() {
    if (!product || !variant) return;
    basket.add(
      {
        variantId: variant.id,
        productId: product.id,
        name: product.name,
        variantName: variant.name,
        unit: product.unit_of_measure,
        price: variant.price ?? product.price,
        imageUrl: product.image_url,
      },
      quantity,
    );
    setAdded(true);
  }

  async function share() {
    const url = window.location.href;
    try {
      if (navigator.share) {
        await navigator.share({ title: product?.name, url });
        return;
      }
      await navigator.clipboard?.writeText(url);
      setShared(true);
    } catch {
      // The visitor dismissed the share sheet; nothing to do.
    }
  }

  if (error) {
    return (
      <main style={{ maxWidth: 720, margin: "10vh auto", padding: "0 16px" }}>
        <Alert>{error}</Alert>
        <p>
          <Link href={`/shop/${slug}`}>Back to the shop</Link>
        </p>
      </main>
    );
  }

  const price = variant?.price ?? product?.price ?? null;
  const inStock = variant ? variant.in_stock : product?.in_stock ?? false;

  return (
    <StorefrontShell slug={slug} shop={shop} basketCount={basket.count} basketTotal={basket.total}>
      <p className="crumbs">
        <Link href={`/shop/${slug}`}>All products</Link>
        {product?.category && (
          <>
            {" › "}
            <Link href={`/shop/${slug}?category=${encodeURIComponent(product.category)}`}>{product.category}</Link>
          </>
        )}
      </p>

      {!product ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="product-hero">
          <ProductImage src={product.image_url} name={product.name} className="thumb hero" />
          <div>
            {product.brand && <div className="label muted">{product.brand}</div>}
            <h1 style={{ marginTop: 0 }}>{product.name}</h1>
            <div className="price big">
              {price ? money(price, currency) : <span className="muted">Ask for a price</span>}
              <span className="muted unit"> / {product.unit_of_measure}</span>
            </div>
            <p>
              <span className={`badge ${inStock ? "ok" : "warn"}`}>{inStock ? "In stock" : "Out of stock"}</span>
            </p>
            {product.description && <p className="description">{product.description}</p>}

            {product.variants.length > 1 && (
              <div className="variant-list">
                <div className="label muted">Options</div>
                <div className="row">
                  {product.variants.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      className={`chip${variant?.id === option.id ? " is-active" : ""}`}
                      onClick={() => {
                        setVariant(option);
                        setAdded(false);
                      }}
                    >
                      {option.name ?? "Standard"}
                      {option.price ? ` · ${money(option.price, currency)}` : ""}
                      {!option.in_stock ? " · out of stock" : ""}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="row" style={{ marginTop: 14 }}>
              <Stepper value={quantity} onChange={(next) => setQuantity(Math.max(next, 0.001))} />
              <button type="button" onClick={add} disabled={!variant}>
                Add to basket
              </button>
            </div>
            {added && (
              <Alert kind="ok">
                Added to your basket.{" "}
                <Link href={`/shop/${slug}/basket`}>View basket and request a proforma →</Link>
              </Alert>
            )}
            {!inStock && (
              <p className="muted" style={{ fontSize: "0.88rem" }}>
                You can still request it: the seller will tell you when it is available.
              </p>
            )}

            <div className="row" style={{ marginTop: 18 }}>
              <button type="button" className="secondary" onClick={() => setAsking((v) => !v)}>
                {asking ? "Close" : "Ask about this item"}
              </button>
              <button type="button" className="secondary" onClick={() => void share()}>
                {shared ? "Link copied" : "Share"}
              </button>
            </div>
            {shop && (
              <div style={{ marginTop: 14 }}>
                <div className="label muted">Contact the seller</div>
                <SellerContact shop={shop} />
              </div>
            )}
          </div>
        </div>
      )}

      {asking && product && <EnquiryForm slug={slug} product={product} onDone={() => setAsking(false)} />}
    </StorefrontShell>
  );
}
