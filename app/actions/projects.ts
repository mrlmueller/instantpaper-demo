'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth } from '@/app/lib/auth/server-auth';
import {
  collection,
  doc,
  getDoc,
  getDocs,
  setDoc,
  deleteDoc,
  serverTimestamp,
  query,
  orderBy,
} from 'firebase/firestore';

export type Project = {
  id: string;
  name: string;
  createdAt: string;
  updatedAt?: string;
};

const DEFAULT_PROJECT_ID = 'default';
const DEFAULT_PROJECT_NAME = 'Standardprojekt';

export async function getOrCreateDefaultProject(): Promise<Project> {
  const user = await requireAuth();
  const db = await getFirestoreForUser();

  const projectRef = doc(db, 'users', user.uid, 'projects', DEFAULT_PROJECT_ID);
  const projectSnap = await getDoc(projectRef);

  if (!projectSnap.exists()) {
    await setDoc(projectRef, {
      name: DEFAULT_PROJECT_NAME,
      ownerId: user.uid,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });
    return {
      id: DEFAULT_PROJECT_ID,
      name: DEFAULT_PROJECT_NAME,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
  }

  const data = projectSnap.data();
  return {
    id: projectSnap.id,
    name: data.name || DEFAULT_PROJECT_NAME,
    createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
    updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
  };
}

export async function getProjects(): Promise<Project[]> {
  const user = await requireAuth();
  const db = await getFirestoreForUser();

  const projectsRef = collection(db, 'users', user.uid, 'projects');
  const snapshot = await getDocs(query(projectsRef, orderBy('createdAt', 'desc')));

  return snapshot.docs.map((docSnap) => {
    const data = docSnap.data();
    return {
      id: docSnap.id,
      name: data.name,
      createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
      updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
    };
  });
}

export async function createProject(name: string): Promise<{ success: boolean; id?: string; error?: string }> {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const projectsRef = collection(db, 'users', user.uid, 'projects');
    const newRef = doc(projectsRef); // random id
    await setDoc(newRef, {
      name,
      ownerId: user.uid,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });

    return { success: true, id: newRef.id };
  } catch (error: any) {
    console.error('Error creating project:', error);
    return { success: false, error: error.message };
  }
}

export async function renameProject(projectId: string, name: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const projectRef = doc(db, 'users', user.uid, 'projects', projectId);
    const snap = await getDoc(projectRef);
    if (!snap.exists()) {
      return { success: false, error: 'Projekt nicht gefunden' };
    }

    await setDoc(
      projectRef,
      {
        name,
        updatedAt: serverTimestamp(),
      },
      { merge: true }
    );

    return { success: true };
  } catch (error: any) {
    console.error('Error renaming project:', error);
    return { success: false, error: error.message };
  }
}

export async function deleteProject(projectId: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const projectRef = doc(db, 'users', user.uid, 'projects', projectId);
    await deleteDoc(projectRef);

    return { success: true };
  } catch (error: any) {
    console.error('Error deleting project:', error);
    return { success: false, error: error.message };
  }
}

export async function getDefaultProjectInfo(): Promise<Project> {
  return {
    id: DEFAULT_PROJECT_ID,
    name: DEFAULT_PROJECT_NAME,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}
