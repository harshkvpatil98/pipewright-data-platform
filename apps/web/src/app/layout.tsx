import type { Metadata } from "next";
import "./globals.css";

import { RootProviders } from "@/components/providers/root-providers";
import { appName, brand } from "@/lib/brand";
import { NO_FLASH_SCRIPT } from "@/lib/theme/preferences";

export const metadata: Metadata = {
  title: { default: appName, template: `%s · ${appName}` },
  description: brand.description,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // data-scroll-behavior tells Next the smooth scroll in globals.css is intentional.
  return (
    <html lang="en" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head>
        {/*
          Runs before first paint and stamps data-theme / data-density from
          localStorage. It has to be inline and synchronous: anything async
          paints the default theme first, and the flash is exactly what a theme
          preference is supposed to prevent.
        */}
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH_SCRIPT }} />
      </head>
      <body>
        <RootProviders>{children}</RootProviders>
      </body>
    </html>
  );
}
