"use client";

import { NavigationGuardProvider } from "@/features/navigation/unsaved-changes-guard";

export function RootProviders({ children }: { children: React.ReactNode }) {
  return <NavigationGuardProvider>{children}</NavigationGuardProvider>;
}
