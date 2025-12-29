'use server';

import { revalidatePath } from 'next/cache';
import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth } from '@/app/lib/auth/server-auth';
import type {
  ActivePromptSelections,
  PromptStage,
  PromptTemplate,
  PromptTemplatePayload,
  SystemPromptPermissions,
  SystemPromptTemplateMeta,
} from '@/app/types/prompts';
import { STAGE_CONFIG, MAX_TEMPLATES_PER_STAGE, MAX_NAME_LENGTH, MIN_NAME_LENGTH } from '@/app/lib/prompts/promptConfig';
import { cookies } from 'next/headers';
import {
  collection,
  query,
  where,
  getDocs,
  addDoc,
  updateDoc,
  deleteDoc,
  doc,
  serverTimestamp,
  getDoc,
  setDoc,
} from 'firebase/firestore';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

function validatePlaceholders(stage: PromptStage, instructions: string): string | null {
  const config = STAGE_CONFIG[stage];
  const missing = (config.requiredPlaceholders || []).filter((ph) => !instructions.includes(ph));
  if (missing.length > 0) {
    return `<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`;
  }
  return null;
}

const SYSTEM_STAGES: PromptStage[] = ['process_quelle', 'combine', 'shorten', 'lesefluss', 'summary'];

function fallbackSystemTemplates(): SystemPromptTemplateMeta[] {
  return SYSTEM_STAGES.flatMap((stage) => [
    { stage, templateKey: 'default', name: 'System-Standard', createdAt: null, updatedAt: null },
    { stage, templateKey: 'default_v2', name: 'System-Standard (v2)', createdAt: null, updatedAt: null },
  ]);
}

async function loadSystemTemplates(): Promise<{
  systemTemplates: SystemPromptTemplateMeta[];
  systemPermissions: SystemPromptPermissions;
}> {
  const store = await cookies();
  const token = store.get('__session')?.value;
  if (!token) {
    return { systemTemplates: fallbackSystemTemplates(), systemPermissions: { canDuplicateSystemPrompts: false } };
  }

  try {
    const res = await fetch(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { systemTemplates: fallbackSystemTemplates(), systemPermissions: { canDuplicateSystemPrompts: false } };
    }

    const raw = Array.isArray((data as any)?.templates) ? ((data as any).templates as any[]) : [];
    const templates: SystemPromptTemplateMeta[] = raw
      .map((t) => {
        const stage = t?.stage;
        const templateKey = t?.templateKey;
        const name = t?.name;
        if (!SYSTEM_STAGES.includes(stage)) return null;
        if (typeof templateKey !== 'string' || !templateKey.trim()) return null;
        return {
          stage,
          templateKey: templateKey.trim(),
          name: typeof name === 'string' && name.trim() ? name.trim() : templateKey.trim(),
          createdAt: typeof t?.createdAt === 'string' ? t.createdAt : null,
          updatedAt: typeof t?.updatedAt === 'string' ? t.updatedAt : null,
        } satisfies SystemPromptTemplateMeta;
      })
      .filter(Boolean) as SystemPromptTemplateMeta[];

    // Ensure defaults exist even if the backend is not seeded yet.
    const byKey = new Set(templates.map((t) => `${t.stage}__${t.templateKey}`));
    for (const stage of SYSTEM_STAGES) {
      if (!byKey.has(`${stage}__default`)) {
        templates.push({ stage, templateKey: 'default', name: 'System-Standard', createdAt: null, updatedAt: null });
      }
      if (!byKey.has(`${stage}__default_v2`)) {
        templates.push({
          stage,
          templateKey: 'default_v2',
          name: 'System-Standard (v2)',
          createdAt: null,
          updatedAt: null,
        });
      }
    }

    const perms = (data as any)?.permissions;
    const canDuplicate = perms?.canDuplicateSystemPrompts === true;

    return {
      systemTemplates: templates,
      systemPermissions: { canDuplicateSystemPrompts: canDuplicate },
    };
  } catch {
    return { systemTemplates: fallbackSystemTemplates(), systemPermissions: { canDuplicateSystemPrompts: false } };
  }
}

