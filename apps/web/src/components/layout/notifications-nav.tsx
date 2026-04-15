"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import type { UserNotificationListResponse } from "@platform/shared-types";

import { apiFetch } from "@/lib/api/client";
import { cx } from "@/lib/utils";

export function NotificationsNavLink() {
  const pathname = usePathname();
  const [unread, setUnread] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<UserNotificationListResponse>("/notifications?limit=1");
        if (!cancelled) {
          setUnread(data.unread_count);
        }
      } catch {
        if (!cancelled) {
          setUnread(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  const isActive = pathname === "/notifications" || pathname.startsWith("/notifications/");
  const badge =
    unread !== null && unread > 0 ? (
      <span className="rounded-full bg-indigo-500/25 px-2 py-0.5 text-[10px] font-semibold text-indigo-100">
        {unread > 99 ? "99+" : unread}
      </span>
    ) : (
      <span className="text-[11px] uppercase tracking-[0.18em] text-slate-500">In-app</span>
    );

  return (
    <Link
      href="/notifications"
      className={cx(
        "flex items-center justify-between rounded-2xl border px-4 py-3 text-sm transition",
        isActive
          ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] text-white shadow-[0_12px_30px_rgba(79,70,229,0.14)]"
          : "border-white/5 text-slate-300 hover:border-white/12 hover:bg-white/[0.05] hover:text-white",
      )}
    >
      <span>Notifications</span>
      {badge}
    </Link>
  );
}
