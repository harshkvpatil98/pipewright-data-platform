"use client";

import { Icon, type IconName } from "@/components/ui/icon";
import { Tooltip } from "@/components/ui/tooltip";
import { cx } from "@/lib/utils";

export type RibbonAction = {
  id: string;
  label: string;
  icon: IconName;
  hint?: string;
  onClick?: () => void;
  href?: string;
  disabled?: boolean;
  /** Large buttons anchor a group the way a primary action does in Office. */
  prominent?: boolean;
};

export type RibbonGroup = {
  id: string;
  label: string;
  actions: RibbonAction[];
};

type RibbonProps = {
  groups: RibbonGroup[];
  className?: string;
};

/**
 * Contextual command surface, in the shape Office and Power BI use: actions are
 * grouped by task with a labelled divider, so a user scans group titles rather
 * than reading every button.
 */
export function Ribbon({ groups, className }: RibbonProps) {
  if (groups.length === 0) return null;

  return (
    <div
      data-tour="ribbon"
      className={cx("relative border-b border-line bg-[color:var(--surface-sunken)]", className)}
    >
      <div className="flex items-stretch gap-1 overflow-x-auto px-3 py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {groups.map((group, groupIndex) => (
          <div key={group.id} className="flex items-stretch">
            <div className="flex flex-col items-center gap-1 px-2">
              <div className="flex items-end gap-1">
                {group.actions.map((action) => (
                  <RibbonButton key={action.id} action={action} />
                ))}
              </div>
              <span className="whitespace-nowrap text-[10px] uppercase tracking-[0.16em] text-muted">
                {group.label}
              </span>
            </div>
            {groupIndex < groups.length - 1 ? (
              <div className="my-1 w-px shrink-0 bg-surface-2" aria-hidden="true" />
            ) : null}
          </div>
        ))}
      </div>
      {/* Signals that the toolbar continues past the right edge. */}
      <div
        className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-[color:var(--surface-sunken)] to-transparent"
        aria-hidden="true"
      />
    </div>
  );
}

function RibbonButton({ action }: { action: RibbonAction }) {
  const Component = action.href ? "a" : "button";

  const content = (
    <Component
      {...(action.href ? { href: action.href } : { type: "button" as const })}
      onClick={action.onClick}
      disabled={action.disabled}
      aria-label={action.label}
      className={cx(
        "group inline-flex select-none flex-col items-center justify-center gap-1 rounded-lg border border-transparent transition duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        action.prominent ? "min-w-[62px] px-2.5 py-1.5" : "min-w-[54px] px-2 py-1.5",
        action.disabled
          ? "cursor-not-allowed opacity-35"
          : "hover:border-line hover:bg-surface-2 active:scale-[0.97]",
        action.prominent && !action.disabled
          ? "bg-[color:var(--accent-faint)] text-ink hover:bg-[color:var(--accent-soft)]"
          : "text-ink-2",
      )}
    >
      <Icon name={action.icon} size={action.prominent ? 19 : 17} />
      <span className="text-[10.5px] leading-none">{action.label}</span>
    </Component>
  );

  return action.hint ? (
    <Tooltip label={action.label} shortcut={action.hint} side="bottom">
      {content}
    </Tooltip>
  ) : (
    content
  );
}
