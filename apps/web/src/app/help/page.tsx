import { HelpRoute } from "@/features/help/help-route";

export const metadata = { title: "Help" };
// Reads the session cookie; said explicitly because the read is wrapped in a
// catch (the page must render when the API is down), which hides it from Next.
export const dynamic = "force-dynamic";

export default function HelpPage() {
  return <HelpRoute slug="index" />;
}
