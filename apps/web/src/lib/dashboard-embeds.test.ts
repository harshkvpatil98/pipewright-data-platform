import { describe, expect, it } from "vitest";

import { embedLink, embedState, frameCode } from "@/features/reporting/components/dashboard-embeds";

/* The Embed panel's words and the code a site pastes (A8, Y4). */
describe("dashboard embeds", () => {
  it("uses the API's link when it knows the web's address, and this site's otherwise", () => {
    expect(embedLink({ url: "https://pw.example.com/embed/a.b.c", token: "a.b.c" }, "http://localhost:3002")).toBe(
      "https://pw.example.com/embed/a.b.c",
    );
    expect(embedLink({ url: null, token: "a.b.c" }, "http://localhost:3002")).toBe("http://localhost:3002/embed/a.b.c");
  });

  it("gives a frame with a title, and escapes the dashboard's name", () => {
    expect(frameCode("https://pw.example.com/embed/t", 'Sales "Q3" <draft> & more')).toBe(
      '<iframe src="https://pw.example.com/embed/t" title="Sales &quot;Q3&quot; &lt;draft> &amp; more" width="100%" height="640" style="border:0" loading="lazy"></iframe>',
    );
  });

  it("says whether it is on, off, or ran out", () => {
    const expires_at = "2026-11-14T10:00:00Z";
    expect(embedState({ state: "on", expires_at, revoked_at: null })).toBe("On until 14 Nov 2026");
    expect(embedState({ state: "off", expires_at, revoked_at: expires_at })).toBe("Turned off");
    expect(embedState({ state: "expired", expires_at, revoked_at: null })).toBe("Ran out on 14 Nov 2026");
  });
});
