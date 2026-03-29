import { getAuthAccess, requireAuth } from '@/app/lib/auth/server-auth';
import { redirect } from 'next/navigation';

export const dynamic = 'force-dynamic';

export default async function AccountLayout({ children }: { children: React.ReactNode }) {
  // Login required (but no `fullAccess` enforcement here).
  const user = await requireAuth();

  // Profile should be reachable for blocked users (to manage Stripe), but not for normal users without access.
  if (user) {
    const access = await getAuthAccess();
    const hasAccess = Boolean(access?.fullAccess || access?.legacyApproved);
    if (!access?.blocked && !hasAccess) {
      redirect('/activate');
    }
  }

  return (
    <div className="min-h-screen">
      <main className="h-screen">{children}</main>
    </div>
  );
}
