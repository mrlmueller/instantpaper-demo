import type { NextRequest } from 'next/server';
import { proxyFastApiJson } from '@/app/api/_fastapiProxy';

export async function POST(request: NextRequest) {
  const headers = new Headers();
  const xff = request.headers.get('x-forwarded-for');
  const xrip = request.headers.get('x-real-ip');
  const ua = request.headers.get('user-agent');
  if (xff) headers.set('x-forwarded-for', xff);
  if (xrip) headers.set('x-real-ip', xrip);
  if (ua) headers.set('user-agent', ua);

  return proxyFastApiJson(request, '/api/access-codes/redeem', { method: 'POST', headers });
}

