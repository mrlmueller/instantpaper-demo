import { NextResponse } from 'next/server';
import {
  getSessionTokenOrNull,
  joinFastApiUrlWithRequestSearch,
  readFastApiErrorDetail,
} from '@/app/lib/server/fastapi';

function extractFirstUrl(value: string | null | undefined): string | null {
  const raw = String(value || '');
  const match = raw.match(/https?:\/\/\S+/);
  if (!match) return null;
  return match[0].replace(/[).,;\\]}>]+$/, '');
}

export async function proxyAdminJson(request: Request, path: string, init?: RequestInit): Promise<Response> {
  try {
    const token = await getSessionTokenOrNull();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const url = joinFastApiUrlWithRequestSearch(path, request);

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
      const detail = await readFastApiErrorDetail(res);
      const createIndexUrl = extractFirstUrl(detail);
      return NextResponse.json({ error: detail || 'Request failed.', createIndexUrl }, { status: res.status });
    }

    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 500 });
  }
}

