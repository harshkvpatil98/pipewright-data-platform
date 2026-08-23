"use client";

import { useEffect, useState } from "react";

import { CopyField } from "@/features/demo/components/copy-field";

type CopyAppUrlProps = {
  label: string;
  path: string;
};

/** Builds absolute URL using the current browser origin (client-only). */
export function CopyAppUrl({ label, path }: CopyAppUrlProps) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const [full, setFull] = useState<string | null>(null);

  useEffect(() => {
    setFull(`${window.location.origin}${normalized}`);
  }, [normalized]);

  if (full === null) {
    return (
      <div className="rounded-xl border border-line bg-surface px-3 py-3 text-xs text-muted">
        {label} — preparing link…
      </div>
    );
  }

  return <CopyField label={label} value={full} />;
}
