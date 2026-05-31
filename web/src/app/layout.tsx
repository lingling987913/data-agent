import type { Metadata } from 'next'
import Link from 'next/link'
import AppToaster from './AppToaster'
import { APP_TERMS, COMPREHENSIVE_REVIEW_TERMS, SUPER_AGENT_TERMS } from '@/lib/aeroTerminology'
import './globals.css'

export const metadata: Metadata = {
  title: APP_TERMS.pageTitle,
  description: APP_TERMS.pageDescription,
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" data-theme="tech-blue" suppressHydrationWarning>
      <body
        className="min-h-screen bg-background text-primary antialiased"
        suppressHydrationWarning
      >
        <header className="border-b border-border/20 bg-background-secondary/80 px-4 py-3 backdrop-blur-sm">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-3">
            <Link href="/" className="flex min-w-0 items-center gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand to-primaryAccent text-[10px] font-semibold text-white">
                {APP_TERMS.brandAbbr}
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-primary">{APP_TERMS.brandName}</p>
                <p className="truncate text-[11px] text-muted">{APP_TERMS.tagline}</p>
              </div>
            </Link>
            <nav className="flex shrink-0 items-center gap-1 text-[11px] font-medium text-muted">
              <Link href="/super-agent" className="rounded-lg px-3 py-1.5 hover:bg-surface hover:text-primary">
                {SUPER_AGENT_TERMS.nav}
              </Link>
              <Link href="/comprehensive-review" className="rounded-lg px-3 py-1.5 hover:bg-surface hover:text-primary">
                {COMPREHENSIVE_REVIEW_TERMS.nav}
              </Link>
            </nav>
          </div>
        </header>
        <main className="min-h-[calc(100vh-57px)]">{children}</main>
        <AppToaster />
      </body>
    </html>
  )
}
