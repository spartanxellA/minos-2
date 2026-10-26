import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "minOS 2.0",
  description: "Riesgo reputacional en tiempo real",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
