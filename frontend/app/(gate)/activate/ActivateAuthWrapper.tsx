'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

import { hasFullAccess } from '@/app/lib/firebase/auth';
import { useAuth } from '@/app/components/providers/AuthProvider';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function ActivateAuthWrapper() {
  const { user, access, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;

    if (!user) {
      router.replace('/login?reason=session-expired');
      return;
    }

    // If access was granted while the token was stale, refreshing the route will pick it up.
    if (hasFullAccess(access) && !access.blocked) {
      router.replace('/dashboard');
      return;
    }

    router.refresh();
  }, [user, access, loading, router]);

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <Card className="w-full max-w-md border-border shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">Zugriff wird geprüft…</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

