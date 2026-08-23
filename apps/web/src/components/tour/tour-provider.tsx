"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";

import { Icon } from "@/components/ui/icon";
import { cx } from "@/lib/utils";

export type TourStep = {
  /** Matches a `data-tour="..."` attribute on the element to highlight. */
  target: string;
  title: string;
  body: string;
  /** Where the card sits relative to the target. "center" ignores the target. */
  placement?: "top" | "bottom" | "left" | "right" | "center";
};

type Rect = { top: number; left: number; width: number; height: number };

type TourContextValue = {
  start: (steps: TourStep[], tourId: string) => void;
  /** Runs the tour only if this browser has not completed it before. */
  startIfUnseen: (steps: TourStep[], tourId: string) => void;
  active: boolean;
};

const TourContext = createContext<TourContextValue | null>(null);

const STORAGE_PREFIX = "pipewright.tour.";
const CARD_WIDTH = 340;
const GAP = 14;

function seen(tourId: string): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(`${STORAGE_PREFIX}${tourId}`) === "done";
  } catch {
    return true;
  }
}

function markSeen(tourId: string): void {
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${tourId}`, "done");
  } catch {
    /* private browsing: the tour simply runs again next time */
  }
}

export function TourProvider({ children }: { children: React.ReactNode }) {
  const [steps, setSteps] = useState<TourStep[]>([]);
  const [tourId, setTourId] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);

  const active = steps.length > 0;
  const step = active ? steps[index] : null;

  const start = useCallback((nextSteps: TourStep[], id: string) => {
    setSteps(nextSteps);
    setTourId(id);
    setIndex(0);
  }, []);

  const startIfUnseen = useCallback(
    (nextSteps: TourStep[], id: string) => {
      if (!seen(id)) start(nextSteps, id);
    },
    [start],
  );

  const finish = useCallback(() => {
    if (tourId) markSeen(tourId);
    setSteps([]);
    setTourId(null);
    setIndex(0);
    setRect(null);
  }, [tourId]);

  // Measure the current target, following it through scrolls and resizes.
  useLayoutEffect(() => {
    if (!step) return;

    const measure = () => {
      if (step.placement === "center") {
        setRect(null);
        return;
      }
      const element = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
      if (!element) {
        setRect(null);
        return;
      }
      const box = element.getBoundingClientRect();
      setRect({ top: box.top, left: box.left, width: box.width, height: box.height });
    };

    const element = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
    element?.scrollIntoView({ block: "center", behavior: "smooth" });

    // Let the smooth scroll land before measuring.
    const settle = setTimeout(measure, 320);
    measure();

    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      clearTimeout(settle);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step]);

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") finish();
      if (event.key === "ArrowRight" || event.key === "Enter") {
        setIndex((current) => (current + 1 < steps.length ? current + 1 : (finish(), current)));
      }
      if (event.key === "ArrowLeft") setIndex((current) => Math.max(0, current - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, steps.length, finish]);

  const value = useMemo<TourContextValue>(
    () => ({ start, startIfUnseen, active }),
    [start, startIfUnseen, active],
  );

  return (
    <TourContext.Provider value={value}>
      {children}
      {active && step ? (
        <TourOverlay
          step={step}
          rect={rect}
          index={index}
          total={steps.length}
          onBack={() => setIndex((current) => Math.max(0, current - 1))}
          onNext={() =>
            setIndex((current) => {
              if (current + 1 >= steps.length) {
                finish();
                return current;
              }
              return current + 1;
            })
          }
          onSkip={finish}
        />
      ) : null}
    </TourContext.Provider>
  );
}

type OverlayProps = {
  step: TourStep;
  rect: Rect | null;
  index: number;
  total: number;
  onBack: () => void;
  onNext: () => void;
  onSkip: () => void;
};

function TourOverlay({ step, rect, index, total, onBack, onNext, onSkip }: OverlayProps) {
  const isLast = index + 1 === total;
  const placement = step.placement ?? "bottom";
  const centered = placement === "center" || !rect;

  // The spotlight is a transparent box with an enormous shadow, which dims
  // everything except the cut-out without needing an SVG mask.
  const spotlight = rect
    ? {
        top: rect.top - 6,
        left: rect.left - 6,
        width: rect.width + 12,
        height: rect.height + 12,
      }
    : null;

  const card = computeCardPosition(placement, rect);

  return (
    <div className="fixed inset-0 z-[90]" role="dialog" aria-modal="true" aria-label={step.title}>
      {spotlight ? (
        <div
          className="pointer-events-none absolute rounded-xl ring-2 ring-[color:var(--accent)] transition-all duration-300 ease-[var(--ease-out)]"
          style={{
            top: spotlight.top,
            left: spotlight.left,
            width: spotlight.width,
            height: spotlight.height,
            boxShadow: "0 0 0 9999px rgba(3, 6, 14, 0.74)",
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-scrim" />
      )}

      {/* Click-through blocker so the tour is modal while it runs. */}
      <button
        type="button"
        aria-label="Skip tour"
        onClick={onSkip}
        className="absolute inset-0 cursor-default"
        tabIndex={-1}
      />

      {rect && !centered ? <Pointer placement={placement} rect={rect} /> : null}

      <div
        className={cx(
          "absolute w-[min(340px,calc(100vw-2rem))] rounded-2xl border border-line bg-[color:var(--panel-strong)] p-5 shadow-[var(--shadow-lg)] backdrop-blur-xl",
          "animate-fade-up",
        )}
        style={card}
      >
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-[color:var(--accent)] text-[11px] font-semibold text-accent-ink">
            {index + 1}
          </span>
          <h3 className="text-sm font-semibold text-ink">{step.title}</h3>
        </div>
        <p className="mt-2.5 text-sm leading-6 text-ink-2">{step.body}</p>

        <div className="mt-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            {Array.from({ length: total }).map((_, dot) => (
              <span
                key={dot}
                className={cx(
                  "h-1.5 rounded-full transition-all duration-[var(--duration-base)]",
                  dot === index ? "w-5 bg-[color:var(--accent)]" : "w-1.5 bg-surface-2",
                )}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onSkip}
              className="rounded-lg px-2.5 py-1.5 text-xs text-ink-3 transition hover:bg-surface-2 hover:text-ink"
            >
              Skip
            </button>
            {index > 0 ? (
              <button
                type="button"
                onClick={onBack}
                className="rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink transition hover:bg-surface-2"
              >
                Back
              </button>
            ) : null}
            <button
              type="button"
              onClick={onNext}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[color:var(--accent)] px-3 py-1.5 text-xs font-medium text-accent-ink transition hover:brightness-110"
            >
              {isLast ? "Finish" : "Next"}
              {!isLast ? <Icon name="chevronRight" size={13} /> : null}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** The little triangle that points from the card at the highlighted element. */
function Pointer({ placement, rect }: { placement: string; rect: Rect }) {
  const base = "absolute h-3 w-3 rotate-45 bg-[color:var(--panel-strong)] border-line";
  const style: React.CSSProperties = {};
  let classes = "";

  if (placement === "bottom") {
    style.top = rect.top + rect.height + GAP - 6;
    style.left = Math.min(
      Math.max(rect.left + rect.width / 2 - 6, 24),
      window.innerWidth - 36,
    );
    classes = "border-l border-t";
  } else if (placement === "top") {
    style.top = rect.top - GAP - 6;
    style.left = Math.min(Math.max(rect.left + rect.width / 2 - 6, 24), window.innerWidth - 36);
    classes = "border-r border-b";
  } else if (placement === "right") {
    style.left = rect.left + rect.width + GAP - 6;
    style.top = rect.top + rect.height / 2 - 6;
    classes = "border-l border-b";
  } else {
    style.left = rect.left - GAP - 6;
    style.top = rect.top + rect.height / 2 - 6;
    classes = "border-r border-t";
  }

  return <div className={cx(base, classes)} style={style} />;
}

function computeCardPosition(placement: string, rect: Rect | null): React.CSSProperties {
  if (!rect || placement === "center") {
    return { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  }

  const viewportWidth = typeof window === "undefined" ? 1280 : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 800 : window.innerHeight;
  const clampLeft = (value: number) =>
    Math.min(Math.max(value, 16), Math.max(16, viewportWidth - CARD_WIDTH - 16));

  switch (placement) {
    case "top":
      return {
        top: Math.max(16, rect.top - GAP),
        left: clampLeft(rect.left + rect.width / 2 - CARD_WIDTH / 2),
        transform: "translateY(-100%)",
      };
    case "right":
      return {
        top: Math.min(Math.max(16, rect.top - 20), viewportHeight - 220),
        left: clampLeft(rect.left + rect.width + GAP),
      };
    case "left":
      return {
        top: Math.min(Math.max(16, rect.top - 20), viewportHeight - 220),
        left: clampLeft(rect.left - CARD_WIDTH - GAP),
      };
    default:
      return {
        top: rect.top + rect.height + GAP,
        left: clampLeft(rect.left + rect.width / 2 - CARD_WIDTH / 2),
      };
  }
}

export function useTour(): TourContextValue {
  const context = useContext(TourContext);
  if (!context) {
    throw new Error("useTour must be used inside <TourProvider>.");
  }
  return context;
}
