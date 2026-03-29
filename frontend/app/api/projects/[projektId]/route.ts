import type { NextRequest } from 'next/server';
import { proxyFastApiJson } from '@/app/api/_fastapiProxy';

type RouteContext = { params: Promise<{ projektId: string }> };

export async function DELETE(request: NextRequest, { params }: RouteContext) {
  const { projektId } = await params;
  return proxyFastApiJson(request, `/api/projects/${encodeURIComponent(projektId)}`);
}

