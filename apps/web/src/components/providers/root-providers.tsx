"use client";

import { ThemeProvider } from "@/components/providers/theme-provider";
import { TourProvider } from "@/components/tour/tour-provider";
import { NavigationGuardProvider } from "@/features/navigation/unsaved-changes-guard";
import { useSessionKeepAlive } from "@/lib/auth/use-session-keep-alive";
import { ToastProvider } from "@platform/shared-ui";

export function RootProviders({ children }: { children: React.ReactNode }) {
  useSessionKeepAlive();
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
