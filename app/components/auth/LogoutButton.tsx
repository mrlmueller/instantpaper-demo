'use client';

import { signOut } from '@/app/lib/firebase/auth';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import Cookies from 'js-cookie';

export function LogoutButton() {
  const router = useRouter();

  const handleLogout = async () => {
    try {
      const sessionCookie = Cookies.get('__session');

      // Revoke session on backend if cookie exists
      if (sessionCookie) {
        try {
          const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
          await fetch(`${apiUrl}/api/auth/revoke`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sessionCookie })
          });
        } catch (error) {
          console.error('Failed to revoke session:', error);
          // Continue with logout anyway
        }
      }

      // Sign out on client (will remove cookie via onAuthStateChange)
      await signOut();

      // Reload to sync server and client after auth state change
      window.location.href = '/login';
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  return (
    <Button onClick={handleLogout} variant="outline">
      Sign out
    </Button>
  );
}
