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
      <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-3 text-xs text-slate-500">
        {label} — preparing link…
      </div>
    );
  }

  return <CopyField label={label} value={full} />;
}
