"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import type { UserNotificationListResponse } from "@platform/shared-types";

import { apiFetch } from "@/lib/api/client";
import { cx } from "@/lib/utils";
import { Badge } from "@platform/shared-ui";
import { t } from "@/lib/i18n";

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
      <Badge tone="accent">
        {unread > 99 ? "99+" : unread}
      </Badge>
    ) : (
      <span className="text-[12px] text-muted">{t("shell.notifications.inApp")}</span>
    );

  return (
    <Link
      href="/notifications"
      className={cx(
        "flex items-center justify-between rounded-2xl border px-4 py-3 text-sm transition",
        isActive
          ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] text-ink shadow-[var(--shadow-glow)]"
          : "border-line text-ink-2 hover:border-line hover:bg-surface hover:text-ink",
      )}
    >
      <span>{t("shell.notifications.label")}</span>
      {badge}
    </Link>
  );
}
