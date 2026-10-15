"use client";

import { useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api/client";
import { appConfig } from "@/lib/config";
import { getAccessToken } from "@/lib/auth/session";

/** How often a page says it is still open. Twenty seconds of silence is gone. */
const BEAT_MS = 5000;

export type PresencePerson = {
  user_id: string;
  name: string;
  initials: string;
  /** One of eight colours, the same for a person everywhere. */
  colour: number;
  focus: Record<string, string> | null;
  you: boolean;
  client_id: string;
};

/** Background and text for each presence colour, from the chart palette. */
export const PRESENCE_COLOURS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
  "var(--series-8)",
];

/**
 * Who else has this recipe open in the Studio, and which step each has
 * open (C2). Says so every five seconds while the page is visible, and
 * that it has gone when the page closes.
 */
export function usePresence(options: {
  projectId: string;
  recipeId: string | null;
  clientId: string;
  focus: Record<string, string> | null;
}) {
  const { projectId, recipeId, clientId, focus } = options;
  const [people, setPeople] = useState<PresencePerson[]>([]);
  const focusRef = useRef(focus);
  focusRef.current = focus;

  useEffect(() => {
    if (!recipeId) return;
    let stopped = false;
    const beat = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const answer = await apiFetch<{ people: PresencePerson[] }>(`/projects/${projectId}/presence`, {
          method: "POST",
          body: JSON.stringify({
            target_type: "recipe",
            target_id: recipeId,
            client_id: clientId,
            focus: focusRef.current,
          }),
        });
        if (!stopped) setPeople(answer.people);
      } catch {
        /* presence is a courtesy; the Studio works without it */
      }
    };
    void beat();
    const timer = setInterval(() => void beat(), BEAT_MS);
    const leave = () => {
      const token = getAccessToken();
      // keepalive lets the request outlive the page that sends it.
      void fetch(
        `${appConfig.apiBaseUrl}/projects/${projectId}/presence/${clientId}?target_type=recipe&target_id=${recipeId}`,
        { method: "DELETE", keepalive: true, headers: token ? { Authorization: `Bearer ${token}` } : {} },
      ).catch(() => undefined);
    };
    window.addEventListener("pagehide", leave);
    return () => {
      stopped = true;
      clearInterval(timer);
      window.removeEventListener("pagehide", leave);
      leave();
    };
  }, [projectId, recipeId, clientId]);

  // Say what changed in focus straight away, not at the next beat. The
  // focus the page opened with goes with the first beat.
  const lastFocus = useRef<string>(JSON.stringify(focus));
  useEffect(() => {
    const key = JSON.stringify(focus);
    if (!recipeId || key === lastFocus.current) return;
    lastFocus.current = key;
    void apiFetch<{ people: PresencePerson[] }>(`/projects/${projectId}/presence`, {
      method: "POST",
      body: JSON.stringify({ target_type: "recipe", target_id: recipeId, client_id: clientId, focus }),
    })
      .then((answer) => setPeople(answer.people))
      .catch(() => undefined);
  }, [focus, projectId, recipeId, clientId]);

  return people.filter((person) => person.client_id !== clientId);
}
