// Data Transformers
// Convert between Firebase data structures and UI types

import type { Quelle as FirebaseQuelle } from "@/app/actions/quellen";
import type {
  Kapitel as FirebaseKapitel,
  KapitelRun as FirebaseKapitelRun,
  KapitelRunResult as FirebaseKapitelRunResult,
} from "@/app/actions/kapitels";
import type {
  Quelle as UIQuelle,
  Kapitel as UIKapitel,
  Run as UIRun,
  QuellenErgebnis as UIQuellenErgebnis,
} from "@/app/types/ui";

/**
 * Transform Firebase Quelle to UI Quelle
 * Maps: title → name, content → text, images metadata → image URLs
 */
export function transformQuelleToUI(
  fbQuelle: FirebaseQuelle,
  projektId: string
): UIQuelle {
  return {
    id: fbQuelle.id,
    name: fbQuelle.title,
    // V2: Quelle content is stored separately at `quellen/{id}/content/main` and should be loaded on open.
    text: "",
    wordCount: typeof fbQuelle.wordCount === "number" ? fbQuelle.wordCount : undefined,
    projektId,
    createdAt: new Date(fbQuelle.createdAt),
    images: fbQuelle.images?.map((img) => img.url),
    // Advanced metadata fields
    autor: fbQuelle.autor,
    jahr: fbQuelle.jahr,
    typ: fbQuelle.typ,
    url: fbQuelle.url,
    zugriffAm: fbQuelle.zugriffAm,
    color: fbQuelle.color,
  };
}

/**
 * Transform Firebase Kapitel to UI Kapitel
 * Adds: nummer field, status computation
 * Maps: quelleIds → assignedQuellenIds
 */
export function transformKapitelToUI(
  fbKapitel: FirebaseKapitel,
  projektId: string
): UIKapitel {
  // V2: Kapitel status comes from denormalized `latestRun.status`
  const latestStatus = fbKapitel.latestRun?.status ?? "none";
  const status: "nicht-verarbeitet" | "in-bearbeitung" | "fertig" =
    latestStatus === "done"
      ? "fertig"
      : latestStatus === "running"
      ? "in-bearbeitung"
      : "nicht-verarbeitet";

  return {
    id: fbKapitel.id,
    title: fbKapitel.title,
    thema: fbKapitel.thema || "",
    nummer: fbKapitel.nummer || "1",
    status,
    latestRunId: fbKapitel.latestRun?.runId,
    order: fbKapitel.order ?? 0,
    projektId,
    assignedQuellenIds: fbKapitel.quelleIds || [],
    parentId: fbKapitel.parentId ?? null,
    activeRunId: fbKapitel.activeRunId ?? undefined,
  };
}

/**
 * Transform Firebase KapitelRunResult to UI QuellenErgebnis
 */
export function transformResultToUI(
  fbResult: FirebaseKapitelRunResult,
  quelleName: string = ""
): UIQuellenErgebnis {
  // Determine status
  let status: UIQuellenErgebnis["status"] = "success";
  if (fbResult.status === "running") status = "waiting";
  else if (fbResult.status === "error") status = "error";
  else if (fbResult.status === "no-content") status = "no-content";
  else if (fbResult.hasContent === false) status = "no-content";

  // UI uses cents, Firestore stores USD float.
  const baseCostUsd = fbResult.costUsd || 0;
  const refinementCostUsd = fbResult.refinement?.costTotalUsd || 0;
  const costUsd = baseCostUsd + refinementCostUsd;
  const costInCents = Math.round(costUsd * 100);

  return {
    id: fbResult.quelleId,
    quelleId: fbResult.quelleId,
    quelleName,
    text: fbResult.content || "",
    status,
    cost: costInCents,
    costUsd,
  };
}

/**
 * Transform Firebase KapitelRun to UI Run
 */
