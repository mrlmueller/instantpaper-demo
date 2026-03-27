import { NextResponse } from 'next/server';
import {
  buildFastApiUrl,
  getSessionTokenOrNull,
  joinFastApiUrlWithRequestSearch,
} from '@/app/lib/server/fastapi';

export async function GET(request: Request) {
  try {
    const token = await getSessionTokenOrNull();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const url = joinFastApiUrlWithRequestSearch('/api/quellen-finder/project-pdf', request);
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

export async function DELETE(request: Request) {
  try {
    const token = await getSessionTokenOrNull();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const url = joinFastApiUrlWithRequestSearch('/api/quellen-finder/project-pdf', request);
    const res = await fetch(url, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      cache: 'no-store',
    });

    const text = await res.text().catch(() => '');
    const contentType = res.headers.get('content-type') || '';
    if (!res.ok) {
      return new NextResponse(text || JSON.stringify({ error: 'Request failed.' }), {
        status: res.status,
        headers: {
          'content-type': contentType.includes('application/json') ? contentType : 'application/json',
          'cache-control': 'no-store',
        },
      });
    }

    if (contentType.includes('application/json')) {
      return new NextResponse(text, {
        status: res.status,
        headers: {
          'content-type': 'application/json',
          'cache-control': 'no-store',
        },
      });
    }
    return NextResponse.json({ error: 'Unexpected backend response.' }, { status: 502 });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unbekannter Fehler';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const token = await getSessionTokenOrNull();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const bodyText = await request.text();
    const res = await fetch(buildFastApiUrl('/api/quellen-finder/project-pdf'), {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: bodyText,
      cache: 'no-store',
    });

    const text = await res.text().catch(() => '');
    const contentType = res.headers.get('content-type') || '';
    if (!res.ok) {
      return new NextResponse(text || JSON.stringify({ error: 'Request failed.' }), {
        status: res.status,
        headers: {
          'content-type': contentType.includes('application/json') ? contentType : 'application/json',
          'cache-control': 'no-store',
        },
      });
    }

    return new NextResponse(text || '{}', {
      status: res.status,
      headers: {
        'content-type': contentType.includes('application/json') ? contentType : 'application/json',
        'cache-control': 'no-store',
      },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unbekannter Fehler';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
