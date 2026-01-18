import type { ReactNode } from 'react';

import { AdminHeader } from '@/app/admin/ui/AdminHeader';
import { AdminSidebar } from '@/app/admin/ui/AdminSidebar';

export const dynamic = 'force-dynamic';

export default function AdminShellLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <div className="flex min-h-screen">
        <aside className="w-[260px] shrink-0 border-r bg-muted/20">
          <div className="px-4 py-6">
            <AdminHeader />
          </div>
          <div className="px-4 pb-6">
            <AdminSidebar />
          </div>
        </aside>

        <main className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-4xl px-6 py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
