import { requireAuth } from '@/app/lib/auth/server-auth';
import { createOrUpdateUser } from '@/app/actions/user';
import { getUserQuellen } from '@/app/actions/quellen';
import { getUserKapitels } from '@/app/actions/kapitels';
import { getOrCreateDefaultProject, getProjects } from '@/app/actions/projects';
import { Dashboard } from '@/app/components/dashboard/Dashboard';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const user = await requireAuth();

  await createOrUpdateUser();

  const projekt = await getOrCreateDefaultProject();
  const projekte = await getProjects();
  const quellen = await getUserQuellen(projekt.id);
  // Fetch more runs so the run dropdown can show historical entries
  const kapitels = await getUserKapitels(projekt.id, true, 50);

  return (
    <Dashboard
      initialKapitels={kapitels}
      initialQuellen={quellen}
      initialProjekt={projekt}
      initialProjekte={projekte.length ? projekte : [projekt]}
    />
  );
}
