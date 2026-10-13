"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { buttonClassName, Icon, type IconName } from "@platform/shared-ui";

import { cx } from "@/lib/utils";

export type ActionMenuItem = {
  id: string;
  label: string;
  icon?: IconName;
  /** A short line under the label saying what it does. */
  description?: string;
  href?: string;
  onSelect?: () => void;
};

type ActionMenuProps = {
  label: string;
  icon?: IconName;
  items: ActionMenuItem[];
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
};

/**
 * A button that opens a short list of related actions. The detail-page
 * template allows three visible actions; everything else lives in one of
 * these, so a page header stops being a wall of equal-weight buttons.
 */
export function ActionMenu({
  label,
  icon,
  items,
  variant = "secondary",
  size = "sm",
}: ActionMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (items.length === 0) return null;

  const row =
    "flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition hover:bg-surface-2";
  const body = (item: ActionMenuItem) => (
    <>
      {item.icon ? <Icon name={item.icon} size={15} className="mt-0.5 shrink-0 text-ink-3" /> : null}
      <span className="min-w-0">
        <span className="block text-[13.5px] text-ink">{item.label}</span>
        {item.description ? (
          <span className="block text-[12px] leading-4 text-muted">{item.description}</span>
        ) : null}
      </span>
    </>
  );

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((current) => !current)}
        className={buttonClassName(variant, size)}
      >
        {icon ? <Icon name={icon} size={15} /> : null}
        {label}
        <Icon name="chevronDown" size={13} className={cx("transition", open && "rotate-180")} />
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          className="animate-fade-up absolute right-0 top-full z-40 mt-2 w-64 rounded-xl border border-line bg-[color:var(--panel-strong)] p-1.5 shadow-[var(--shadow-lg)]"
        >
          {items.map((item) =>
            item.href ? (
              <Link
                key={item.id}
                href={item.href}
                role="menuitem"
                onClick={() => setOpen(false)}
                className={row}
              >
                {body(item)}
              </Link>
            ) : (
              <button
                key={item.id}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  item.onSelect?.();
                }}
                className={row}
              >
                {body(item)}
              </button>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}
