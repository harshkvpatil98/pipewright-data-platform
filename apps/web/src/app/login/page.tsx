import { redirect } from "next/navigation";

import { LoginForm } from "@/features/auth/components/login-form";
import { getCurrentUser } from "@/lib/auth/server";

export const metadata = { title: "Sign in" };
// Reads the session cookie; said explicitly because the read is wrapped in a
// catch (the page must render when the API is down), which hides it from Next.
export const dynamic = "force-dynamic";

export default async function LoginPage() {
  // The form must show even when the API cannot be reached; signing in then
  // says why it failed, rather than the page failing before anyone can try.
  const user = await getCurrentUser().catch(() => null);
  if (user !== null) {
    redirect("/projects");
  }

  return <LoginForm />;
}
