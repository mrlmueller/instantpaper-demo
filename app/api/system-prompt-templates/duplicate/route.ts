import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

type FastApiErrorPayload = { detail?: unknown };

async function readErrorDetail(res: Response): Promise<string | null> {
  try {
    const data = (await res.json()) as FastApiErrorPayload;
    if (typeof data?.detail === 'string' && data.detail.trim()) return data.detail.trim();
  } catch {
    // ignore
  }
  return null;
}

async function getAuthTokenOrNullAsync(): Promise<string | null> {
  const store = await cookies();
  const token = store.get('__session')?.value;
  return typeof token === 'string' && token.trim() ? token.trim() : null;
}

export async function POST(request: Request) {
  try {
    const token = await getAuthTokenOrNullAsync();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const body = await request.json();
    const res = await fetch(`${API_BASE_URL}/api/system-prompt-templates/duplicate`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    if (!res.ok) {
      const detail = await readErrorDetail(res);
      return NextResponse.json({ error: detail || 'Failed to duplicate system prompt.' }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 500 });
  }
}

