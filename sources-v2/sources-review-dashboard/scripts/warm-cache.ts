import { promises as fs } from "node:fs";
import path from "node:path";

import { getDashboardPayload } from "../lib/dashboard-data";

async function main() {
  const runsDir = path.resolve(process.cwd(), "../runs");
  const runIds = (await fs.readdir(runsDir, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .filter((name) => !name.startsWith("_"))
    .sort();

  console.log(`warming ${runIds.length} run caches`);

  for (const runId of runIds) {
    const startedAt = Date.now();
    await getDashboardPayload(runId, null);
    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(2);
    console.log(`${runId} ${elapsed}s`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
