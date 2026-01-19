import { getAuthenticatedAppForUser } from '@/app/lib/firebase/serverApp';
import { redirect } from 'next/navigation';
import { cookies } from 'next/headers';

export type AuthUser = {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL: string | null;
};

export type AuthAccess = {
  fullAccess: boolean;
  legacyApproved: boolean;
  blocked: boolean;
};

function readAuthAccessFromClaims(claims: Record<string, unknown> | null | undefined): AuthAccess {
  const fullAccess = claims?.['fullAccess'] === true;
  const legacyApproved = claims?.['approved'] === true;
  const blocked = claims?.['blocked'] === true;
  return { fullAccess, legacyApproved, blocked };
}

function hasFullAccess(access: AuthAccess | null | undefined): boolean {
  return Boolean(access?.fullAccess || access?.legacyApproved);
}

export async function getAuthSession(): Promise<{ user: AuthUser | null; access: AuthAccess | null }> {
  try {
    const { currentUser } = await getAuthenticatedAppForUser();

    if (!currentUser) return { user: null, access: null };

    const tokenResult = await currentUser.getIdTokenResult();

    return {
      user: {
        uid: currentUser.uid,
        email: currentUser.email,
        displayName: currentUser.displayName,
        photoURL: currentUser.photoURL,
      },
      access: readAuthAccessFromClaims(tokenResult.claims as unknown as Record<string, unknown>),
    };
  } catch (error) {
    console.error('Auth verification error:', error);
    return { user: null, access: null };
  }
}

export async function getAuthUser(): Promise<AuthUser | null> {
  const { user } = await getAuthSession();
  return user;
}

export async function getAuthAccess(): Promise<AuthAccess | null> {
  const { access } = await getAuthSession();
  return access;
}

// Use in Server Components - throws if not authenticated
// If cookie exists but token is expired, returns null to allow client-side refresh
export async function requireAuth(): Promise<AuthUser | null> {
  const cookieStore = await cookies();
  const authCookie = cookieStore.get('__session');

  const { user } = await getAuthSession();
  if (user) return user;

  // If there's a cookie (even if expired), allow page to load
  // Client-side will handle token refresh
  if (authCookie?.value) {
    return null;
  }

  // No cookie at all - redirect to login
  redirect('/login?reason=unauthenticated');
}

// Like requireAuth(), but enforces `fullAccess` (or legacy `approved`) and respects `blocked`.
export async function requireFullAccess(): Promise<AuthUser | null> {
  const cookieStore = await cookies();
  const authCookie = cookieStore.get('__session');

  const { user, access } = await getAuthSession();
  if (user) {
    if (access?.blocked) {
      redirect('/profil');
    }
    if (!hasFullAccess(access)) {
      redirect('/activate');
    }
    return user;
  }

  // If there's a cookie (even if expired), allow page to load. Client-side will handle refresh.
  if (authCookie?.value) {
    return null;
  }

  redirect('/login?reason=unauthenticated');
}
