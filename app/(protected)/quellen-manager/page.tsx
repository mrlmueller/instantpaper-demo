import { redirect } from 'next/navigation';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { getUserQuellen } from '@/app/actions/quellen';
import { getUserKapitels } from '@/app/actions/kapitels';
import { getOrCreateDefaultProject, getProjects } from '@/app/actions/projects';
import { QuellenManager } from '@/app/components/quellen/QuellenManager';
import { cookies } from 'next/headers';
import { getActiveProjektCookieName } from '@/app/lib/ui/projektSelection';

export const dynamic = 'force-dynamic';

export default async function QuellenManagerPage() {
  const user = await requireAuth();

  if (!user) {
    redirect('/login?reason=unauthenticated');
  }

  const db = await getFirestoreForUser();
  const cookieStore = await cookies();

  const defaultProjekt = await getOrCreateDefaultProject({ user, db });
  const projekte = await getProjects({ user, db });
  const projekteWithDefault = projekte.some((p) => p.id === defaultProjekt.id) ? projekte : [defaultProjekt, ...projekte];
  const persistedProjektId = cookieStore.get(getActiveProjektCookieName())?.value;
  const selectedProjekt =
    (persistedProjektId ? projekteWithDefault.find((p) => p.id === persistedProjektId) : undefined) ?? defaultProjekt;

  const [quellen, kapitels] = await Promise.all([
    getUserQuellen(selectedProjekt.id, { user, db }),
    getUserKapitels(selectedProjekt.id, false, 0, { user, db }), // No runs needed
  ]);

  return <QuellenManager initialQuellen={quellen} initialKapitels={kapitels} projektId={selectedProjekt.id} />;
}
