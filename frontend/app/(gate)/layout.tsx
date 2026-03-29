import { getAuthAccess, requireAuth } from '@/app/lib/auth/server-auth';
import { redirect } from 'next/navigation';

export const dynamic = 'force-dynamic';

export default async function GateLayout({ children }: { children: React.ReactNode }) {
  // Login required (but no `fullAccess` enforcement here).
  const user = await requireAuth();

  // If we can already verify the token and the user has access, skip the gate.
  if (user) {
    const access = await getAuthAccess();
    const hasAccess = Boolean(access?.fullAccess || access?.legacyApproved);
    if (access?.blocked) {
      redirect('/profil');
    }
    if (hasAccess && !access?.blocked) {
      redirect('/dashboard');
    }
  }

  return <>{children}</>;
}

