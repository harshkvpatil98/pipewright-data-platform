import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * The help's pictures (A9, Z2), served from `docs/user/images/`, which ships
 * with the app like the pages that show them. Only plain PNG names are
 * served, so no path can climb out of the folder.
 */
function imageFolder(): string {
  const candidates = [resolve(process.cwd(), "docs/user/images"), resolve(process.cwd(), "../../docs/user/images")];
  return candidates.find((folder) => existsSync(folder)) ?? candidates[0];
}

export async function GET(_request: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  if (!/^[a-z0-9-]+\.png$/.test(name)) return new Response("Not found", { status: 404 });
  const file = join(imageFolder(), name);
  if (!existsSync(file)) return new Response("Not found", { status: 404 });
  return new Response(readFileSync(file), {
    headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=3600" },
  });
}
