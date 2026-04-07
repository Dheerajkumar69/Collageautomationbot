import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "LMS Auto-Feedback | Adamas University Automation",
  description:
    "Automate your SSN LMS feedback submissions with one click. Enter your credentials and let the bot handle the rest — fully headless, live terminal logs.",
  keywords: ["LMS", "feedback", "automation", "Adamas University", "bot"],
  authors: [{ name: "LMS Auto-Feedback" }],
  robots: "noindex, nofollow",
  openGraph: {
    title: "LMS Auto-Feedback",
    description: "Automate your LMS feedback submissions seamlessly.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#030712",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col relative">
        {/* Grain / noise overlay */}
        <div className="noise-overlay" aria-hidden="true" />
        {children}
      </body>
    </html>
  );
}
