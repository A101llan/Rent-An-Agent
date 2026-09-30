import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Header } from "@/components/header";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AgentHub — Rent AI Agents That Get Work Done",
  description:
    "Discover specialized AI agents, hire them for a task or a period of time, and pay only for what they do.",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const headerList = await headers();
  const isEmbed = headerList.get("x-agenthub-embed") === "1";

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body
        className="min-h-full flex flex-col bg-zinc-950 text-zinc-100"
        suppressHydrationWarning
      >
        <Providers>
          {!isEmbed && <Header />}
          <main className={isEmbed ? "h-dvh flex flex-col" : "flex-1"}>{children}</main>
        </Providers>
      </body>
    </html>
  );
}
