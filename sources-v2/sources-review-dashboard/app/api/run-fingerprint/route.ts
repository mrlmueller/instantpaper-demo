import { promises as fs } from "node:fs";
import path from "node:path";

import { unstable_noStore as noStore } from "next/cache";
import { NextResponse } from "next/server";

import { RUNS_DIR } from "@/lib/dashboard-utils";

export const dynamic = "force-dynamic";
export const revalidate = 0;

interface RunFingerprintResponse {
  fingerprint: string;
  generatedAt: string;
  runCount: number;
}

async function buildRunFingerprint(): Promise<RunFingerprintResponse> {
  const runsDir = path.resolve(process.cwd(), RUNS_DIR);

  try {
    const entries = await fs.readdir(runsDir, { withFileTypes: true });
    const parts = await Promise.all(
      entries
        .filter((entry) => entry.isDirectory())
        .map(async (entry) => {
          try {
            const stat = await fs.stat(path.join(runsDir, entry.name));
            return `${entry.name}:${stat.mtime.toISOString()}`;
          } catch {
            return `${entry.name}:missing`;
          }
        }),
    );

    parts.sort((left, right) => left.localeCompare(right));

    return {
      fingerprint: parts.join("|"),
      generatedAt: new Date().toISOString(),
      runCount: parts.length,
    };
  } catch {
    return {
      fingerprint: "",
      generatedAt: new Date().toISOString(),
      runCount: 0,
    };
  }
}

export async function GET() {
  noStore();

  const payload = await buildRunFingerprint();
  return NextResponse.json(payload, {
    headers: {
      "Cache-Control": "no-store, max-age=0, must-revalidate",
    },
  });
}
