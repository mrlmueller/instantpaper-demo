import type { NextRequest } from 'next/server';
import { proxyFastApiJson } from '@/app/api/_fastapiProxy';

export async function GET(request: NextRequest) {
  return proxyFastApiJson(request, '/api/me', { method: 'GET' });
}

