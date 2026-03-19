import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

async function getAuthTokenOrNullAsync(): Promise<string | null> {
  const store = await cookies();
  const token = store.get('__session')?.value;
  return typeof token === 'string' && token.trim() ? token.trim() : null;
}

function joinUrlWithSearchParams(baseUrl: string, request: Request): string {
  const reqUrl = new URL(request.url);
  const out = new URL(baseUrl);
  out.search = reqUrl.search;
  return out.toString();
}

export async function GET(request: Request) {
  try {
    const token = await getAuthTokenOrNullAsync();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const url = joinUrlWithSearchParams(`${API_BASE_URL}/api/quellen-finder/project-pdf`, request);
    const res = await fetch(url, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      cache: 'no-store',
    });

    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      return NextResponse.json({ error: detail || 'Request failed.' }, { status: res.status });
    }

    const headers = new Headers();
    const contentType = res.headers.get('content-type');
    const contentDisposition = res.headers.get('content-disposition');
    const contentLength = res.headers.get('content-length');
    if (contentType) headers.set('content-type', contentType);
    if (contentDisposition) headers.set('content-disposition', contentDisposition);
    if (contentLength) headers.set('content-length', contentLength);
    headers.set('cache-control', 'no-store');

    return new Response(res.body, {
      status: res.status,
      headers,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unbekannter Fehler';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
