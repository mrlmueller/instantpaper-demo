'use server';

import { revalidatePath } from 'next/cache';
import { setUserApprovedByEmail } from '@/app/lib/api/adminServer';

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

