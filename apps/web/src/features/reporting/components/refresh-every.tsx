"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Fetch the page again every so often, as its owner set the dashboard to, so
 * a shared or embedded dashboard on a wall screen stays current. Paused while
 * the page is hidden, so a background tab costs nothing.
 */
export function RefreshEvery({ seconds }: { seconds: number | null }) {
  const router = useRouter();
  useEffect(() => {
    if (!seconds || seconds < 30) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, seconds * 1000);
    return () => window.clearInterval(timer);
  }, [router, seconds]);
  return null;
}
