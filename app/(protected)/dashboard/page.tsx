import { requireAuth } from '@/app/lib/auth/server-auth';
import { createOrUpdateUser } from '@/app/actions/user';
import { getUserQuellen } from '@/app/actions/quellen';
import { getUserKapitels } from '@/app/actions/kapitels';
import { DashboardPanels } from '@/app/components/dashboard/DashboardPanels';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const user = await requireAuth();

  await createOrUpdateUser();

  const quellen = await getUserQuellen();
  const kapitels = await getUserKapitels(true, 5);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold">Deine Kapiteln</h1>
          <p className="text-gray-600 mt-1">
            Organisiere Kapiteln und Quellen und verarbeite sie mit denselben Anweisungen.
          </p>
        </div>
      </div>

      <DashboardPanels kapitels={kapitels} quellen={quellen} />
    </div>
  );
}
