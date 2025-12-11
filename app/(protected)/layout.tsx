import { requireAuth } from '@/app/lib/auth/server-auth';

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await requireAuth();

  return (
    <div className="min-h-screen">
      <main className="h-screen">{children}</main>
    </div>
  );
}
