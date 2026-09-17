import { redirect } from "next/navigation";
import { serverSession } from "@/lib/server-auth";
import { AuthProvider } from "@/components/auth-provider";
import { Sidebar } from "@/components/sidebar";
export default async function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const manager = await serverSession();
  if (!manager) redirect("/login");
  return (
    <AuthProvider manager={manager}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Sidebar />
      <main id="main" className="main">
        {children}
      </main>
    </AuthProvider>
  );
}