async function ensureLimits(stage: PromptStage, userId: string, db: any) {
  const templatesRef = collection(db, 'users', userId, 'promptTemplates');
  const existing = await getDocs(query(templatesRef, where('stage', '==', stage)));
  if (existing.size >= MAX_TEMPLATES_PER_STAGE) {
    throw new Error(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`);
  }
}

export async function listPromptTemplates(): Promise<{
  templates: PromptTemplate[];
  active: ActivePromptSelections;
  askOnEachProcess: boolean;
  systemTemplates: SystemPromptTemplateMeta[];
  systemPermissions: SystemPromptPermissions;
}> {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();

  const templatesRef = collection(db, 'users', user.uid, 'promptTemplates');
  const snapshot = await getDocs(templatesRef);
  const templates: PromptTemplate[] = snapshot.docs.map((d) => {
    const data = d.data() as any;
    return {
      id: d.id,
      stage: data.stage,
      name: data.name,
      instructions: data.instructions,
      placeholders: data.placeholders || [],
      createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
      updatedAt: data.updatedAt?.toDate?.()?.toISOString() || new Date().toISOString(),
    };
  });

  const settingsDoc = await getDoc(doc(db, 'users', user.uid, 'promptSettings', 'active'));
  const active = (settingsDoc.exists() ? settingsDoc.data() : {}) as any;

  const { systemTemplates, systemPermissions } = await loadSystemTemplates();
  return {
    templates,
    active: (active.activeTemplates || {}) as ActivePromptSelections,
    askOnEachProcess: Boolean(active.askOnEachProcess),
    systemTemplates,
    systemPermissions,
  };
}

export async function createPromptTemplate(payload: PromptTemplatePayload) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();

  if (payload.name.length < MIN_NAME_LENGTH || payload.name.length > MAX_NAME_LENGTH) {
    throw new Error(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`);
  }

  const validationError = validatePlaceholders(payload.stage, payload.instructions);
  if (validationError) throw new Error(validationError);

  await ensureLimits(payload.stage, user.uid, db);

  const templatesRef = collection(db, 'users', user.uid, 'promptTemplates');
  const docRef = await addDoc(templatesRef, {
    stage: payload.stage,
    name: payload.name,
    instructions: payload.instructions,
    placeholders: STAGE_CONFIG[payload.stage].requiredPlaceholders,
    createdAt: serverTimestamp(),
    updatedAt: serverTimestamp(),
  });

  revalidatePath('/profil');
  return { id: docRef.id };
}

export async function updatePromptTemplate(id: string, payload: Omit<PromptTemplatePayload, 'stage'>) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();

  if (payload.name.length < MIN_NAME_LENGTH || payload.name.length > MAX_NAME_LENGTH) {
    throw new Error(`<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>`);
  }

  // Fetch to ensure stage not changed
  const ref = doc(db, 'users', user.uid, 'promptTemplates', id);
  const snapshot = await getDoc(ref);
  if (!snapshot.exists()) throw new Error('Template nicht gefunden.');
  const stage = (snapshot.data() as any).stage as PromptStage;

  const validationError = validatePlaceholders(stage, payload.instructions);
  if (validationError) throw new Error(validationError);

  await updateDoc(ref, {
    name: payload.name,
    instructions: payload.instructions,
    updatedAt: serverTimestamp(),
  });

  revalidatePath('/profil');
}

export async function deletePromptTemplate(id: string) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();

  const ref = doc(db, 'users', user.uid, 'promptTemplates', id);
  const snapshot = await getDoc(ref);
  if (!snapshot.exists()) return;
  const stage = (snapshot.data() as any).stage as PromptStage;

  // Remove if active
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  const settingsSnap = await getDoc(settingsRef);
  if (settingsSnap.exists()) {
    const active = settingsSnap.data()?.activeTemplates || {};
    if (active[stage] === id) {
      await setDoc(
        settingsRef,
        {
          activeTemplates: { ...active, [stage]: 'default' },
          updatedAt: serverTimestamp(),
        },
        { merge: true }
      );
    }
  }

  await deleteDoc(ref);
  revalidatePath('/profil');
}

export async function setActivePrompt(stage: PromptStage, templateId: string | 'default') {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  const existing = await getDoc(settingsRef);
  const current = existing.exists() ? existing.data()?.activeTemplates || {} : {};
  await setDoc(
    settingsRef,
    {
      activeTemplates: { ...current, [stage]: templateId },
      updatedAt: serverTimestamp(),
    },
    { merge: true }
  );

  revalidatePath('/profil');
}

export async function setAskOnEachProcess(value: boolean) {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  await setDoc(
    settingsRef,
    {
      askOnEachProcess: value,
      updatedAt: serverTimestamp(),
    },
    { merge: true }
  );
  revalidatePath('/profil');
}

export async function getActivePromptInstructions(stage: PromptStage): Promise<string> {
  const user = await requireAuth();
  if (!user) {
    throw new Error('Not authenticated');
  }
  const db = await getFirestoreForUser();
  const settingsRef = doc(db, 'users', user.uid, 'promptSettings', 'active');
  const settingsSnap = await getDoc(settingsRef);
  const active = settingsSnap.exists() ? settingsSnap.data()?.activeTemplates || {} : {};
  const activeId = active[stage];

  if (activeId && activeId !== 'default') {
    const ref = doc(db, 'users', user.uid, 'promptTemplates', activeId);
    const tpl = await getDoc(ref);
    if (tpl.exists()) {
      return (tpl.data() as any).instructions as string;
    }
  }

  return STAGE_CONFIG[stage].defaultInstructions;
}
