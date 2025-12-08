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
  where,
  orderBy,
  serverTimestamp,
} from 'firebase/firestore';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { revalidatePath } from 'next/cache';

export type Paper = {
  id: string;
  title: string;
  content: string;
  createdAt: string; // ISO string
  updatedAt?: string; // ISO string
};

export async function createPaper(title: string, content: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    // Papers are now a subcollection under users/{userId}/papers
    const papersRef = collection(db, 'users', user.uid, 'papers');
    const docRef = await addDoc(papersRef, {
      title,
      content,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true, id: docRef.id };
  } catch (error: any) {
    console.error('Error creating paper:', error);
    return { success: false, error: error.message };
  }
}

export async function updatePaper(paperId: string, title: string, content: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const paperRef = doc(db, 'users', user.uid, 'papers', paperId);

    // Check if paper exists
    const paperDoc = await getDoc(paperRef);
    if (!paperDoc.exists()) {
      throw new Error('Paper not found');
    }

    await updateDoc(paperRef, {
      title,
      content,
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error updating paper:', error);
    return { success: false, error: error.message };
  }
}

export async function deletePaper(paperId: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const paperRef = doc(db, 'users', user.uid, 'papers', paperId);

    // Check if paper exists
    const paperDoc = await getDoc(paperRef);
    if (!paperDoc.exists()) {
      throw new Error('Paper not found');
    }

    await deleteDoc(paperRef);

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error deleting paper:', error);
    return { success: false, error: error.message };
  }
}

export async function getPaper(paperId: string): Promise<Paper | null> {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const paperRef = doc(db, 'users', user.uid, 'papers', paperId);
    const paperDoc = await getDoc(paperRef);

    if (!paperDoc.exists()) {
      return null;
    }

    const data = paperDoc.data();

    return {
      id: paperDoc.id,
      title: data.title,
      content: data.content,
      createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
      updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
    };
  } catch (error: any) {
    console.error('Error getting paper:', error);
    return null;
  }
}

export async function getUserPapers(): Promise<Paper[]> {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    // Query the subcollection under the user document
    const papersRef = collection(db, 'users', user.uid, 'papers');
    const q = query(papersRef, orderBy('createdAt', 'desc'));

    const querySnapshot = await getDocs(q);
    const papers: Paper[] = [];

    querySnapshot.forEach((doc) => {
      const data = doc.data();
      papers.push({
        id: doc.id,
        title: data.title,
        content: data.content,
        createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
        updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
      });
    });

    return papers;
  } catch (error: any) {
    console.error('Error getting user papers:', error);
    return [];
  }
}
