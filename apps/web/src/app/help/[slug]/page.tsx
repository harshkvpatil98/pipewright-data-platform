import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { HelpRoute } from "@/features/help/help-route";
import { readHelpPage } from "@/lib/help/content";

type HelpPageProps = { params: Promise<{ slug: string }> };

// Reads the session cookie behind a catch; see the help front page.
export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: HelpPageProps): Promise<Metadata> {
  const { slug } = await params;
  const page = readHelpPage(slug);
  return { title: page ? `${page.title} · Help` : "Help" };
}

export default async function HelpSlugPage({ params }: HelpPageProps) {
  const { slug } = await params;
  if (slug === "index") redirect("/help");
  return <HelpRoute slug={slug} />;
}
