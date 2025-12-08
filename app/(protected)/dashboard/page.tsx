import { requireAuth } from '@/app/lib/auth/server-auth';
import { createOrUpdateUser } from '@/app/actions/user';
import { getUserQuellen } from '@/app/actions/quellen';
import { getUserKapitels } from '@/app/actions/kapitels';
import { CreateKapitelDialog } from '@/app/components/kapitels/CreateKapitelDialog';
import { KapitelList } from '@/app/components/kapitels/KapitelList';
import { CreateQuelleDialog } from '@/app/components/quellen/CreateQuelleDialog';
import { QuellenList } from '@/app/components/quellen/QuellenList';

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
        <div className="flex gap-3">
          <CreateKapitelDialog quellen={quellen} />
        </div>
      </div>

      <KapitelList kapitels={kapitels} quellen={quellen} />

      <div className="mt-10 border-t pt-8 space-y-4">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-2xl font-semibold">Quellen verwalten</h2>
            <p className="text-sm text-muted-foreground">
              Lege Quellen an und ordne sie Kapiteln zu.
            </p>
          </div>
          <CreateQuelleDialog />
        </div>

        <QuellenList initialQuellen={quellen} />
      </div>
    </div>
  );
}
