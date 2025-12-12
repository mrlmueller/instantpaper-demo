'use server';

import { getFirestoreForUser, getStorageForUser } from '@/app/lib/firebase/serverApp';
import type { AuthUser } from '@/app/lib/auth/server-auth';
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
  type Firestore,
} from 'firebase/firestore';
import { ref, deleteObject } from 'firebase/storage';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { revalidatePath } from 'next/cache';

export type Quelle = {
  id: string;
  title: string;
  content: string;
  projektId: string;
  createdAt: string; // ISO string
  updatedAt?: string; // ISO string
  images?: {
    url: string;
    path: string;
    filename: string;
    size: number;
    contentType: string;
  }[];
};

type ActionContext = {
  user?: AuthUser;
  db?: Firestore;
};

async function getContext(ctx?: ActionContext) {
  const user = ctx?.user ?? (await requireAuth());
  const db = ctx?.db ?? (await getFirestoreForUser());
  return { user, db };
}

export type ImageMetadata = {
  url: string;
  path: string;
  filename: string;
  size: number;
  contentType: string;
};

export async function createQuelle(
  title: string,
  content: string,
  projektId: string,
  imageMetadata?: ImageMetadata[],
  ctx?: ActionContext
) {
  try {
    const { user, db } = await getContext(ctx);

    // Create Firestore document
    const quellenRef = collection(db, 'users', user.uid, 'quellen');
    const docData: any = {
      title,
      content,
      projektId,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    };

    if (imageMetadata && imageMetadata.length > 0) {
      docData.images = imageMetadata;
    }

    const docRef = await addDoc(quellenRef, docData);

    revalidatePath('/dashboard');
    return {
      success: true,
      id: docRef.id,
      imageUrls: imageMetadata?.map((img) => img.url) || [],
    };
  } catch (error: any) {
    console.error('Error creating Quelle:', error);
    return { success: false, error: error.message };
  }
}

export async function updateQuelle(quelleId: string, title: string, content: string, ctx?: ActionContext) {
  try {
    const { user, db } = await getContext(ctx);

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

export async function deleteQuelle(quelleId: string, ctx?: ActionContext) {
  try {
    const { user, db } = await getContext(ctx);

    const quelleRef = doc(db, 'users', user.uid, 'quellen', quelleId);
    const quelleDoc = await getDoc(quelleRef);
    if (!quelleDoc.exists()) {
      throw new Error('Quelle not found');
    }

    // Delete images from Storage
    const quelleData = quelleDoc.data();
    if (quelleData.images && Array.isArray(quelleData.images)) {
      const storage = await getStorageForUser();

      await Promise.all(
        quelleData.images.map(async (img: any) => {
          try {
            await deleteObject(ref(storage, img.path));
            console.log(`Deleted image: ${img.path}`);
          } catch (error: any) {
            if (error.code !== 'storage/object-not-found') {
              console.error(`Failed to delete ${img.path}:`, error);
            }
          }
        })
      );
    }

    // Delete Firestore document
    await deleteDoc(quelleRef);

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error deleting Quelle:', error);
    return { success: false, error: error.message };
  }
}

export async function getQuelle(quelleId: string, ctx?: ActionContext): Promise<Quelle | null> {
  try {
    const { user, db } = await getContext(ctx);

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
      images: data.images || undefined,
    };
  } catch (error: any) {
    console.error('Error getting Quelle:', error);
    return null;
  }
}

export async function getUserQuellen(projektId: string, ctx?: ActionContext): Promise<Quelle[]> {
  try {
    const { user, db } = await getContext(ctx);

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
        images: data.images || undefined,
      });
    });

    return quellen;
  } catch (error: any) {
    console.error('Error getting user Quellen:', error);
    return [];
  }
}
