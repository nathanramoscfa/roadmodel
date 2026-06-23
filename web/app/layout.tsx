// web/app/layout.tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

import { AppNav } from "@/components/AppNav";
import { env } from "@/lib/env";

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
  // Pre-launch posture: belt-and-suspenders with public/robots.txt
  // Disallow. Remove both at real-launch time. See project memory
  // `project_site_pre_launch_gate`.
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // suppressHydrationWarning: the no-flash script below mutates the <html>
    // class before React hydrates (T4 dark mode); without it React would flag
    // (and reconcile) the script's class change as a hydration mismatch.
    <html lang="en" className={`${inter.variable} dark`} suppressHydrationWarning>
      <body className={`${inter.className} min-h-screen font-sans`}>
        {/* No-flash theme init: dark is the default, so the server already
            renders <html class="dark"> (zero flash for the common case). Only
            an explicit "light" choice removes it before paint; "dark" or an
            unset preference stay dark. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{if(localStorage.getItem('theme')==='light')document.documentElement.classList.remove('dark')}catch(e){}",
          }}
        />
        <AppNav roadmapEnabled={env.ROADMAP_ENABLED} />
        <main>{children}</main>
      </body>
    </html>
  );
}
