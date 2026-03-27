import { NextResponse } from 'next/server';
import { buildFastApiUrl, getSessionTokenOrNull, readFastApiErrorDetail } from '@/app/lib/server/fastapi';

export async function POST(): Promise<Response> {
  const sessionCookie = await getSessionTokenOrNull();

  if (!sessionCookie) {
    return NextResponse.json({ status: 'missing-session' }, { status: 200 });
  }

  const res = await fetch(buildFastApiUrl('/api/auth/revoke'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionCookie }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiErrorDetail(res);
    return NextResponse.json({ error: detail || 'Request failed.' }, { status: res.status });
  }

  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
