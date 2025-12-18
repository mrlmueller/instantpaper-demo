import { redirect } from 'next/navigation';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { getUserQuellen } from '@/app/actions/quellen';
import { getUserKapitels } from '@/app/actions/kapitels';
import { getOrCreateDefaultProject } from '@/app/actions/projects';
import { QuellenManager } from '@/app/components/quellen/QuellenManager';

export const dynamic = 'force-dynamic';

export default async function QuellenManagerPage() {
  const user = await requireAuth();

  if (!user) {
    redirect('/login?reason=unauthenticated');
  }

  const db = await getFirestoreForUser();
  const projekt = await getOrCreateDefaultProject({ user, db });

  const [quellen, kapitels] = await Promise.all([
    getUserQuellen(projekt.id, { user, db }),
    getUserKapitels(projekt.id, false, 0, { user, db }), // No runs needed
  ]);

  return <QuellenManager initialQuellen={quellen} initialKapitels={kapitels} projektId={projekt.id} />;
}
