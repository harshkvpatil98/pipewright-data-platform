"use client";

import { useEffect, useState } from "react";

import { absoluteApiBase, appConfig } from "@/lib/config";

/**
 * The API's full address, for showing and copying. A relative address
 * ("/api/v1") gains the site's own origin once the page is in the browser;
 * the server's render and the first browser render agree, so nothing is
 * rendered twice.
 */
export function useApiAddress(): string {
  const [address, setAddress] = useState(appConfig.apiBaseUrl);
  useEffect(() => setAddress(absoluteApiBase()), []);
  return address;
}
