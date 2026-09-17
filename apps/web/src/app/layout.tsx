import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: { default: "Technician Hub", template: "%s · Technician Hub" },
  description: "A local operations workspace for your field team.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
