import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

const sourceSans = localFont({
  src: "../public/fonts/source-sans-3.ttf",
  variable: "--font-source-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ReStock — Restaurant inventory & purchasing",
  description:
    "Keep track of kitchen stock, review purchase recommendations, and manage incoming deliveries.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-scroll-behavior="smooth" className={`${sourceSans.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
