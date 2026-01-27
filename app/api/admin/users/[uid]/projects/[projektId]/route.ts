import type { NextRequest } from 'next/server';
import { proxyAdminJson } from '@/app/api/admin/_fastapiProxy';

type RouteContext = { params: Promise<{ uid: string; projektId: string }> };

export async function DELETE(request: NextRequest, { params }: RouteContext) {
  const { uid, projektId } = await params;
  return proxyAdminJson(request, `/api/admin/users/${encodeURIComponent(uid)}/projects/${encodeURIComponent(projektId)}`);
}

