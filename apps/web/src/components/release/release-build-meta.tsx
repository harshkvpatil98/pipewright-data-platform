"use client";

import { useState } from "react";

import { appConfig } from "@/lib/config";

function buildLine(): string {
  const parts: string[] = [];
  if (appConfig.releaseVersion) {
    parts.push(appConfig.releaseVersion.startsWith("v") ? appConfig.releaseVersion : `v${appConfig.releaseVersion}`);
  }
  if (appConfig.gitSha) {
    parts.push(`git ${appConfig.gitSha.slice(0, 7)}`);
  }
  if (appConfig.buildDate) {
    parts.push(appConfig.buildDate);
  }
  return parts.join(" · ");
}

type ReleaseBuildMetaProps = {
  className?: string;
};

/** Subtle web build stamp + copy; renders nothing if no env vars set. */
export function ReleaseBuildMeta({ className = "" }: ReleaseBuildMetaProps) {
  const line = buildLine();
  const [copied, setCopied] = useState(false);

  if (!line) {
    return null;
  }

  return (
    <div className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] leading-4 text-slate-500 ${className}`}>
      <span className="text-slate-600">Web UI</span>
      <span className="font-mono text-slate-500">{line}</span>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard.writeText(line).then(
            () => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 2000);
            },
            () => {},
          );
        }}
        className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-white/20 hover:text-slate-300"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
