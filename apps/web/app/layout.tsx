import type { Metadata } from "next";
import { Space_Grotesk, Inter, JetBrains_Mono } from "next/font/google";
import TopNav from "../components/TopNav";
import { AuthProvider } from "../lib/auth";
import "./globals.css";

const display = Space_Grotesk({ subsets: ["latin"], variable: "--font-display", weight: ["500", "600", "700"] });
const body = Inter({ subsets: ["latin"], variable: "--font-body", weight: ["400", "500", "600"] });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "Business X-Ray — Operating Graph",
  description: "Upload business data, compile an executable operating graph, simulate change, and explain impact.",
};

export default function Root({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className="grain min-h-[100dvh] bg-paper-50 font-sans text-stone-900">
        <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded focus:bg-pine-700 focus:px-3 focus:py-2 focus:text-white">
          Skip to content
        </a>
        <AuthProvider>
          <TopNav />
          <div id="content">{children}</div>
        </AuthProvider>
      </body>
    </html>
  );
}
