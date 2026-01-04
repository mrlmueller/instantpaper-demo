'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import type { AuthUser } from '@/app/lib/auth/server-auth';
import {
  collection,
  addDoc,
  updateDoc,
  doc,
  getDoc,
  getDocs,
  setDoc,
  query,
  orderBy,
  where,
  serverTimestamp,
  deleteField,
  type Firestore,
} from 'firebase/firestore';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { revalidatePath } from 'next/cache';
import { quelleContentDoc, quelleDoc, quellenCol } from '@/app/lib/firestore/refs';

export type Quelle = {
  id: string;
  title: string;
  projektId: string;
  createdAt: string; // ISO string
  updatedAt?: string; // ISO string
  archived?: boolean;
  archivedAt?: string; // ISO string
  wordCount?: number;
  images?: {
    url: string;
    path: string;
    filename: string;
    size: number;
    contentType: string;
  }[];
  // Advanced metadata fields
  autor?: string;
  jahr?: number;
  typ?: 'Book' | 'Article' | 'Website' | 'Thesis' | 'Report';
  url?: string;
  zugriffAm?: string; // ISO date string
  zitat?: string;
  zitatModus?: 'auto' | 'authorYear' | 'full' | 'none';
  color?: 'blue' | 'green' | 'teal' | 'lavender' | 'cream' | 'peach' | 'rose';
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

function countWords(text: string) {
  return (text || '').trim().split(/\s+/).filter(Boolean).length;
}

const MAX_WORDS = 7000;
const MAX_CHARS = 140000;

export async function createQuelle(
  title: string,
  content: string,
  projektId: string,
  imageMetadata?: ImageMetadata[],
  advancedFields?: {
    autor?: string;
    jahr?: number;
    typ?: 'Book' | 'Article' | 'Website' | 'Thesis' | 'Report';
    url?: string;
    zugriffAm?: string;
    zitat?: string;
    zitatModus?: 'auto' | 'authorYear' | 'full' | 'none';
    color?: 'blue' | 'green' | 'teal' | 'lavender' | 'cream' | 'peach' | 'rose';
  },
  ctx?: ActionContext
) {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }

    const wordCount = countWords(content);
    if (wordCount > MAX_WORDS) {
      return { success: false, error: `Text zu lang (${wordCount} Wörter). Maximal ${MAX_WORDS} Wörter.` };
    }
    if (content.length > MAX_CHARS) {
      return { success: false, error: `Text zu lang (${content.length} Zeichen). Bitte kürzen.` };
    }

    // Create Firestore document
    const quellenRef = quellenCol(db, user.uid);
    const docData: Record<string, unknown> = {
      title,
      projektId,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
      archived: false,
      wordCount,
    };

    if (imageMetadata && imageMetadata.length > 0) {
      docData.images = imageMetadata;
    }

    // Add advanced fields if provided
    if (advancedFields) {
      if (advancedFields.autor) docData.autor = advancedFields.autor;
      if (advancedFields.jahr) docData.jahr = advancedFields.jahr;
      if (advancedFields.typ) docData.typ = advancedFields.typ;
      if (advancedFields.url) docData.url = advancedFields.url;
      if (advancedFields.zugriffAm) docData.zugriffAm = advancedFields.zugriffAm;
      if (advancedFields.zitat) docData.zitat = advancedFields.zitat;
      if (advancedFields.zitatModus) docData.zitatModus = advancedFields.zitatModus;
      if (advancedFields.color) docData.color = advancedFields.color;
    }

    const docRef = await addDoc(quellenRef, docData);

    await setDoc(quelleContentDoc(db, user.uid, docRef.id), {
      text: content,
      wordCount,
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return {
      success: true,
      id: docRef.id,
      imageUrls: imageMetadata?.map((img) => img.url) || [],
    };
  } catch (error: unknown) {
    console.error('Error creating Quelle:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function updateQuelle(quelleId: string, title: string, content: string, ctx?: ActionContext) {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }

    const quelleRef = quelleDoc(db, user.uid, quelleId);
    const quelleSnap = await getDoc(quelleRef);
    if (!quelleSnap.exists()) {
      throw new Error('Quelle not found');
    }

    const wordCount = countWords(content);
    if (wordCount > MAX_WORDS) {
      return { success: false, error: `Text zu lang (${wordCount} Wörter). Maximal ${MAX_WORDS} Wörter.` };
    }
    if (content.length > MAX_CHARS) {
      return { success: false, error: `Text zu lang (${content.length} Zeichen). Bitte kürzen.` };
    }

    await updateDoc(quelleRef, {
      title,
      wordCount,
      updatedAt: serverTimestamp(),
    });

    const contentRef = quelleContentDoc(db, user.uid, quelleId);
    const contentSnap = await getDoc(contentRef);
    if (contentSnap.exists()) {
      await updateDoc(contentRef, {
        text: content,
        wordCount,
        updatedAt: serverTimestamp(),
      });
    } else {
      await setDoc(contentRef, {
        text: content,
        wordCount,
        createdAt: serverTimestamp(),
        updatedAt: serverTimestamp(),
      });
    }

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error updating Quelle:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

type QuelleAdvancedFieldsUpdate = {
  autor?: string | null;
  jahr?: number | null;
  typ?: 'Book' | 'Article' | 'Website' | 'Thesis' | 'Report' | null;
  url?: string | null;
  zugriffAm?: string | null;
  zitat?: string | null;
  zitatModus?: 'auto' | 'authorYear' | 'full' | 'none' | null;
  color?: 'blue' | 'green' | 'teal' | 'lavender' | 'cream' | 'peach' | 'rose' | null;
};

function hasOwn(obj: Record<string, unknown>, key: string) {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function normalizeStringUpdate(value: unknown): string | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length === 0 ? null : trimmed;
}

function normalizeNumberUpdate(value: unknown): number | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  if (typeof value !== 'number' || Number.isNaN(value)) return undefined;
  return value;
}

export async function updateQuelleFull(
  quelleId: string,
  data: {
    title: string;
    content: string;
    images?: ImageMetadata[];
    advancedFields?: QuelleAdvancedFieldsUpdate;
  },
  ctx?: ActionContext
) {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }

    const quelleRef = quelleDoc(db, user.uid, quelleId);
    const quelleSnap = await getDoc(quelleRef);
    if (!quelleSnap.exists()) {
      throw new Error('Quelle not found');
    }

    const wordCount = countWords(data.content);
    if (wordCount > MAX_WORDS) {
      return {
        success: false,
        error: `Text zu lang (${wordCount} W”rter). Maximal ${MAX_WORDS} W”rter.`,
      };
    }
    if (data.content.length > MAX_CHARS) {
      return {
        success: false,
        error: `Text zu lang (${data.content.length} Zeichen). Bitte krzen.`,
      };
    }

    const updateData: Record<string, unknown> = {
      title: data.title,
      wordCount,
      updatedAt: serverTimestamp(),
    };

    if (data.images) {
      if (data.images.length > 0) {
        updateData.images = data.images;
      } else {
        updateData.images = deleteField();
      }
    }

    if (data.advancedFields) {
      const af = data.advancedFields as unknown as Record<string, unknown>;

      if (hasOwn(af, 'autor')) {
        const autor = normalizeStringUpdate(af.autor);
        updateData.autor = autor === null ? deleteField() : autor;
      }

      if (hasOwn(af, 'jahr')) {
        const jahr = normalizeNumberUpdate(af.jahr);
        updateData.jahr = jahr === null ? deleteField() : jahr;
      }

      if (hasOwn(af, 'typ')) {
        const typ = af.typ;
        if (typ === null || typ === undefined || typ === '') {
          updateData.typ = deleteField();
        } else {
          updateData.typ = typ;
        }
      }

      if (hasOwn(af, 'url')) {
        const url = normalizeStringUpdate(af.url);
        updateData.url = url === null ? deleteField() : url;
      }

      if (hasOwn(af, 'zugriffAm')) {
        const zugriffAm = normalizeStringUpdate(af.zugriffAm);
        updateData.zugriffAm = zugriffAm === null ? deleteField() : zugriffAm;
      }

      if (hasOwn(af, 'zitat')) {
        const zitat = normalizeStringUpdate(af.zitat);
        updateData.zitat = zitat === null ? deleteField() : zitat;
      }

      if (hasOwn(af, 'zitatModus')) {
        const zitatModus = af.zitatModus;
        if (zitatModus === null || zitatModus === undefined || zitatModus === '') {
          updateData.zitatModus = deleteField();
        } else {
          updateData.zitatModus = zitatModus;
        }
      }

      if (hasOwn(af, 'color')) {
        const color = af.color as unknown;
        if (color === null || color === undefined || color === '') {
          updateData.color = deleteField();
        } else {
          updateData.color = color;
        }
      }
    }

    await updateDoc(quelleRef, updateData);

    const contentRef = quelleContentDoc(db, user.uid, quelleId);
    const contentSnap = await getDoc(contentRef);
    if (contentSnap.exists()) {
      await updateDoc(contentRef, {
        text: data.content,
        wordCount,
        updatedAt: serverTimestamp(),
      });
    } else {
      await setDoc(contentRef, {
        text: data.content,
        wordCount,
        createdAt: serverTimestamp(),
        updatedAt: serverTimestamp(),
      });
    }

    revalidatePath('/dashboard');
    revalidatePath('/quellen-manager');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error updating Quelle (full):', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function deleteQuelle(quelleId: string, ctx?: ActionContext) {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }

    const quelleRef = quelleDoc(db, user.uid, quelleId);
    const snap = await getDoc(quelleRef);
    if (!snap.exists()) {
      throw new Error('Quelle not found');
    }

    // V2: archive instead of hard delete (rules deny deletes)
    await updateDoc(quelleRef, {
      archived: true,
      archivedAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error deleting Quelle:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function getQuelle(quelleId: string, ctx?: ActionContext): Promise<Quelle | null> {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return null;
    }

    const quelleRef = quelleDoc(db, user.uid, quelleId);
    const quelleSnap = await getDoc(quelleRef);

    if (!quelleSnap.exists()) {
      return null;
    }

    const data = quelleSnap.data();

    return {
      id: quelleSnap.id,
      title: data.title,
      projektId: data.projektId || 'default',
      createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
      updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
      images: data.images || undefined,
      archived: Boolean(data.archived),
      archivedAt: data.archivedAt?.toDate?.()?.toISOString(),
      wordCount: typeof data.wordCount === 'number' ? data.wordCount : undefined,
      autor: data.autor,
      jahr: data.jahr,
      typ: data.typ,
      url: data.url,
      zugriffAm: data.zugriffAm,
      zitat: data.zitat,
      zitatModus: data.zitatModus,
      color: data.color,
    };
  } catch (error: unknown) {
    console.error('Error getting Quelle:', error);
    return null;
  }
}

export async function getQuelleContent(
  quelleId: string,
  ctx?: ActionContext
): Promise<{ text: string; wordCount: number } | null> {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) return null;

    const ref = quelleContentDoc(db, user.uid, quelleId);
    const snap = await getDoc(ref);
    if (!snap.exists()) return null;
    const data = snap.data();
    return { text: data.text || '', wordCount: Number(data.wordCount ?? 0) };
  } catch (error: unknown) {
    console.error('Error getting Quelle content:', error);
    return null;
  }
}

export async function setQuelleContent(quelleId: string, text: string, ctx?: ActionContext) {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }

    const wordCount = countWords(text);
    if (wordCount > MAX_WORDS) {
      return { success: false, error: `Text zu lang (${wordCount} Wörter). Maximal ${MAX_WORDS} Wörter.` };
    }
    if (text.length > MAX_CHARS) {
      return { success: false, error: `Text zu lang (${text.length} Zeichen). Bitte kürzen.` };
    }

    const metaRef = quelleDoc(db, user.uid, quelleId);
    const metaSnap = await getDoc(metaRef);
    if (!metaSnap.exists()) {
      return { success: false, error: 'Quelle not found' };
    }

    const contentRef = quelleContentDoc(db, user.uid, quelleId);
    const contentSnap = await getDoc(contentRef);

    if (contentSnap.exists()) {
      await updateDoc(contentRef, { text, wordCount, updatedAt: serverTimestamp() });
    } else {
      await setDoc(contentRef, { text, wordCount, createdAt: serverTimestamp(), updatedAt: serverTimestamp() });
    }

    await updateDoc(metaRef, { wordCount, updatedAt: serverTimestamp() });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error setting Quelle content:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function getUserQuellen(projektId: string, ctx?: ActionContext): Promise<Quelle[]> {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return [];
    }

    const quellenRef = quellenCol(db, user.uid);
    const q = query(
      quellenRef,
      where('projektId', '==', projektId),
      where('archived', '==', false),
      orderBy('createdAt', 'desc')
    );

    const querySnapshot = await getDocs(q);
    const quellen: Quelle[] = [];

    querySnapshot.forEach((d) => {
      const data = d.data();

      quellen.push({
        id: d.id,
        title: data.title,
        projektId: data.projektId || 'default',
        createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
        updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
        archived: Boolean(data.archived),
        archivedAt: data.archivedAt?.toDate?.()?.toISOString(),
        wordCount: typeof data.wordCount === 'number' ? data.wordCount : undefined,
        images: data.images || undefined,
        // Advanced metadata fields
        autor: data.autor,
        jahr: data.jahr,
        typ: data.typ,
        url: data.url,
        zugriffAm: data.zugriffAm,
        zitat: data.zitat,
        zitatModus: data.zitatModus,
        color: data.color,
      });
    });

    return quellen;
  } catch (error: unknown) {
    console.error('Error getting user Quellen:', error);
    return [];
  }
}

