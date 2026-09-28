"use client";

/** The basket moved to the shared cart; keep old links working. */

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function BasketRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/cart");
  }, [router]);
  return null;
}
