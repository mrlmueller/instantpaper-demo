'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { doc, setDoc, getDoc, serverTimestamp, type Firestore } from 'firebase/firestore';
import { requireAuth, type AuthUser } from '@/app/lib/auth/server-auth';
import { getOrCreateDefaultProject } from './projects';

type ActionContext = {
  user?: AuthUser;
  db?: Firestore;
};

async function getContext(ctx?: ActionContext) {
  const user = ctx?.user ?? (await requireAuth());
  const db = ctx?.db ?? (await getFirestoreForUser());
  return { user, db };
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
