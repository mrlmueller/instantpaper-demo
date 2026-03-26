"use client";

import { signOut } from '@/app/lib/firebase/auth';
import { Button } from '@/components/ui/button';

export function LogoutButton() {
  const handleLogout = async () => {
    try {
      try {
        await fetch('/api/auth/revoke', { method: 'POST' });
      } catch (error) {
        console.error('Failed to revoke session:', error);
        // Continue with logout anyway
      }

      // Sign out on client (will remove cookie via onAuthStateChange)
      await signOut();

      // Reload to sync server and client after auth state change
      window.location.href = "/login";
    } catch (error) {
      console.error("Logout failed:", error);
    }
  };

  return (
    <Button onClick={handleLogout} variant="outline">
      Sign out
    </Button>
  );
}
