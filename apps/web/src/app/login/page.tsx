import { redirect } from "next/navigation";
import { LoginForm } from "@/components/login-form";
import { serverSession } from "@/lib/server-auth";
export default async function LoginPage() {
  if (await serverSession()) redirect("/");
  return <LoginForm />;
}
