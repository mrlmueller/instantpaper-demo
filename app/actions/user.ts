'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { doc, setDoc, getDoc, serverTimestamp } from 'firebase/firestore';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { getOrCreateDefaultProject } from './projects';

export async function createOrUpdateUser() {
  const user = await requireAuth();
  const db = await getFirestoreForUser();

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
    await getOrCreateDefaultProject();
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
