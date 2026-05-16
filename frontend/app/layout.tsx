import type { Metadata, Viewport } from "next"
import { Geist, Geist_Mono, Noto_Sans_JP } from "next/font/google"
import { Analytics } from "@vercel/analytics/next"
import "./globals.css"
import { ToastProvider } from "@/components/aibo/toast-provider"

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
})
const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
})
const notoJP = Noto_Sans_JP({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-noto-jp",
})

export const metadata: Metadata = {
  title: "AIBO Cyber Studio v8.0",
  description:
    "Cyberpunk-themed AI portrait, fashion, and scene generation studio — Bloomberg Terminal × Blade Runner 2049.",
  generator: "v0.app",
}

export const viewport: Viewport = {
  themeColor: "#0a0a0c",
  width: "device-width",
  initialScale: 1,
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="ja"
      className={`${geist.variable} ${geistMono.variable} ${notoJP.variable} bg-background dark`}
    >
      <body className="font-sans antialiased bg-background text-foreground min-h-screen">
        <ToastProvider>{children}</ToastProvider>
        {process.env.NODE_ENV === "production" && <Analytics />}
      </body>
    </html>
  )
}
