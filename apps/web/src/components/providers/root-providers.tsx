"use client";

import { ThemeProvider } from "@/components/providers/theme-provider";
import { ToastProvider } from "@/components/providers/toast-provider";
import { TourProvider } from "@/components/tour/tour-provider";
import { NavigationGuardProvider } from "@/features/navigation/unsaved-changes-guard";

export function RootProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <NavigationGuardProvider>
        <ToastProvider>
          <TourProvider>{children}</TourProvider>
        </ToastProvider>
      </NavigationGuardProvider>
    </ThemeProvider>
  );
}
