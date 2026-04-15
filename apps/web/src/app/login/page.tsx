import { redirect } from "next/navigation";

import { LoginForm } from "@/features/auth/components/login-form";
import { getCurrentUser } from "@/lib/auth/server";

export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user !== null) {
    redirect("/projects");
  }

  return <LoginForm />;
}
