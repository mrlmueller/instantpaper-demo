import { requireAuth } from '@/app/lib/auth/server-auth';
import { ActivateAuthWrapper } from './ActivateAuthWrapper';
import { ActivatePage } from './ActivatePage';

export const dynamic = 'force-dynamic';

export default async function ActivateRoute() {
  const user = await requireAuth();

  // Cookie exists but token is expired -> let the client refresh and re-render.
  if (!user) {
    return <ActivateAuthWrapper />;
  }

  return <ActivatePage />;
}

