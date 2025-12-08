import { requireAuth } from '@/app/lib/auth/server-auth';
import { createOrUpdateUser } from '@/app/actions/user';
import { getUserPapers } from '@/app/actions/papers';
import { CreatePaperDialog } from '@/app/components/papers/CreatePaperDialog';
import { PapersList } from '@/app/components/papers/PapersList';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const user = await requireAuth();

  // Create or update user in Firestore
  await createOrUpdateUser();

  // Get user's papers
  const papers = await getUserPapers();

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold">Your Papers</h1>
          <p className="text-gray-600 mt-1">
            Manage and organize your long-form content
          </p>
        </div>
        <CreatePaperDialog />
      </div>

      <PapersList initialPapers={papers} />
    </div>
  );
}
