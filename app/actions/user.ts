'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { doc, setDoc, getDoc, serverTimestamp, type Firestore } from 'firebase/firestore';
import { requireAuth, type AuthUser } from '@/app/lib/auth/server-auth';
import { getOrCreateDefaultProject } from './projects';
import { cookies } from 'next/headers';

type ActionContext = {
  user?: AuthUser;
  db?: Firestore;
};

export type UserFeaturePermissions = {
  canViewUsageInsights: boolean;
  canUseQuellenFinder: boolean;
  canUsePdfScan: boolean;
};

type MeResponse = Partial<UserFeaturePermissions> & {
  blocked?: boolean;
  fullAccess?: boolean;
  legacyApproved?: boolean;
};

async function getContext(ctx?: ActionContext) {
  const user = ctx?.user ?? (await requireAuth());
  const db = ctx?.db ?? (await getFirestoreForUser());
  return { user, db };
}

async function getUserFeaturePermissionsFromApi(): Promise<UserFeaturePermissions | null> {
  const cookieStore = await cookies();
  const token = cookieStore.get('__session')?.value;
  if (!token) return null;

  const apiBaseUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';
  try {
    const res = await fetch(`${apiBaseUrl}/api/me`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    if (!res.ok) return null;

    const data = (await res.json()) as MeResponse;
    return {
      canViewUsageInsights: data.canViewUsageInsights === true,
      canUseQuellenFinder: data.canUseQuellenFinder === true,
      canUsePdfScan: data.canUsePdfScan === true,
    };
  } catch {
    return null;
  }
}

export async function createOrUpdateUser(ctx?: ActionContext) {
  const { user, db } = await getContext(ctx);
  if (!user) {
    return { success: false, error: 'Not authenticated' };
  }

  const userRef = doc(db, 'users', user.uid);
  const userDoc = await getDoc(userRef);

  if (!userDoc.exists()) {
    // Create new user document
    await setDoc(userRef, {
      uid: user.uid,
      email: user.email,
      displayName: user.displayName,
      photoURL: user.photoURL,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });
    console.log('User created in Firestore:', user.uid);

    // Ensure a default project exists for this user
    await getOrCreateDefaultProject({ user, db });
  } else {
    // Update existing user document
    await setDoc(
      userRef,
      {
        email: user.email,
        displayName: user.displayName,
        photoURL: user.photoURL,
        updatedAt: serverTimestamp(),
      },
      { merge: true }
    );
    console.log('User updated in Firestore:', user.uid);
  }

  return { success: true };
}

export async function getUserFeaturePermissions(ctx?: ActionContext): Promise<UserFeaturePermissions> {
  const { user, db } = await getContext(ctx);
  if (!user) {
    throw new Error('Not authenticated');
  }

  const apiPermissions = await getUserFeaturePermissionsFromApi();
  if (apiPermissions) {
    return apiPermissions;
  }

  const snap = await getDoc(doc(db, 'users', user.uid));
  const data = snap.exists() ? (snap.data() as Record<string, unknown>) : {};

  return {
    canViewUsageInsights: data.canViewUsageInsights === true,
    canUseQuellenFinder: data.canUseQuellenFinder === true,
    canUsePdfScan: data.canUsePdfScan === true,
  };
}
