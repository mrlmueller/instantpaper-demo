export type QuelleZitatModus = "auto" | "authorYear" | "full" | "none";

export type QuelleZitatPreview = {
  value: string;
  kind: "authorYear" | "full" | "none";
};

export function toOneLine(value: string): string {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

export function computeQuelleZitatPreview(args: {
  autor?: string | null;
  jahr?: number | null;
  zitat?: string | null;
  modus?: QuelleZitatModus | null;
}): QuelleZitatPreview {
  const modus = args.modus ?? "auto";
  const autor = toOneLine(args.autor ?? "");
  const zitat = toOneLine(args.zitat ?? "");
  const jahr = typeof args.jahr === "number" && !Number.isNaN(args.jahr) ? args.jahr : null;

  const hasAuthorYear = Boolean(autor) && jahr !== null;
  const authorYearValue = hasAuthorYear ? `${autor}, ${jahr}` : "";

  if (modus === "none") return { value: "", kind: "none" };
  if (modus === "authorYear") {
    return authorYearValue
      ? { value: authorYearValue, kind: "authorYear" }
      : { value: "", kind: "none" };
  }
  if (modus === "full") {
    return zitat ? { value: zitat, kind: "full" } : { value: "", kind: "none" };
  }

  // auto: author+year if available, else full citation, else none
  if (authorYearValue) return { value: authorYearValue, kind: "authorYear" };
  if (zitat) return { value: zitat, kind: "full" };
  return { value: "", kind: "none" };
}

