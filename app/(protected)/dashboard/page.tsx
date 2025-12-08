import { requireAuth } from '@/app/lib/auth/server-auth';
import { createOrUpdateUser } from '@/app/actions/user';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const user = await requireAuth();

  // Create or update user in Firestore
  await createOrUpdateUser();

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="text-3xl font-bold mb-4">
        Welcome, {user.displayName || 'User'}!
      </h1>
      <p className="text-gray-600">
        You are successfully logged in. Your dashboard content will go here.
      </p>
      <div className="mt-8 p-4 bg-gray-50 rounded-lg">
        <h2 className="text-lg font-semibold mb-2">Your Profile</h2>
        <p className="text-sm text-gray-600">Email: {user.email}</p>
        <p className="text-sm text-gray-600">UID: {user.uid}</p>
      </div>
    </div>
  );
}
