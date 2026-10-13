"use client";

import { useId } from "react";

import { Button } from "./button";
import { cx } from "./internal/cx";
import { Overlay } from "./overlay";

type ModalProps = {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  widthClassName?: string;
  /** A dialog in the middle of the screen, or a drawer along the right edge. */
  side?: "center" | "right";
};

export function Modal({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  widthClassName = "max-w-2xl",
  side = "center",
}: ModalProps) {
  const titleId = useId();
  const drawer = side === "right";
  return (
    <Overlay open={open} onClose={onClose} labelledBy={titleId} placement={drawer ? "right" : "center"}>
      {/* Capped to the viewport with the body scrolling, so the title and the
          buttons stay on screen on a laptop however long the form is. */}
      <div
        className={cx(
          "relative z-10 flex w-full flex-col border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)]",
          drawer ? "h-full rounded-l-[28px]" : "max-h-[calc(100vh-2rem)] rounded-[28px]",
          widthClassName,
        )}
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-6 py-5">
          <div>
            <h2 id={titleId} className="text-xl font-semibold text-ink">
              {title}
            </h2>
            {description ? <p className="mt-2 text-sm leading-6 text-ink-3">{description}</p> : null}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full px-2 text-lg leading-none"
          >
            ×
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer ? <div className="shrink-0 border-t border-line px-6 py-4">{footer}</div> : null}
      </div>
    </Overlay>
  );
}
