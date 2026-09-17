import type { Metadata } from "next";
import { Sidebar } from "@/components/sidebar";
import "./globals.css";
export const metadata: Metadata = {
  title: { default: "Technician Hub", template: "%s ? Technician Hub" },
  description: "A local operations workspace for your field team.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <Sidebar />
        <main id="main" className="main">
          {children}
        </main>
      </body>
    </html>
  );
}
