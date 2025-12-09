'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import {
  collection,
  addDoc,
  updateDoc,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  query,
  orderBy,
  where,
  serverTimestamp,
} from 'firebase/firestore';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { revalidatePath } from 'next/cache';

export type Quelle = {
  id: string;
  title: string;
  content: string;
  projektId: string;
  createdAt: string; // ISO string
  updatedAt?: string; // ISO string
};

export async function createQuelle(title: string, content: string, projektId: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const quellenRef = collection(db, 'users', user.uid, 'quellen');
    const docRef = await addDoc(quellenRef, {
      title,
      content,
      projektId,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true, id: docRef.id };
  } catch (error: any) {
    console.error('Error creating Quelle:', error);
    return { success: false, error: error.message };
  }
}

export async function updateQuelle(quelleId: string, title: string, content: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const quelleRef = doc(db, 'users', user.uid, 'quellen', quelleId);
    const quelleDoc = await getDoc(quelleRef);
    if (!quelleDoc.exists()) {
      throw new Error('Quelle not found');
    }

    await updateDoc(quelleRef, {
      title,
      content,
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error updating Quelle:', error);
    return { success: false, error: error.message };
  }
}

export async function deleteQuelle(quelleId: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const quelleRef = doc(db, 'users', user.uid, 'quellen', quelleId);
    const quelleDoc = await getDoc(quelleRef);
    if (!quelleDoc.exists()) {
      throw new Error('Quelle not found');
    }

    await deleteDoc(quelleRef);

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error deleting Quelle:', error);
    return { success: false, error: error.message };
  }
}

export async function getQuelle(quelleId: string): Promise<Quelle | null> {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const quelleRef = doc(db, 'users', user.uid, 'quellen', quelleId);
    const quelleDoc = await getDoc(quelleRef);

    if (!quelleDoc.exists()) {
      return null;
    }

    const data = quelleDoc.data();

    return {
      id: quelleDoc.id,
      title: data.title,
      content: data.content,
      projektId: data.projektId || 'default',
      createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
      updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
    };
  } catch (error: any) {
    console.error('Error getting Quelle:', error);
    return null;
  }
}

export async function getUserQuellen(projektId: string): Promise<Quelle[]> {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const quellenRef = collection(db, 'users', user.uid, 'quellen');
    const q = query(quellenRef, where('projektId', '==', projektId), orderBy('createdAt', 'desc'));

    const querySnapshot = await getDocs(q);
    const quellen: Quelle[] = [];

    querySnapshot.forEach((d) => {
      const data = d.data();
      quellen.push({
        id: d.id,
        title: data.title,
        content: data.content,
        projektId: data.projektId || 'default',
        createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
        updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
      });
    });

    return quellen;
  } catch (error: any) {
    console.error('Error getting user Quellen:', error);
    return [];
  }
}
