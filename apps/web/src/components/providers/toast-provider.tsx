"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

import { Icon, type IconName } from "@/components/ui/icon";
import { cx } from "@/lib/utils";

export type ToastTone = "success" | "error" | "info" | "warning";

type Toast = {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
};

type ToastContextValue = {
  notify: (toast: Omit<Toast, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_STYLES: Record<ToastTone, { icon: IconName; className: string }> = {
  success: { icon: "check", className: "border-success-line bg-success-soft text-success" },
  error: { icon: "warning", className: "border-danger-line bg-danger-soft text-danger" },
  warning: { icon: "warning", className: "border-warning-line bg-warning-soft text-warning" },
  info: { icon: "info", className: "border-info-line bg-info-soft text-info" },
};

const AUTO_DISMISS_MS = 5200;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = nextId.current++;
      // Cap the stack so a burst of failures cannot cover the screen.
      setToasts((current) => [...current.slice(-3), { ...toast, id }]);
      setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      notify,
      success: (title, description) => notify({ tone: "success", title, description }),
      error: (title, description) => notify({ tone: "error", title, description }),
      info: (title, description) => notify({ tone: "info", title, description }),
    }),
    [notify],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-10 right-5 z-[80] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2"
        role="status"
        aria-live="polite"
      >
        {toasts.map((toast) => {
          const tone = TONE_STYLES[toast.tone];
          return (
            <div
              key={toast.id}
              className={cx(
                "pointer-events-auto flex items-start gap-3 rounded-2xl border px-4 py-3 shadow-[var(--shadow-lg)] backdrop-blur-xl",
                "animate-fade-up",
                tone.className,
              )}
            >
              <Icon name={tone.icon} size={16} className="mt-0.5 shrink-0 opacity-90" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{toast.title}</div>
                {toast.description ? (
                  <div className="mt-0.5 text-xs leading-5 opacity-80">{toast.description}</div>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                className="shrink-0 rounded-md p-1 opacity-60 transition hover:bg-surface-2 hover:opacity-100"
                aria-label="Dismiss"
              >
                <Icon name="close" size={13} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used inside <ToastProvider>.");
  }
  return context;
}
