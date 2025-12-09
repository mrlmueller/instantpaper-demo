// Data Transformers
// Convert between Firebase data structures and UI types

import type { Quelle as FirebaseQuelle } from '@/app/actions/quellen';
import type {
  Kapitel as FirebaseKapitel,
  KapitelRun as FirebaseKapitelRun,
  KapitelRunResult as FirebaseKapitelRunResult,
  CombinedResult as FirebaseCombinedResult,
} from '@/app/actions/kapitels';
import type {
  Quelle as UIQuelle,
  Kapitel as UIKapitel,
  Run as UIRun,
  QuellenErgebnis as UIQuellenErgebnis,
} from '@/app/types/ui';

/**
 * Transform Firebase Quelle to UI Quelle
 * Maps: title → name, content → text
 */
export function transformQuelleToUI(
  fbQuelle: FirebaseQuelle,
  projektId: string
): UIQuelle {
  return {
    id: fbQuelle.id,
    name: fbQuelle.title,
    text: fbQuelle.content,
    projektId,
    createdAt: new Date(fbQuelle.createdAt),
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
  // Compute status from runs
  let status: "nicht-verarbeitet" | "in-bearbeitung" | "fertig" =
    "nicht-verarbeitet";

  if (fbKapitel.runs && fbKapitel.runs.length > 0) {
    const latestRun = fbKapitel.runs[0];
    // If combined result exists, it's finished
    if (latestRun.combined && latestRun.combined.combinedContent) {
      status = "fertig";
    }
    // If individual results exist but no combined, it's in progress
    else if (latestRun.results && latestRun.results.length > 0) {
      status = "in-bearbeitung";
    }
  }

  return {
    id: fbKapitel.id,
    title: fbKapitel.title,
    nummer: (fbKapitel as any).nummer || "1", // Default to "1" for existing kapitels
    status,
    order: fbKapitel.order ?? 0,
    projektId,
    assignedQuellenIds: fbKapitel.quelleIds || [],
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
  let status: "waiting" | "success" | "no-content" = "success";
  if (fbResult.hasContent === false) {
    status = "no-content";
  }

  // Convert cost from dollars to cents (EUR)
  // Note: Firebase stores in USD, UI expects cents in EUR
  // For now, just convert to cents (multiply by 100)
  const costInCents = Math.round((fbResult.cost || 0) * 100);

  return {
    id: fbResult.quelleId,
    quelleId: fbResult.quelleId,
    quelleName,
    text: fbResult.resultContent || "",
    status,
    cost: costInCents,
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
  const combinedCost = fbRun.combined
    ? Math.round((fbRun.combined.cost || 0) * 100)
    : 0;

  // Determine status
  // For now, simplified: if we have a combined result, it's success
  // In future, we could add more sophisticated status tracking
  const status: "success" | "error" | "running" = fbRun.combined
    ? "success"
    : "running";

  return {
    id: fbRun.id,
    index: fbRun.index,
    kapitelId,
    timestamp: new Date(fbRun.createdAt),
    status,
    model: fbRun.model || "",
    ueberschrift: (fbRun as any).ueberschrift || fbRun.combined?.heading || "",
    thema: (fbRun as any).thema || fbRun.instruction || fbRun.combined?.topic || "",
    combinedText: fbRun.combined?.combinedContent || "",
    quellenErgebnisse,
    quellenCost,
    combinedCost,
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
