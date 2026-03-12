import { notFound, redirect } from 'next/navigation';
import { cookies } from 'next/headers';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { getUserKapitels } from '@/app/actions/kapitels';
import { getOrCreateDefaultProject, getProjects } from '@/app/actions/projects';
import { getUserFeaturePermissions } from '@/app/actions/user';
import { getActiveProjektCookieName } from '@/app/lib/ui/projektSelection';
import { QuellenFinder } from '@/app/components/quellen-finder/QuellenFinder';

export const dynamic = 'force-dynamic';

export default async function QuellenFinderPage() {
  const user = await requireAuth();

  if (!user) {
    redirect('/login?reason=unauthenticated');
  }

  const db = await getFirestoreForUser();
  const permissions = await getUserFeaturePermissions({ user, db });
  if (!permissions.canUseQuellenFinder) {
    notFound();
  }
  const cookieStore = await cookies();

  const defaultProjekt = await getOrCreateDefaultProject({ user, db });
  const projekte = await getProjects({ user, db }, { includeArchived: true });
  const projekteWithDefault = projekte.some((p) => p.id === defaultProjekt.id) ? projekte : [defaultProjekt, ...projekte];

  const persistedProjektId = cookieStore.get(getActiveProjektCookieName())?.value;
  const activeProjekte = projekteWithDefault.filter((p) => p.archived !== true);
  const selectedProjekt =
    (persistedProjektId ? activeProjekte.find((p) => p.id === persistedProjektId) : undefined) ??
    activeProjekte[0] ??
    defaultProjekt;

  const kapitels = await getUserKapitels(selectedProjekt.id, false, 0, { user, db }); // no runs needed

  return <QuellenFinder initialKapitels={kapitels} projektId={selectedProjekt.id} projektName={selectedProjekt.name} />;
}
