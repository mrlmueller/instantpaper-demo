'use server';

import { revalidatePath } from 'next/cache';
import {
  setUserAllowPlatformKeyByEmail,
  setUserApprovedByEmail,
  setUserCanDuplicateSystemPromptsByEmail,
} from '@/app/lib/api/adminServer';

function normalizeEmail(value: unknown): string {
  const email = String(value || '').trim();
  return email;
}

export async function adminSetUserApproval(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const approvedRaw = String(formData.get('approved') ?? 'true').trim().toLowerCase();
  const approved = approvedRaw === 'true' || approvedRaw === '1' || approvedRaw === 'yes' || approvedRaw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine gültige E-Mail angeben.');
  }

  await setUserApprovedByEmail(email, approved);
  revalidatePath('/admin');
}

export async function adminSetAllowPlatformKey(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const allowRaw = String(formData.get('allowPlatformKey') ?? 'false').trim().toLowerCase();
  const allow = allowRaw === 'true' || allowRaw === '1' || allowRaw === 'yes' || allowRaw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine gültige E-Mail angeben.');
  }

  await setUserAllowPlatformKeyByEmail(email, allow);
  revalidatePath('/admin');
}

export async function adminSetCanDuplicateSystemPrompts(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const allowRaw = String(formData.get('canDuplicateSystemPrompts') ?? 'false').trim().toLowerCase();
  const allow = allowRaw === 'true' || allowRaw === '1' || allowRaw === 'yes' || allowRaw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine g〕tige E-Mail angeben.');
  }

  await setUserCanDuplicateSystemPromptsByEmail(email, allow);
  revalidatePath('/admin');
}
