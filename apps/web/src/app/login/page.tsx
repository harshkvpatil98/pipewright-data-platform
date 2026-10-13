import { redirect } from "next/navigation";

import { LoginForm } from "@/features/auth/components/login-form";
import { getCurrentUser } from "@/lib/auth/server";

export const metadata = { title: "Sign in" };

export default async function LoginPage() {
  // The form must show even when the API cannot be reached; signing in then
  // says why it failed, rather than the page failing before anyone can try.
  const user = await getCurrentUser().catch(() => null);
  if (user !== null) {
    redirect("/projects");
  }

  return <LoginForm />;
}
