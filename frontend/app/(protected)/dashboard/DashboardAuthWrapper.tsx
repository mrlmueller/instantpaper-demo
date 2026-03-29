'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/app/components/providers/AuthProvider';
import { DashboardSkeleton } from '@/app/components/dashboard/DashboardSkeleton';
import { hasFullAccess } from '@/app/lib/firebase/auth';

type DashboardAuthWrapperProps = {
  initialShowQuellenPanel?: boolean;
};

export function DashboardAuthWrapper({ initialShowQuellenPanel = false }: DashboardAuthWrapperProps) {
  const { user, access, effectiveBlocked, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;

    if (user) {
      if (effectiveBlocked) {
        router.replace('/profil');
        return;
      }

      if (!hasFullAccess(access)) {
        router.replace('/activate');
        return;
      }

      // Auth succeeded - refresh the page to fetch data with valid token + claims
      router.refresh();
    } else {
      // Auth failed - no valid refresh token, redirect to login
      router.replace('/login?reason=session-expired');
    }
  }, [user, access, effectiveBlocked, loading, router]);

  // Show loading skeleton while waiting for auth to complete
  return <DashboardSkeleton showQuellenPanel={initialShowQuellenPanel} />;
}
