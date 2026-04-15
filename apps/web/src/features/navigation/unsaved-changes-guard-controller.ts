"use client";

export type UnsavedChangesGuardOptions = {
  when: boolean;
  title?: string;
  message?: string;
  onConfirmLeave?: () => void;
  onCancelLeave?: () => void;
};

export type UnsavedChangesNavigationKind = "link" | "history" | "programmatic";

type RegisteredGuard = {
  id: string;
  title: string;
  message: string;
  onConfirmLeave?: () => void;
  onCancelLeave?: () => void;
};

type PendingNavigation = {
  kind: UnsavedChangesNavigationKind;
  proceed: () => void;
  restore?: () => void;
  guard: RegisteredGuard;
};

export type UnsavedChangesGuardSnapshot = {
  activeGuard: RegisteredGuard | null;
  pendingNavigation: PendingNavigation | null;
  isModalOpen: boolean;
};

type RequestNavigationArgs = {
  kind: UnsavedChangesNavigationKind;
  proceed: () => void;
  restore?: () => void;
};

type Subscriber = () => void;

const DEFAULT_TITLE = "Leave this page?";
const DEFAULT_MESSAGE = "You have unsaved changes. If you leave now, those edits will be lost.";

export function createUnsavedChangesGuardController() {
  let snapshot: UnsavedChangesGuardSnapshot = {
    activeGuard: null,
    pendingNavigation: null,
    isModalOpen: false,
  };
  const subscribers = new Set<Subscriber>();

  const emit = () => {
    subscribers.forEach((subscriber) => subscriber());
  };

  const setSnapshot = (next: UnsavedChangesGuardSnapshot) => {
    snapshot = next;
    emit();
  };

  return {
    subscribe(subscriber: Subscriber) {
      subscribers.add(subscriber);
      return () => {
        subscribers.delete(subscriber);
      };
    },

    getSnapshot() {
      return snapshot;
    },

    registerGuard(id: string, options: UnsavedChangesGuardOptions) {
      if (!options.when) {
        if (snapshot.activeGuard?.id === id) {
          setSnapshot({
            activeGuard: null,
            pendingNavigation: null,
            isModalOpen: false,
          });
        }
        return;
      }

      setSnapshot({
        activeGuard: {
          id,
          title: options.title ?? DEFAULT_TITLE,
          message: options.message ?? DEFAULT_MESSAGE,
          onConfirmLeave: options.onConfirmLeave,
          onCancelLeave: options.onCancelLeave,
        },
        pendingNavigation:
          snapshot.pendingNavigation && snapshot.pendingNavigation.guard.id === id
            ? snapshot.pendingNavigation
            : null,
        isModalOpen:
          snapshot.pendingNavigation?.guard.id === id ? snapshot.isModalOpen : false,
      });
    },

    unregisterGuard(id: string) {
      if (snapshot.activeGuard?.id !== id) {
        return;
      }

      setSnapshot({
        activeGuard: null,
        pendingNavigation: null,
        isModalOpen: false,
      });
    },

    requestNavigation(args: RequestNavigationArgs) {
      if (!snapshot.activeGuard) {
        args.proceed();
        return false;
      }

      setSnapshot({
        ...snapshot,
        pendingNavigation: {
          kind: args.kind,
          proceed: args.proceed,
          restore: args.restore,
          guard: snapshot.activeGuard,
        },
        isModalOpen: true,
      });
      return true;
    },

    confirmNavigation() {
      const pending = snapshot.pendingNavigation;
      setSnapshot({
        ...snapshot,
        pendingNavigation: null,
        isModalOpen: false,
      });

      if (!pending) {
        return;
      }

      pending.guard.onConfirmLeave?.();
      pending.proceed();
    },

    cancelNavigation() {
      const pending = snapshot.pendingNavigation;
      setSnapshot({
        ...snapshot,
        pendingNavigation: null,
        isModalOpen: false,
      });

      if (!pending) {
        return;
      }

      pending.guard.onCancelLeave?.();
      pending.restore?.();
    },
  };
}
