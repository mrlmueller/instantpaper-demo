import type { NextRequest } from 'next/server';
import { proxyAdminJson } from '@/app/api/admin/_fastapiProxy';

type RouteContext = { params: Promise<{ uid: string; templateId: string }> };

export async function PUT(request: NextRequest, { params }: RouteContext) {
  const { uid, templateId } = await params;
  return proxyAdminJson(
    request,
    `/api/admin/users/${encodeURIComponent(uid)}/prompt-templates/${encodeURIComponent(templateId)}`
  );
}

export async function DELETE(request: NextRequest, { params }: RouteContext) {
  const { uid, templateId } = await params;
  return proxyAdminJson(
    request,
    `/api/admin/users/${encodeURIComponent(uid)}/prompt-templates/${encodeURIComponent(templateId)}`
  );
}
