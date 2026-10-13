import { HelpRoute } from "@/features/help/help-route";

export const metadata = { title: "Help" };

export default function HelpPage() {
  return <HelpRoute slug="index" />;
}