// Update Quelle color
export async function updateQuelleColor(
  quelleId: string,
  color: 'blue' | 'green' | 'teal' | 'lavender' | 'cream' | 'peach' | 'rose' | null,
  ctx?: ActionContext
) {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }

    const quelleRef = quelleDoc(db, user.uid, quelleId);
    const quelleSnap = await getDoc(quelleRef);
    if (!quelleSnap.exists()) {
      throw new Error('Quelle not found');
    }

    const updateData: Record<string, unknown> = {
      updatedAt: serverTimestamp(),
    };

    if (color === null) {
      // Remove color field
      updateData.color = deleteField();
    } else {
      updateData.color = color;
    }

    await updateDoc(quelleRef, updateData);

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error updating Quelle color:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

// Bulk assign Quellen to multiple Kapitels
export async function bulkAssignQuellen(
  quelleIds: string[],
  kapitelIds: string[],
  projektId: string,
  ctx?: ActionContext,
  replaceExisting: boolean = false
) {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return { success: false, error: 'Not authenticated' };
    }

    if (replaceExisting) {
      const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
      const q = query(kapitelsRef, where('projektId', '==', projektId));
      const snap = await getDocs(q);

      const selectedKapitelIdSet = new Set(kapitelIds);
      const quelleIdSet = new Set(quelleIds);

      const updates: Promise<unknown>[] = [];

      snap.forEach((kapitelDoc) => {
        const data = kapitelDoc.data() as { quelleIds?: string[] };
        const existingQuelleIds: string[] = data.quelleIds || [];

        const withoutTargetQuellen = existingQuelleIds.filter((id) => !quelleIdSet.has(id));
        const updatedQuelleIds = selectedKapitelIdSet.has(kapitelDoc.id)
          ? Array.from(new Set([...withoutTargetQuellen, ...quelleIds]))
          : withoutTargetQuellen;

        const unchanged =
          updatedQuelleIds.length === existingQuelleIds.length &&
          updatedQuelleIds.every((id, i) => id === existingQuelleIds[i]);
        if (unchanged) return;

        updates.push(
          updateDoc(doc(db, 'users', user.uid, 'kapitels', kapitelDoc.id), {
            quelleIds: updatedQuelleIds,
            updatedAt: serverTimestamp(),
          })
        );
      });

      await Promise.all(updates);

      revalidatePath('/dashboard');
      revalidatePath('/quellen-manager');
      return { success: true };
    }

    if (kapitelIds.length === 0) {
      return { success: true };
    }

    // Additive mode: update selected Kapitels with union of existing + new Quellen
    const kapitelRefs = kapitelIds.map((id) => doc(db, 'users', user.uid, 'kapitels', id));
    const kapitelDocs = await Promise.all(kapitelRefs.map(getDoc));

    const updates = kapitelDocs.map((kapitelDoc, i) => {
      if (!kapitelDoc.exists()) {
        throw new Error(`Kapitel ${kapitelIds[i]} not found`);
      }

      const data = kapitelDoc.data() as { projektId?: string; quelleIds?: string[] };
      if (data.projektId && data.projektId !== projektId) {
        throw new Error(`Kapitel ${kapitelIds[i]} does not belong to projekt ${projektId}`);
      }

      const existingQuelleIds: string[] = data.quelleIds || [];
      const updatedQuelleIds = Array.from(new Set([...existingQuelleIds, ...quelleIds]));

      return updateDoc(kapitelRefs[i], {
        quelleIds: updatedQuelleIds,
        updatedAt: serverTimestamp(),
      });
    });

    await Promise.all(updates);

    revalidatePath('/dashboard');
    revalidatePath('/quellen-manager');
    return { success: true };
  } catch (error: unknown) {
    console.error('Error bulk assigning Quellen:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

// Get Kapitels that include a specific Quelle
export async function getKapitelsForQuelle(
  quelleId: string,
  projektId: string,
  ctx?: ActionContext
): Promise<{ id: string; title: string }[]> {
  try {
    const { user, db } = await getContext(ctx);
    if (!user) {
      return [];
    }

    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const q = query(
      kapitelsRef,
      where('projektId', '==', projektId),
      where('quelleIds', 'array-contains', quelleId)
    );

    const querySnapshot = await getDocs(q);
    const kapitels: { id: string; title: string }[] = [];

    querySnapshot.forEach((d) => {
      const data = d.data();
      kapitels.push({
        id: d.id,
        title: data.title,
      });
    });

    return kapitels;
  } catch (error: unknown) {
    console.error('Error getting Kapitels for Quelle:', error);
    return [];
  }
}
