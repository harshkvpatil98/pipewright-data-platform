"use client";

import { useEffect } from "react";

import { renewIfDue } from "@/lib/auth/renewal";

const CHECK_EVERY_MS = 60_000;
const ACTIVE_WITHIN_MS = 5 * 60_000;

/**
 * Renews the session while somebody is using the page, including typing into
 * a long form that makes no requests. Activity is a key press or a click in
 * the last five minutes; an untouched tab is left to run out.
 */
export function useSessionKeepAlive(): void {
  useEffect(() => {
    let lastActive = Date.now();
    const markActive = () => {
      lastActive = Date.now();
    };
    window.addEventListener("keydown", markActive, { passive: true });
    window.addEventListener("pointerdown", markActive, { passive: true });
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && Date.now() - lastActive < ACTIVE_WITHIN_MS) renewIfDue();
    }, CHECK_EVERY_MS);
    return () => {
      window.removeEventListener("keydown", markActive);
      window.removeEventListener("pointerdown", markActive);
      window.clearInterval(timer);
    };
  }, []);
}
