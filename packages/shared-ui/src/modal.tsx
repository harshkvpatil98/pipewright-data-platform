"use client";

import { useEffect } from "react";

import { Button } from "./button";
import { cx } from "./internal/cx";

type ModalProps = {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  widthClassName?: string;
};

export function Modal({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  widthClassName = "max-w-2xl",
}: ModalProps) {
  useEffect(() => {
    if (!open) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-4 backdrop-blur-sm">
      <button aria-label="Close modal backdrop" className="absolute inset-0" onClick={onClose} />
      <div
        className={cx(
          "relative z-10 w-full rounded-[28px] border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)]",
          widthClassName,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
          <div>
            <h2 className="text-xl font-semibold text-ink">{title}</h2>
            {description ? <p className="mt-2 text-sm leading-6 text-ink-3">{description}</p> : null}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="rounded-full px-2">
            ×
          </Button>
        </div>
        <div className="px-6 py-5">{children}</div>
        {footer ? <div className="border-t border-line px-6 py-4">{footer}</div> : null}
      </div>
    </div>
  );
}
