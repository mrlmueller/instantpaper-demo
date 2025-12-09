import { requireAuth } from '@/app/lib/auth/server-auth';
import { createOrUpdateUser } from '@/app/actions/user';
import { getUserQuellen } from '@/app/actions/quellen';
import { getUserKapitels } from '@/app/actions/kapitels';
import { Dashboard } from '@/app/components/dashboard/Dashboard';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const user = await requireAuth();

  await createOrUpdateUser();

  const quellen = await getUserQuellen();
  // Fetch more runs so the run dropdown can show historical entries
  const kapitels = await getUserKapitels(true, 50);

  return <Dashboard initialKapitels={kapitels} initialQuellen={quellen} />;
}
