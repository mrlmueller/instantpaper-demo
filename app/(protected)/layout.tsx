import { requireFullAccess } from '@/app/lib/auth/server-auth';

// This layout always runs on the server to read auth cookies.
export const dynamic = 'force-dynamic';

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Check auth - will return null if cookie exists but token expired
  // Client-side will handle token refresh
  await requireFullAccess();

  return (
    <div className="min-h-screen">
      <main className="h-screen">{children}</main>
    </div>
  );
}
