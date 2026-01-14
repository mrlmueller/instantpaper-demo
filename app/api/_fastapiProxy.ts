import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

type FastApiErrorPayload = { detail?: unknown; error?: unknown; message?: unknown };

async function readFastApiError(res: Response): Promise<string | null> {
  try {
    const data = (await res.json()) as FastApiErrorPayload;
    const candidates = [data?.detail, data?.error, data?.message];
    for (const c of candidates) {
      if (typeof c === 'string' && c.trim()) return c.trim();
    }
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

export async function proxyFastApiJson(request: Request, path: string, init?: RequestInit): Promise<Response> {
  const token = await getAuthTokenOrNullAsync();
  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const url = `${API_BASE_URL}${path}`;
  const method = init?.method || request.method || 'GET';
  const headers = new Headers(init?.headers || undefined);
  headers.set('Authorization', `Bearer ${token}`);

  let body: string | undefined = undefined;
  if (method !== 'GET' && method !== 'HEAD') {
    headers.set('Content-Type', 'application/json');
    body = await request.text();
    if (!body) body = undefined;
  }

  const res = await fetch(url, {
    method,
    headers,
    body,
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiError(res);
    return NextResponse.json({ error: detail || 'Request failed.' }, { status: res.status });
  }

  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

