import type { ReactNode } from 'react';

import { AdminHeader } from '@/app/admin/ui/AdminHeader';
import { AdminMobileNav } from '@/app/admin/ui/AdminMobileNav';
import { AdminSidebar } from '@/app/admin/ui/AdminSidebar';

export const dynamic = 'force-dynamic';

export default function AdminShellLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <div className="flex min-h-screen">
        <aside className="hidden w-[260px] shrink-0 border-r bg-muted/20 md:block">
          <div className="px-4 py-6">
            <AdminHeader />
          </div>
          <div className="px-4 pb-6">
            <AdminSidebar />
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 md:hidden">
            <div className="flex items-center justify-between px-4 py-3">
              <AdminHeader />
              <AdminMobileNav />
            </div>
          </header>

          <main className="min-w-0">
            <div className="mx-auto w-full max-w-4xl px-4 py-4 sm:px-6 sm:py-8">{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}
