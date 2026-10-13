"use client";

import { Tooltip } from "@/components/ui/tooltip";
import { cx } from "@/lib/utils";
import { Icon, type IconName } from "@platform/shared-ui";

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
 * A page's actions, on one line under the tabs: each button an icon and its
 * name side by side, the way buttons look everywhere else, with groups kept
 * apart by a thin divider and named for screen readers. It replaced the
 * Office-style ribbon (icons over tiny labels, a caption under each group),
 * which drew a second, taller kind of button on four pages (A6).
 */
export function Ribbon({ groups, className }: RibbonProps) {
  if (groups.length === 0) return null;

  return (
    <div
      data-tour="ribbon"
      role="toolbar"
      className={cx("border-b border-line bg-[color:var(--panel)]", className)}
    >
      <div className="flex items-center gap-1 overflow-x-auto px-4 py-1.5 lg:px-6">
        {groups.map((group, groupIndex) => (
          <div key={group.id} role="group" aria-label={group.label} className="flex items-center gap-1">
            {groupIndex > 0 ? <span className="mx-1.5 h-5 w-px shrink-0 bg-line" aria-hidden="true" /> : null}
            {group.actions.map((action) => (
              <RibbonButton key={action.id} action={action} />
            ))}
          </div>
        ))}
      </div>
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
      className={cx(
        "inline-flex h-8 shrink-0 select-none items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 text-[13.5px] transition duration-[var(--duration-fast)] ease-[var(--ease-out)]",
        action.disabled ? "cursor-not-allowed opacity-40" : "hover:bg-surface-2 active:scale-[0.98]",
        action.prominent && !action.disabled
          ? "bg-[color:var(--accent)] font-medium text-accent-ink hover:bg-[color:var(--accent-hover)]"
          : "text-ink-2 hover:text-ink",
      )}
    >
      <Icon name={action.icon} size={15} />
      {action.label}
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
