"use client";

import { useEffect } from "react";

import { cx } from "./internal/cx";

type OverlayProps = {
  open: boolean;
  onClose: () => void;
  /** The accessible name, when no visible heading names the layer. */
  label?: string;
  /** The id of the heading that names the layer. */
  labelledBy?: string;
  /** Where the content sits: centred, near the top (palettes), along the right edge (drawers), or placed by the caller. */
  placement?: "center" | "top" | "right" | "free";
  /** Dim and blur what is behind. Off for a coach mark that draws its own. */
  scrim?: boolean;
  /** Close when the dimmed area is clicked. */
  closeOnScrim?: boolean;
  /** Stacking: dialogs, then palettes above them, then the tour above everything. */
  layer?: "dialog" | "palette" | "tour";
  className?: string;
  children: React.ReactNode;
};

const LAYERS: Record<NonNullable<OverlayProps["layer"]>, string> = {
  dialog: "z-50",
  palette: "z-[85]",
  tour: "z-[90]",
};

const PLACEMENT: Record<NonNullable<OverlayProps["placement"]>, string> = {
  center: "flex items-center justify-center p-4",
  top: "flex items-start justify-center px-4 pt-[12vh]",
  right: "flex justify-end",
  free: "",
};

/**
 * Anything that sits above the page and takes the keyboard: dialogs, drawers,
 * palettes and the tour. One place handles Escape, the scrim and the dialog
 * semantics, so every layer closes the same way.
 */
export function Overlay({
  open,
  onClose,
  label,
  labelledBy,
  placement = "center",
  scrim = true,
  closeOnScrim = true,
  layer = "dialog",
  className,
  children,
}: OverlayProps) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={labelledBy ? undefined : label}
      aria-labelledby={labelledBy}
      className={cx("fixed inset-0", LAYERS[layer], PLACEMENT[placement], scrim && "bg-scrim backdrop-blur-sm", className)}
    >
      {scrim && closeOnScrim ? (
        <button aria-label="Close" tabIndex={-1} className="absolute inset-0 cursor-default" onClick={onClose} />
      ) : null}
      {children}
    </div>
  );
}
