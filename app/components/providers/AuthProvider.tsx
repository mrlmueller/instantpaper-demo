'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { hasFullAccess, onAuthStateChange, type AccessState } from '@/app/lib/firebase/auth';
import type { User, AuthContextType } from '@/app/types/auth';

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [access, setAccess] = useState<AccessState>({ fullAccess: false, legacyApproved: false, blocked: false });
  const [serverBlocked, setServerBlocked] = useState(false);
  const [canViewUsageInsights, setCanViewUsageInsights] = useState(false);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();
  const effectiveBlocked = access.blocked || serverBlocked;

  useEffect(() => {
    const unsubscribe = onAuthStateChange((firebaseUser, nextAccess) => {
      if (firebaseUser) {
        setUser({
          uid: firebaseUser.uid,
          email: firebaseUser.email,
          displayName: firebaseUser.displayName,
          photoURL: firebaseUser.photoURL,
          emailVerified: firebaseUser.emailVerified,
        });
        if (nextAccess) setAccess(nextAccess);
      } else {
        setUser(null);
        setAccess({ fullAccess: false, legacyApproved: false, blocked: false });
        setServerBlocked(false);
        setCanViewUsageInsights(false);
      }
      setLoading(false);
    });

    return () => unsubscribe();
  }, []);

  useEffect(() => {
    if (loading) return;

    // Best-effort server-side status probe to catch immediate blocks (Firestore-backed).
    if (user) {
      let cancelled = false;
      fetch('/api/me', { method: 'GET', cache: 'no-store' })
        .then(async (res) => ({ ok: res.ok, data: (await res.json().catch(() => ({}))) as Record<string, unknown> }))
        .then(({ ok, data }) => {
          if (cancelled || !ok) return;
          const blocked = data.blocked === true || String(data.accountStatus || '').toLowerCase() === 'blocked';
          setServerBlocked(blocked);
          setCanViewUsageInsights(data.canViewUsageInsights === true);
        })
        .catch(() => {
          // ignore
        });
      return () => {
        cancelled = true;
      };
    }
  }, [loading, user, pathname]);

  useEffect(() => {
    if (loading) return;
    const hasAccess = hasFullAccess(access) && !effectiveBlocked;

    // Redirect authenticated users away from login page
    if (user && pathname === '/login') {
      router.replace(effectiveBlocked ? '/profil' : hasAccess ? '/dashboard' : '/activate');
      return;
    }

    // Blocked users should always land on /profil (but still be able to manage Stripe).
    if (user && effectiveBlocked) {
      const isAllowed = pathname === '/profil' || pathname === '/login' || pathname.startsWith('/admin');
      if (!isAllowed) {
        router.replace('/profil');
      }
      return;
    }

    // Users with access should never be on the activation gate.
    if (user && pathname === '/activate' && hasAccess) {
      router.replace('/dashboard');
      return;
    }

    // Global gate for protected routes (whitelist: /login, /activate, /admin and public pages).
    const isWhitelisted = pathname === '/login' || pathname === '/activate' || pathname.startsWith('/admin');
    if (user && !hasAccess && !isWhitelisted) {
      router.replace('/activate');
    }

    // Note: We don't redirect unauthenticated users here anymore
    // Protected pages handle their own auth checks via requireAuth() and show loading skeletons
  }, [loading, user, access, serverBlocked, pathname, router]);

  return (
    <AuthContext.Provider value={{ user, access, effectiveBlocked, canViewUsageInsights, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
