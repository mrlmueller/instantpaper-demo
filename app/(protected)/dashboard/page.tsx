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
  const kapitels = await getUserKapitels(true, 5);

  return <Dashboard initialKapitels={kapitels} initialQuellen={quellen} />;
}
