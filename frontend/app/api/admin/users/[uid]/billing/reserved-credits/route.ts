import type { NextRequest } from 'next/server';

import { proxyAdminJson } from '@/app/api/admin/_fastapiProxy';

type RouteContext = { params: Promise<{ uid: string }> };

export async function POST(request: NextRequest, { params }: RouteContext) {
  const { uid } = await params;
  return proxyAdminJson(request, `/api/admin/users/${encodeURIComponent(uid)}/billing/reserved-credits`);
}

