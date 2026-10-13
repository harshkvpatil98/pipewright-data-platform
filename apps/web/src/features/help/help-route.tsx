import { notFound } from "next/navigation";

import type { SupportContact } from "@platform/shared-types";

import { HelpArticle } from "@/features/help/components/help-article";
import { HelpLayout } from "@/features/help/components/help-layout";
import { serverApiFetch } from "@/lib/api/server";
import { getCurrentUser } from "@/lib/auth/server";
import { helpContents, readHelpPage } from "@/lib/help/content";

/** Both help routes: the front page and every other page, by slug. */
export async function HelpRoute({ slug }: { slug: string }) {
  const page = readHelpPage(slug);
  if (!page) notFound();
  const [currentUser, support] = await Promise.all([
    getCurrentUser().catch(() => null),
    serverApiFetch<SupportContact>("/status/support").catch(() => null),
  ]);
  const sections = page.blocks.flatMap((block) =>
    block.kind === "heading" && block.level === 2 ? [{ id: block.id, text: block.text }] : [],
  );
  return (
    <HelpLayout
      currentUser={currentUser}
      slug={slug}
      title={page.title}
      contents={helpContents()}
      sections={sections}
      support={support}
    >
      <HelpArticle blocks={page.blocks} />
    </HelpLayout>
  );
}
