// web/app/layout.tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "roadmodel — pick the right model for the job",
  description:
    "Recommend which AI model, platform, and settings to use for your task.",
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://staging.roadmodel.ai",
  ),
  openGraph: {
    images: ["/og-image.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={inter.variable}>
      <body className={`${inter.className} min-h-screen font-sans`}>
        <main>{children}</main>
      </body>
    </html>
  );
}
