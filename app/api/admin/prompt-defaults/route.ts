import { NextResponse } from 'next/server';
import {
  buildFastApiUrl,
  getSessionTokenOrNull,
  readFastApiErrorDetail,
} from '@/app/lib/server/fastapi';

export async function GET() {
  try {
    const token = await getSessionTokenOrNull();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const res = await fetch(buildFastApiUrl('/api/admin/prompt-defaults'), {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });

    if (!res.ok) {
      const detail = await readFastApiErrorDetail(res);
      return NextResponse.json({ error: detail || 'Failed to load prompt defaults.' }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const token = await getSessionTokenOrNull();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const body = await request.json();
    const res = await fetch(buildFastApiUrl('/api/admin/prompt-defaults'), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    if (!res.ok) {
      const detail = await readFastApiErrorDetail(res);
      return NextResponse.json({ error: detail || 'Failed to save prompt default.' }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 500 });
  }
}
