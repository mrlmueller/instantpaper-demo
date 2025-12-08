import { getAuthenticatedAppForUser } from '@/app/lib/firebase/serverApp';

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
export async function requireAuth(): Promise<AuthUser> {
  const user = await getAuthUser();
  if (!user) {
    throw new Error('Unauthorized');
  }
  return user;
}