export function transformRunToUI(
  fbRun: FirebaseKapitelRun,
  kapitelId: string,
  quellenMap: Map<string, string> = new Map() // quelleId -> quelleName
): UIRun {
  // Transform individual results
  const quellenErgebnisse: UIQuellenErgebnis[] = fbRun.results.map((result) => {
    const quelleName = quellenMap.get(result.quelleId) || "";
    return transformResultToUI(result, quelleName);
  });

  // Calculate total costs in cents
  const quellenCost = quellenErgebnisse.reduce((sum, r) => sum + r.cost, 0);
  const quellenCostUsd = quellenErgebnisse.reduce((sum, r) => sum + (r.costUsd || 0), 0);
  const combined = fbRun.artifacts?.combined ?? null;
  const shortened = fbRun.artifacts?.shortened ?? null;
  const lesefluss = fbRun.artifacts?.lesefluss ?? null;

  const combinedStatus: "empty" | "running" | "success" | "error" =
    combined?.status ?? fbRun.artifactsStatus?.combined ?? (combined && combined.content ? "success" : "empty");
  const shortenedStatus: "empty" | "running" | "success" | "error" =
    shortened?.status ?? fbRun.artifactsStatus?.shortened ?? (shortened && shortened.content ? "success" : "empty");
  const leseflussStatus: "empty" | "running" | "success" | "error" =
    lesefluss?.status ?? fbRun.artifactsStatus?.lesefluss ?? (lesefluss && lesefluss.content ? "success" : "empty");

  const combinedCost = combined ? Math.round((combined.costUsd || 0) * 100) : 0;
  const combinedCostUsd = combined ? Number(combined.costUsd || 0) : 0;
  const combinedRefinementCost = combined
    ? Math.round(((combined.refinement?.costTotalUsd || 0) as number) * 100)
    : 0;
  const combinedRefinementCostUsd = combined ? Number((combined.refinement?.costTotalUsd || 0) as number) : 0;

  const shortenedCost = shortened ? Math.round((shortened.costUsd || 0) * 100) : undefined;
  const shortenedCostUsd = shortened ? Number(shortened.costUsd || 0) : undefined;
  const shortenedRefinementCost = shortened
    ? Math.round(((shortened.refinement?.costTotalUsd || 0) as number) * 100)
    : 0;
  const shortenedRefinementCostUsd = shortened ? Number((shortened.refinement?.costTotalUsd || 0) as number) : 0;

  const leseflussCost = lesefluss ? Math.round((lesefluss.costUsd || 0) * 100) : undefined;
  const leseflussCostUsd = lesefluss ? Number(lesefluss.costUsd || 0) : undefined;
  const leseflussRefinementCost = lesefluss
    ? Math.round(((lesefluss.refinement?.costTotalUsd || 0) as number) * 100)
    : 0;
  const leseflussRefinementCostUsd = lesefluss ? Number((lesefluss.refinement?.costTotalUsd || 0) as number) : 0;

  // Determine status
  // For now, simplified: if we have a combined result, it's success
  // In future, we could add more sophisticated status tracking
  const status: "success" | "error" | "running" = combined
    ? "success"
    : "running";

  return {
    id: fbRun.id,
    index: fbRun.index,
    name: fbRun.name,
    kapitelId,
    timestamp: new Date(fbRun.createdAt),
    status,
    model: fbRun.model || "",
    ueberschrift: fbRun.ueberschrift || combined?.heading || "",
    thema:
      fbRun.thema || fbRun.instruction || combined?.topic || "",
    combinedText: combined?.content || "",
    quellenErgebnisse,
    quellenCost,
    quellenCostUsd,
    combinedCost,
    combinedCostUsd,
    combinedStatus,
    combinedRefinementCost,
    combinedRefinementCostUsd,
    shortenedRefinementCost,
    shortenedRefinementCostUsd,
    shortenedText: shortened?.content || null,
    shortenedCost,
    shortenedCostUsd,
    shortenedStatus,
    shortenedOriginalLength: shortened?.originalLength,
    shortenedLength: shortened?.shortenedLength,
    leseflussText: lesefluss?.content || null,
    leseflussAufgabenstellung: lesefluss?.aufgabenstellung,
    leseflussOriginalLength: lesefluss?.originalLength,
    leseflussLength: lesefluss?.leseflussLength,
    leseflussCost,
    leseflussCostUsd,
    leseflussStatus,
    leseflussRefinementCost,
    leseflussRefinementCostUsd,
  };
}

/**
 * Create a map of quelle IDs to names from UI Quellen array
 */
export function createQuellenMap(quellen: UIQuelle[]): Map<string, string> {
  const map = new Map<string, string>();
  quellen.forEach((q) => {
    map.set(q.id, q.name);
  });
  return map;
}
