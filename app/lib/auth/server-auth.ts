import { getAuthenticatedAppForUser } from '@/app/lib/firebase/serverApp';
import { redirect } from 'next/navigation';
import { cookies } from 'next/headers';

export type AuthUser = {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL: string | null;
};

export async function getAuthUser(): Promise<AuthUser | null> {
  try {
    const { currentUser } = await getAuthenticatedAppForUser();

    if (!currentUser) return null;

    return {
      uid: currentUser.uid,
      email: currentUser.email,
      displayName: currentUser.displayName,
      photoURL: currentUser.photoURL,
    };
  } catch (error) {
    console.error('Auth verification error:', error);
    return null;
  }
}

// Use in Server Components - throws if not authenticated
// If cookie exists but token is expired, returns null to allow client-side refresh
export async function requireAuth(): Promise<AuthUser | null> {
  const cookieStore = await cookies();
  const authCookie = cookieStore.get('__session');

  const user = await getAuthUser();
  if (user) return user;

  // If there's a cookie (even if expired), allow page to load
  // Client-side will handle token refresh
  if (authCookie?.value) {
    return null;
  }

  // No cookie at all - redirect to login
  redirect('/login?reason=unauthenticated');
}
