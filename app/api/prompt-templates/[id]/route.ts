import { NextResponse } from 'next/server';
import { deletePromptTemplate, updatePromptTemplate } from '@/app/actions/promptTemplates';

type ParamsPromise = Promise<{ id: string }>;

export async function PUT(request: Request, { params }: { params: ParamsPromise }) {
  try {
    const { id } = await params;
    const body = await request.json();
    await updatePromptTemplate(id, body);
    return NextResponse.json({ ok: true });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 400 });
  }
}

export async function DELETE(_req: Request, { params }: { params: ParamsPromise }) {
  try {
    const { id } = await params;
    await deletePromptTemplate(id);
    return NextResponse.json({ ok: true });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 400 });
  }
}
