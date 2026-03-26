import { NextResponse } from "next/server";
import { buildFastApiUrl, getSessionTokenOrNull } from "@/app/lib/server/fastapi";

export async function POST(request: Request) {
  try {
    const token = await getSessionTokenOrNull();
    if (!token) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    const body = await request.text();
    const res = await fetch(buildFastApiUrl("/api/quellen-finder/project-pdf-duplicate-check"), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body,
      cache: "no-store",
    });

    const text = await res.text().catch(() => "");
    const contentType = res.headers.get("content-type") || "";
    if (!res.ok) {
      return NextResponse.json({ error: text || "Request failed." }, { status: res.status });
    }
    if (contentType.includes("application/json")) {
      return new NextResponse(text, {
        status: res.status,
        headers: {
          "content-type": "application/json",
          "cache-control": "no-store",
        },
      });
    }
    return NextResponse.json({ error: "Unexpected backend response." }, { status: 502 });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unbekannter Fehler";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
