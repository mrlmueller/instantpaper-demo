import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { createOrUpdateUser } from '@/app/actions/user';
import { getUserQuellen } from '@/app/actions/quellen';
import { getUserKapitels } from '@/app/actions/kapitels';
import { getOrCreateDefaultProject, getProjects } from '@/app/actions/projects';
import { Dashboard } from '@/app/components/dashboard/Dashboard';
import { DashboardAuthWrapper } from './DashboardAuthWrapper';
import { cookies } from 'next/headers';
import { getActiveKapitelCookieName } from '@/app/lib/ui/kapitelSelection';
import { getActiveProjektCookieName } from '@/app/lib/ui/projektSelection';
import { STORAGE_KEYS } from '@/app/lib/storage/preferences';

export const dynamic = 'force-dynamic';

const INITIAL_RUN_LIMIT = 10;

export default async function DashboardPage() {
  const user = await requireAuth();
  const cookieStore = await cookies();
  const initialShowQuellenPanel = cookieStore.get(STORAGE_KEYS.QUELLEN_PANEL_OPEN)?.value === 'true';

  // If user is null, cookie exists but token is expired
  // Show loading skeleton while client-side refreshes token
  if (!user) {
    return <DashboardAuthWrapper initialShowQuellenPanel={initialShowQuellenPanel} />;
  }

  const db = await getFirestoreForUser();

  // Do not block render on user upsert
  createOrUpdateUser({ user, db }).catch((error) => {
    console.error('Background user sync failed:', error);
  });

  const defaultProjekt = await getOrCreateDefaultProject({ user, db });
  const projekte = await getProjects({ user, db }, { includeArchived: true });

  // Ensure the default project is available even if it was created after fetching the list
  const projekteWithDefault = projekte.some((p) => p.id === defaultProjekt.id) ? projekte : [defaultProjekt, ...projekte];

  const persistedProjektId = cookieStore.get(getActiveProjektCookieName())?.value;
  const activeProjekte = projekteWithDefault.filter((p) => p.archived !== true);
  const selectedProjekt =
    (persistedProjektId ? activeProjekte.find((p) => p.id === persistedProjektId) : undefined) ??
    activeProjekte[0] ??
    defaultProjekt;

  const [quellen, kapitels] = await Promise.all([
    getUserQuellen(selectedProjekt.id, { user, db }),
    // Only fetch Kapitel metadata; runs are fetched lazily per Kapitel
    getUserKapitels(selectedProjekt.id, false, INITIAL_RUN_LIMIT, { user, db }),
  ]);

  const persistedKapitelId = cookieStore.get(getActiveKapitelCookieName(selectedProjekt.id))?.value;
  const initialActiveKapitelId =
    persistedKapitelId && kapitels.some((k) => k.id === persistedKapitelId) ? persistedKapitelId : undefined;

  // Runs are loaded lazily via client-side listeners for faster initial paint
  return (
    <Dashboard
      initialKapitels={kapitels}
      initialQuellen={quellen}
      initialProjekt={selectedProjekt}
      initialProjekte={projekteWithDefault}
      initialRuns={[]}
      initialActiveKapitelId={initialActiveKapitelId}
      initialShowQuellenPanel={initialShowQuellenPanel}
    />
  );
}
