#!/usr/bin/env node
/**
 * `npm audit`, failing on high or critical advisories unless one is listed
 * below with the reason it cannot be fixed yet.
 *
 * Plain `npm audit --audit-level=high` has no way to say "this one has no
 * patched release": an advisory whose every version is affected keeps the
 * gate red forever, and a gate that is always red stops being read. Each
 * entry here names the advisory, why it is accepted, and when to look again.
 * An entry whose advisory no longer appears is reported, so the list does not
 * outlive its reason.
 */
import { execFileSync } from "node:child_process";

const ACCEPTED = {
  "GHSA-vfj7-8cjw-p6xm": {
    reason:
      "braces <=3.0.3 (stack exhaustion on deeply nested glob patterns). 3.0.3 is the latest release, so " +
      "there is no fix to take. It is reached only through eslint-config-next's lint plugin at development " +
      "time, matching glob patterns this repository writes; nothing shipped to users runs it.",
    review: "When braces publishes a release above 3.0.3, or eslint-config-next stops depending on fast-glob 3.",
  },
};

let report;
try {
  report = execFileSync("npm", ["audit", "--json"], { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
} catch (error) {
  // npm audit exits non-zero when it finds anything; the JSON is still on stdout.
  report = error.stdout;
}
const { vulnerabilities = {} } = JSON.parse(report);

const blocking = [];
const accepted = new Set();
for (const [name, entry] of Object.entries(vulnerabilities)) {
  if (!["high", "critical"].includes(entry.severity)) continue;
  // Advisories are listed on the package that has them; the rest point at it.
  const advisories = entry.via.filter((via) => typeof via === "object");
  if (advisories.length === 0) continue;
  for (const advisory of advisories) {
    const id = String(advisory.url ?? "").split("/").pop();
    if (ACCEPTED[id]) accepted.add(id);
    else blocking.push(`${name} (${entry.severity}): ${advisory.title} ${advisory.url}`);
  }
}

for (const id of accepted) console.log(`accepted ${id}: ${ACCEPTED[id].reason}`);
for (const id of Object.keys(ACCEPTED).filter((id) => !accepted.has(id))) {
  console.log(`note: ${id} is no longer reported; remove it from scripts/audit-npm.mjs.`);
}
if (blocking.length) {
  console.error(`\n${blocking.length} high or critical advisories:\n${blocking.join("\n")}`);
  process.exit(1);
}
console.log("No high or critical advisories outside the accepted list.");
