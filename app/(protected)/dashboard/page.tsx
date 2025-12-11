import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { createOrUpdateUser } from '@/app/actions/user';
import { getUserQuellen } from '@/app/actions/quellen';
import { getKapitelRuns, getUserKapitels } from '@/app/actions/kapitels';
import { getOrCreateDefaultProject, getProjects } from '@/app/actions/projects';
import { Dashboard } from '@/app/components/dashboard/Dashboard';

export const dynamic = 'force-dynamic';

const INITIAL_RUN_LIMIT = 10;

export default async function DashboardPage() {
  const user = await requireAuth();
  const db = await getFirestoreForUser();

  // Do not block render on user upsert
  createOrUpdateUser({ user, db }).catch((error) => {
    console.error('Background user sync failed:', error);
  });

  const projekt = await getOrCreateDefaultProject({ user, db });

  const [projekte, quellen, kapitels] = await Promise.all([
    getProjects({ user, db }),
    getUserQuellen(projekt.id, { user, db }),
    // Only fetch Kapitel metadata; runs are fetched lazily per Kapitel
    getUserKapitels(projekt.id, false, INITIAL_RUN_LIMIT, { user, db }),
  ]);

  // Ensure the default project is available even if it was created after fetching the list
  const projekteWithDefault = projekte.some((p) => p.id === projekt.id) ? projekte : [projekt, ...projekte];

  // Preload runs only for the initially active Kapitel to keep first paint responsive
  const initialKapitelId = kapitels[0]?.id;
  const initialRuns =
    initialKapitelId !== undefined
      ? await getKapitelRuns(initialKapitelId, INITIAL_RUN_LIMIT, { user, db })
      : [];

  return (
    <Dashboard
      initialKapitels={kapitels}
      initialQuellen={quellen}
      initialProjekt={projekt}
      initialProjekte={projekteWithDefault}
      initialRuns={initialRuns}
    />
  );
}
