import { NextResponse } from 'next/server';
import {
  buildFastApiUrl,
  getSessionTokenOrNull,
  readFastApiErrorDetail,
} from '@/app/lib/server/fastapi';

export async function POST(request: Request) {
  try {
    const token = await getSessionTokenOrNull();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const body = await request.json();
    const res = await fetch(buildFastApiUrl('/api/system-prompt-templates/duplicate'), {
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
      return NextResponse.json({ error: detail || 'Failed to duplicate system prompt.' }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 500 });
  }
}

