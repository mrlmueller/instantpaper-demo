import type { NextRequest } from 'next/server';
import { proxyAdminJson } from '@/app/api/admin/_fastapiProxy';

type RouteContext = { params: Promise<{ code: string }> };

export async function GET(request: NextRequest, { params }: RouteContext) {
  const { code } = await params;
  return proxyAdminJson(request, `/api/admin/access-codes/${encodeURIComponent(code)}`, { method: 'GET' });
}

export async function PATCH(request: NextRequest, { params }: RouteContext) {
  const { code } = await params;
  return proxyAdminJson(request, `/api/admin/access-codes/${encodeURIComponent(code)}`, { method: 'PATCH' });
}

