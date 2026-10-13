"use client";

import Link from "next/link";
import { useEffect } from "react";

import { Button, LogoMark, buttonClassName } from "@platform/shared-ui";

import { brand } from "@/lib/brand";

/**
 * Shown when a page fails to render. It cannot rely on the frame (the frame
 * may be what failed), so it stands alone, says what happened in plain words,
 * and offers the two things worth trying.
 */
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-6">
      <div className="w-full max-w-md rounded-2xl border border-line bg-surface p-8 text-center shadow-[var(--shadow-lg)]">
        <LogoMark size={36} title={brand.name} className="mx-auto block" />
        <h1 className="mt-5 text-xl font-semibold text-ink">Something went wrong on this page</h1>
        <p className="mt-2 text-[14px] leading-6 text-ink-3">
          Nothing you did caused this. Try again, and if it keeps happening, share the reference
          below with whoever runs {brand.name} for you.
        </p>
        {error.digest ? (
          <p className="mt-3 font-mono text-[12px] text-muted">Reference: {error.digest}</p>
        ) : null}
        <div className="mt-6 flex justify-center gap-2">
          <Button size="sm" onClick={reset}>
            Try again
          </Button>
          <Link href="/" className={buttonClassName("secondary", "sm")}>
            Go to Home
          </Link>
        </div>
      </div>
    </main>
  );
}
