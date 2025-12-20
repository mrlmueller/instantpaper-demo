'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth, type AuthUser } from '@/app/lib/auth/server-auth';
import {
  collection,
  doc,
  getDoc,
  getDocs,
  setDoc,
  updateDoc,
  serverTimestamp,
  query,
  orderBy,
  where,
  type Firestore,
} from 'firebase/firestore';
import { projectsCol, projectDoc } from '@/app/lib/firestore/refs';

export type Project = {
  id: string;
  name: string;
  createdAt: string;
  updatedAt?: string;
  archived?: boolean;
};

const DEFAULT_PROJECT_ID = 'default';
const DEFAULT_PROJECT_NAME = 'Standardprojekt';

type ActionContext = {
  user?: AuthUser;
  db?: Firestore;
};

async function getContext(ctx?: ActionContext) {
  const user = ctx?.user ?? (await requireAuth());
  const db = ctx?.db ?? (await getFirestoreForUser());
  return { user, db };
}

export async function getOrCreateDefaultProject(ctx?: ActionContext): Promise<Project> {
  const { user, db } = await getContext(ctx);
  if (!user) {
    throw new Error('Not authenticated');
  }

  const projectRef = projectDoc(db, user.uid, DEFAULT_PROJECT_ID);
  const projectSnap = await getDoc(projectRef);

  if (!projectSnap.exists()) {
    await setDoc(projectRef, {
      name: DEFAULT_PROJECT_NAME,
      ownerId: user.uid,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
      archived: false,
    });
    return {
      id: DEFAULT_PROJECT_ID,
      name: DEFAULT_PROJECT_NAME,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      archived: false,
    };
  }

  const data = projectSnap.data();
  return {
    id: projectSnap.id,
    name: data.name || DEFAULT_PROJECT_NAME,
    createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
    updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
    archived: Boolean(data.archived),
  };
}

export async function getProjects(ctx?: ActionContext): Promise<Project[]> {
  const { user, db } = await getContext(ctx);
  if (!user) {
    throw new Error('Not authenticated');
  }

  const projectsRef = projectsCol(db, user.uid);
  const snapshot = await getDocs(query(projectsRef, where('archived', '==', false), orderBy('createdAt', 'desc')));

  return snapshot.docs.map((docSnap) => {
    const data = docSnap.data();
    return {
      id: docSnap.id,
      name: data.name,
      createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
      updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
      archived: Boolean(data.archived),
    };
  });
}

export async function createProject(name: string): Promise<{ success: boolean; id?: string; error?: string }> {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    const projectsRef = projectsCol(db, user.uid);
    const newRef = doc(projectsRef); // random id
    await setDoc(newRef, {
      name,
      ownerId: user.uid,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
      archived: false,
    });

    return { success: true, id: newRef.id };
  } catch (error: unknown) {
    console.error('Error creating project:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function renameProject(projectId: string, name: string) {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    const projectRef = projectDoc(db, user.uid, projectId);
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
  } catch (error: unknown) {
    console.error('Error renaming project:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function deleteProject(projectId: string) {
  try {
    const user = await requireAuth();
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }
    const db = await getFirestoreForUser();

    const projectRef = projectDoc(db, user.uid, projectId);
    const snap = await getDoc(projectRef);
    if (!snap.exists()) {
      return { success: false, error: 'Projekt nicht gefunden' };
    }

    await updateDoc(projectRef, {
      archived: true,
      archivedAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });

    return { success: true };
  } catch (error: unknown) {
    console.error('Error deleting project:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function getDefaultProjectInfo(): Promise<Project> {
  return {
    id: DEFAULT_PROJECT_ID,
    name: DEFAULT_PROJECT_NAME,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    archived: false,
  };
}
