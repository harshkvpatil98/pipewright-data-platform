"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { UnsavedChangesModal } from "@/components/modals/unsaved-changes-modal";
import {
  createUnsavedChangesGuardController,
  type UnsavedChangesGuardOptions,
  type UnsavedChangesNavigationKind,
} from "@/features/navigation/unsaved-changes-guard-controller";

type NavigationGuardContextValue = {
  registerGuard: (id: string, options: UnsavedChangesGuardOptions) => void;
  unregisterGuard: (id: string) => void;
  confirmNavigation: (args: {
    kind?: UnsavedChangesNavigationKind;
    proceed: () => void;
    restore?: () => void;
  }) => void;
};

const NavigationGuardContext = createContext<NavigationGuardContextValue | null>(null);

export function NavigationGuardProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const controller = useMemo(() => createUnsavedChangesGuardController(), []);
  const [snapshot, setSnapshot] = useState(controller.getSnapshot());
  const historySentinelArmedRef = useRef(false);
  const ignoreNextPopStateRef = useRef(false);
  const skipHistoryCleanupRef = useRef(false);

  useEffect(() => controller.subscribe(() => setSnapshot(controller.getSnapshot())), [controller]);

  useEffect(() => {
    if (!snapshot.activeGuard) {
      return;
    }

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [snapshot.activeGuard]);

  useEffect(() => {
    const handleDocumentClick = (event: MouseEvent) => {
      if (!controller.getSnapshot().activeGuard) {
        return;
      }
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }

      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }

      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) {
        return;
      }
      if (anchor.target && anchor.target !== "_self") {
        return;
      }
      if (anchor.hasAttribute("download")) {
        return;
      }

      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:")) {
        return;
      }

      const nextUrl = new URL(anchor.href, window.location.href);
      const currentUrl = new URL(window.location.href);
      if (nextUrl.origin !== currentUrl.origin) {
        return;
      }
      if (
        nextUrl.pathname === currentUrl.pathname &&
        nextUrl.search === currentUrl.search &&
        nextUrl.hash === currentUrl.hash
      ) {
        return;
      }

      event.preventDefault();
      controller.requestNavigation({
        kind: "link",
        proceed: () => router.push(`${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`),
      });
    };

    document.addEventListener("click", handleDocumentClick, true);
    return () => document.removeEventListener("click", handleDocumentClick, true);
  }, [controller, router]);

  useEffect(() => {
    if (!snapshot.activeGuard || historySentinelArmedRef.current) {
      return;
    }

    window.history.pushState(
      { ...(window.history.state ?? {}), __unsavedChangesGuard: true },
      "",
      window.location.href,
    );
    historySentinelArmedRef.current = true;
  }, [snapshot.activeGuard]);

  useEffect(() => {
    if (snapshot.activeGuard || !historySentinelArmedRef.current) {
      return;
    }
    if (skipHistoryCleanupRef.current) {
      skipHistoryCleanupRef.current = false;
      historySentinelArmedRef.current = false;
      return;
    }

    ignoreNextPopStateRef.current = true;
    historySentinelArmedRef.current = false;
    window.history.back();
  }, [snapshot.activeGuard]);

  useEffect(() => {
    const handlePopState = () => {
      if (ignoreNextPopStateRef.current) {
        ignoreNextPopStateRef.current = false;
        return;
      }
      if (!controller.getSnapshot().activeGuard) {
        return;
      }

      historySentinelArmedRef.current = false;
      controller.requestNavigation({
        kind: "history",
        proceed: () => {
          ignoreNextPopStateRef.current = true;
          window.history.back();
        },
        restore: () => {
          window.history.pushState(
            { ...(window.history.state ?? {}), __unsavedChangesGuard: true },
            "",
            window.location.href,
          );
          historySentinelArmedRef.current = true;
        },
      });
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [controller]);

  const contextValue = useMemo<NavigationGuardContextValue>(
    () => ({
      registerGuard: (id, options) => controller.registerGuard(id, options),
      unregisterGuard: (id) => controller.unregisterGuard(id),
      confirmNavigation: ({ kind = "programmatic", proceed, restore }) => {
        controller.requestNavigation({ kind, proceed, restore });
      },
    }),
    [controller],
  );

  return (
    <NavigationGuardContext.Provider value={contextValue}>
      {children}
      <UnsavedChangesModal
        open={snapshot.isModalOpen}
        title={snapshot.pendingNavigation?.guard.title ?? "Leave this page?"}
        message={
          snapshot.pendingNavigation?.guard.message ??
          "You have unsaved changes. If you leave now, those edits will be lost."
        }
        onStay={() => controller.cancelNavigation()}
        onLeave={() => {
          skipHistoryCleanupRef.current = true;
          controller.confirmNavigation();
        }}
      />
    </NavigationGuardContext.Provider>
  );
}

export function useNavigationGuard() {
  const context = useContext(NavigationGuardContext);
  if (!context) {
    throw new Error("useNavigationGuard must be used within NavigationGuardProvider.");
  }
  return context;
}

export function useUnsavedChangesGuard(options: UnsavedChangesGuardOptions) {
  const { registerGuard, unregisterGuard } = useNavigationGuard();
  const guardIdRef = useRef<string>(createGuardId());

  useEffect(() => {
    registerGuard(guardIdRef.current, options);
    return () => unregisterGuard(guardIdRef.current);
  }, [
    options.message,
    options.onCancelLeave,
    options.onConfirmLeave,
    options.title,
    options.when,
    registerGuard,
    unregisterGuard,
  ]);
}

function createGuardId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `unsaved_guard_${Math.random().toString(36).slice(2, 10)}`;
}
