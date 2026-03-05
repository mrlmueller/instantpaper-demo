import type { ReactNode } from "react";

export type HelpLang = "de" | "en";

export type HelpImage = {
  src: string;
  alt: string;
  caption: { de: string; en: string };
};

export type HelpEntry = {
  title: { de: string; en: string };
  body: { de: ReactNode; en: ReactNode };
  images?: HelpImage[];
};

function InlineCode({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[12px]">{children}</span>;
}

function H({ children }: { children: ReactNode }) {
  return <div className="text-xs font-semibold text-foreground">{children}</div>;
}

function P({ children }: { children: ReactNode }) {
  return <p className="text-sm leading-relaxed text-muted-foreground">{children}</p>;
}

function UL({ children }: { children: ReactNode }) {
  return <ul className="list-disc pl-5 text-sm text-muted-foreground space-y-1">{children}</ul>;
}

function LI({ children }: { children: ReactNode }) {
  return <li className="leading-relaxed">{children}</li>;
}

const lanesPools = {
  de: (
    <div className="space-y-2">
      <H>Grundbegriffe (Lane &amp; Pool)</H>
      <UL>
        <LI>
          <InlineCode>Lane</InlineCode>: <InlineCode>match</InlineCode> priorisiert thematische Passung;{" "}
          <InlineCode>authority</InlineCode> priorisiert wissenschaftliche Bedeutung, soll aber weiterhin relevant bleiben.
        </LI>
        <LI>
          <InlineCode>Pool</InlineCode>: <InlineCode>with_abstract</InlineCode> vs{" "}
          <InlineCode>without_abstract</InlineCode>. Die Pools werden im gesamten Pipeline‑Verlauf strikt getrennt (kein
          “Mixing” beim Ranking).
        </LI>
        <LI>Viele Plots sind deshalb bewusst “zweifarbig”: gleiche Metrik, aber getrennt nach Pool.</LI>
      </UL>
    </div>
  ),
  en: (
    <div className="space-y-2">
      <H>Core concepts (Lane &amp; Pool)</H>
      <UL>
        <LI>
          <InlineCode>Lane</InlineCode>: <InlineCode>match</InlineCode> prioritizes topical fit;{" "}
          <InlineCode>authority</InlineCode> prioritizes scholarly importance while still aiming to remain relevant.
        </LI>
        <LI>
          <InlineCode>Pool</InlineCode>: <InlineCode>with_abstract</InlineCode> vs{" "}
          <InlineCode>without_abstract</InlineCode>. Pools are kept strictly separate throughout ranking and reranking.
        </LI>
        <LI>Many plots are intentionally “two‑colored” for this reason.</LI>
      </UL>
    </div>
  ),
} satisfies { de: ReactNode; en: ReactNode };

export const PIPELINE_DETAILS_HELP: Record<string, HelpEntry> = {
  // -------------------------
  // B: Planung
  // -------------------------
  "b.topic_summary": {
    title: { de: "Topic Summary", en: "Topic Summary" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Das Topic Summary ist die “Arbeitsdefinition” deines Kapitels für die Pipeline. Es wird in Phase B vom
            Planner‑LLM aus Kapitel‑Titel und Kapitel‑Beschreibung erzeugt und dient als Kompass für alle folgenden
            Schritte.
          </P>
          <div className="space-y-2">
            <H>Wofür wird es downstream genutzt?</H>
            <UL>
              <LI>
                Gibt Kontext für die Query‑Generierung (Phase C): welche Facetten wichtig sind, welche Begriffe dominieren
                sollen.
              </LI>
              <LI>
                Hilft beim Debugging: Wenn Ergebnisse “komisch” wirken, ist das Topic Summary oft der schnellste Hinweis,
                ob die Pipeline dein Thema richtig verstanden hat.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Gute vs. problematische Signale</H>
            <UL>
              <LI>
                <span className="text-foreground">Gut:</span> klarer Scope (Zeit/Region/Methodik), typische Quellenarten,
                und erkennbare Abgrenzungen.
              </LI>
              <LI>
                <span className="text-foreground">Auffällig:</span> zu generisch (“overview of …”), zu breit (mehrere
                Disziplinen ohne Fokus), oder falsche Epoche/Region → führt oft zu Retrieval‑Drift.
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            The topic summary is the pipeline’s “working definition” of your chapter. It is produced in Phase B by the
            planner LLM from the chapter title and chapter spec and acts as a compass for all later phases.
          </P>
          <div className="space-y-2">
            <H>How it is used downstream</H>
            <UL>
              <LI>Provides context for query generation (Phase C): which facets matter and what should dominate.</LI>
              <LI>
                Debugging aid: when results feel “off”, the topic summary is often the fastest signal that the pipeline
                misunderstood the scope.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Good vs. problematic signals</H>
            <UL>
              <LI>
                <span className="text-foreground">Good:</span> clear scope (time/region/method), typical source types,
                and explicit boundaries.
              </LI>
              <LI>
                <span className="text-foreground">Suspicious:</span> overly generic, overly broad, or wrong epoch/region
                → often leads to retrieval drift later.
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "b.primary_anchors": {
    title: { de: "Primary Anchors (Kontext‑Anker)", en: "Primary Anchors (Context Anchors)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Primary Anchors sind kurze, “hygienische” Schlüsselbegriffe (EN+DE), die sicherstellen sollen, dass Queries
            und spätere Scoring‑Schritte auf dem Kapitel‑Thema bleiben. In Phase C wird für viele Queries geprüft, ob
            mindestens ein Anchor vorkommt.
          </P>
          {lanesPools.de}
          <div className="space-y-2">
            <H>Worauf du achten solltest</H>
            <UL>
              <LI>
                <span className="text-foreground">Gut:</span> konkrete Domänenbegriffe (Personen/Orte/Epochen/Objekte),
                die nicht beliebig sind.
              </LI>
              <LI>
                <span className="text-foreground">Schlecht:</span> generische Wörter (“system”, “model”, “framework”) →
                erhöhte Drift‑Gefahr.
              </LI>
              <LI>Zu “enge” Anchors können Queries unnötig verengen → mehr Zero‑Result Queries in Phase D.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Primary anchors are short, “hygienic” key terms (EN+DE) that keep queries and downstream scoring on-topic.
            In Phase C, many queries are validated to include at least one anchor.
          </P>
          {lanesPools.en}
          <div className="space-y-2">
            <H>What to look for</H>
            <UL>
              <LI>
                <span className="text-foreground">Good:</span> concrete domain anchors (people/places/periods/objects)
                that are not generic.
              </LI>
              <LI>
                <span className="text-foreground">Bad:</span> generic terms (“system”, “model”, “framework”) → higher
                drift risk.
              </LI>
              <LI>Anchors that are too narrow can over-constrain queries → more zero-result queries in Phase D.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "b.global_terms": {
    title: { de: "Global Terms (kanonische Begriffe)", en: "Global Terms (Canonical Terms)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Global Terms sind thematische “Kerngriffe” (EN+DE), die das Kapitel beschreiben. Sie werden in Phase B erzeugt
            und in späteren Phasen indirekt genutzt – u. a. als Signale für Debug‑Listen (z. B. “Econ‑Hits” in Kandidaten).
          </P>
          <div className="space-y-2">
            <H>Wie du sie interpretierst</H>
            <UL>
              <LI>
                <span className="text-foreground">Gut:</span> Begriffe, die tatsächlich zentral sind und nicht nur
                “Akademiker‑Vokabular”.
              </LI>
              <LI>
                <span className="text-foreground">Auffällig:</span> viele zu breite Begriffe → Retrieval kann zu allgemein
                werden.
              </LI>
              <LI>Global Terms sind kein “Filter” für Ergebnisse, sondern ein Kontext‑/Diagnose‑Werkzeug.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Global terms are the chapter’s canonical vocabulary (EN+DE). They are generated in Phase B and used
            indirectly later, e.g. as signals for diagnostic lists (such as “econ hits” in the candidates view).
          </P>
          <div className="space-y-2">
            <H>How to interpret them</H>
            <UL>
              <LI>
                <span className="text-foreground">Good:</span> terms that are truly central, not generic academic filler.
              </LI>
              <LI>
                <span className="text-foreground">Suspicious:</span> too many broad terms → retrieval may become too
                generic.
              </LI>
              <LI>Global terms are not a hard filter; think of them as context + diagnostics.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "b.global_exclusions": {
    title: { de: "Global Exclusions (Ausschlüsse)", en: "Global Exclusions" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Exclusions sind kurze negative Begriffe, die Retrieval‑Drift verhindern sollen (z. B. moderne Themen bei einem
            antiken Kapitel). In Phase C werden Exclusions “bereinigt”: nur atomare, sichere Ausschlüsse werden in Queries
            übernommen.
          </P>
          <div className="space-y-2">
            <H>Gute vs. riskante Exclusions</H>
            <UL>
              <LI>
                <span className="text-foreground">Gut:</span> sehr konkrete, klar falsche Domänen (z. B. “cryptocurrency”).
              </LI>
              <LI>
                <span className="text-foreground">Riskant:</span> Begriffe, die auch im Zielgebiet vorkommen können →
                Recall‑Verlust (zu wenige Records/Kandidaten).
              </LI>
              <LI>Wenn Phase D viele Zero‑Result Queries zeigt, können zu aggressive Exclusions ein Grund sein.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Exclusions are short negative terms intended to prevent retrieval drift (e.g. modern topics for an ancient
            chapter). In Phase C, exclusions are sanitized: only “atomic” and safe exclusions are carried into provider
            queries.
          </P>
          <div className="space-y-2">
            <H>Good vs. risky exclusions</H>
            <UL>
              <LI>
                <span className="text-foreground">Good:</span> very concrete, clearly wrong domains (e.g. “cryptocurrency”).
              </LI>
              <LI>
                <span className="text-foreground">Risky:</span> terms that can also appear in the target domain → loss of
                recall (too few records/candidates).
              </LI>
              <LI>Many zero-result queries in Phase D can be a sign of overly aggressive exclusions.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "b.facets": {
    title: { de: "Facets", en: "Facets" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Facets sind die wichtigste Struktur im gesamten Lauf: 8–20 “atomare” thematische Aspekte (EN+DE) mit Gewicht
            (1–5). Sie steuern sowohl Retrieval (Phase C/D) als auch Scoring (Phase F/G), Coverage‑Tags (Phase H) und
            Rerank‑Prompts (Phase I).
          </P>
          <div className="space-y-2">
            <H>Warum sind Facets so zentral?</H>
            <UL>
              <LI>
                Jeder Kandidat bekommt downstream pro Facet Scores. Die Reihenfolge der Facets wird zur “kanonischen
                Index‑Reihenfolge” für Score‑Arrays.
              </LI>
              <LI>
                Facet‑Gewichte beeinflussen, welche Facets als “required” gelten (typisch: Gewicht ≥ 4). Required‑Facets
                tauchen in QC/Diagnosen und im Rerank‑Kontext besonders stark auf.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Wie erkennst du gute Facets?</H>
            <UL>
              <LI>
                <span className="text-foreground">Gut:</span> Facets sind “single idea” (nicht zwei Themen in einer Facet),
                decken Mechanismen/Daten/Methoden/Background ab und sind in EN &amp; DE konsistent.
              </LI>
              <LI>
                <span className="text-foreground">Auffällig:</span> viele fast‑duplizierte Facets → redundant, kostet
                Queries/Embedding‑Budget und kann Rankings verzerren.
              </LI>
            </UL>
          </div>
          {lanesPools.de}
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Facets are the core structure of the entire run: 8–20 “atomic” aspects (EN+DE) with weights (1–5). They
            drive retrieval (Phase C/D), scoring (Phase F/G), coverage tags (Phase H), and rerank prompts (Phase I).
          </P>
          <div className="space-y-2">
            <H>Why they matter</H>
            <UL>
              <LI>
                Every candidate receives per‑facet scores downstream. The facet order becomes the canonical index order
                for score arrays.
              </LI>
              <LI>
                Facet weights influence which facets are treated as “required” (typically weight ≥ 4). Required facets
                show up strongly in QC diagnostics and rerank context.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>What good facets look like</H>
            <UL>
              <LI>
                <span className="text-foreground">Good:</span> single idea per facet, balanced mix (mechanisms/data/methods/background), consistent in EN &amp; DE.
              </LI>
              <LI>
                <span className="text-foreground">Suspicious:</span> many near‑duplicates → wastes query/embedding budget and can skew rankings.
              </LI>
            </UL>
          </div>
          {lanesPools.en}
        </div>
      ),
    },
  },

  // -------------------------
  // C: Querries
  // -------------------------
  "c.openalex_queries": {
    title: { de: "OpenAlex Queries", en: "OpenAlex Queries" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Das sind die von Phase C erzeugten OpenAlex‑Query‑Objekte (Filter + Sort + Suchfeld + Query‑String). OpenAlex
            liefert typischerweise viele Records schnell, ist aber empfindlich gegenüber “zu breiten” Queries.
          </P>
          <div className="space-y-2">
            <H>Gute Signale</H>
            <UL>
              <LI>
                Abdeckung von <InlineCode>intent</InlineCode> (match/authority) und <InlineCode>language</InlineCode>{" "}
                (en/de).
              </LI>
              <LI>Keine starke Dominanz einzelner Queries (siehe Phase D: Dominance).</LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Wenn es auffällig ist…</H>
            <UL>
              <LI>Sehr wenige OpenAlex‑Queries → Recall kann sinken (weniger Kandidaten).</LI>
              <LI>Sehr viele Zero‑Result Queries → Query‑Strings oder Filter sind zu eng oder fehlerhaft.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            These are the Phase C generated OpenAlex query objects (filters + sort + search field + query string).
            OpenAlex tends to return many records quickly, but it can be sensitive to overly broad queries.
          </P>
          <div className="space-y-2">
            <H>Good signals</H>
            <UL>
              <LI>
                Coverage across <InlineCode>intent</InlineCode> (match/authority) and <InlineCode>language</InlineCode>{" "}
                (en/de).
              </LI>
              <LI>No single query dominates the retrieved records (see Phase D: Dominance).</LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>If it looks suspicious…</H>
            <UL>
              <LI>Very few OpenAlex queries → recall may drop (fewer candidates).</LI>
              <LI>Many zero-result queries → query strings or filters are too strict or malformed.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "c.s2_queries": {
    title: { de: "Semantic Scholar Queries", en: "Semantic Scholar Queries" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Semantic Scholar (S2) nutzt eine andere Suchsyntax (Bulk Search + Hydration). S2 kann andere Bereiche besser
            abdecken als OpenAlex, ist aber häufig langsamer und hat strengere Operator‑Regeln.
          </P>
          <div className="space-y-2">
            <H>Typische Auffälligkeiten</H>
            <UL>
              <LI>Viele Zero‑Result Queries: Query‑Syntax zu strikt oder falsche Required‑Gruppen.</LI>
              <LI>Nur ein Intent/Lang: dann entsteht ein einseitiger Kandidatenraum.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Semantic Scholar (S2) uses different search mechanics (bulk search + hydration). It can cover areas that
            OpenAlex misses, but it’s often slower and has stricter query-operator rules.
          </P>
          <div className="space-y-2">
            <H>Common red flags</H>
            <UL>
              <LI>Many zero-result queries: overly strict syntax or broken required groups.</LI>
              <LI>Only one intent/language: leads to a one-sided candidate universe.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "c.length_distribution": {
    title: { de: "Query String Length Distribution", en: "Query String Length Distribution" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Dieses Histogramm zeigt, wie lang die Query‑Strings pro Provider sind (in 10‑Zeichen‑Bins). Länge ist kein
            Qualitäts‑Score, aber ein guter Proxy für “Breite vs. Komplexität”.
          </P>
          <div className="space-y-2">
            <H>Wie du es liest</H>
            <UL>
              <LI>
                <span className="text-foreground">Sehr kurz</span> → oft breit, kann Drift/Noise erhöhen.
              </LI>
              <LI>
                <span className="text-foreground">Sehr lang</span> → oft sehr strikt; kann Zero‑Results erhöhen oder
                Provider‑Syntax anfälliger machen.
              </LI>
              <LI>Ein “gesunder” Run hat meist eine mittlere Länge mit etwas Varianz.</LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Was tun bei Problemen?</H>
            <UL>
              <LI>Viele lange Queries + viele Zero‑Results → Queries/Exclusions vereinfachen.</LI>
              <LI>Viele sehr kurze Queries + hohe Dominance in Phase D → mehr facet‑spezifische Queries.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This histogram shows query-string lengths per provider (10‑character bins). Length is not a quality score,
            but it is a useful proxy for “breadth vs. complexity”.
          </P>
          <div className="space-y-2">
            <H>How to read it</H>
            <UL>
              <LI>
                <span className="text-foreground">Very short</span> → often broad; can increase drift/noise.
              </LI>
              <LI>
                <span className="text-foreground">Very long</span> → often very strict; can raise zero-results and be
                more fragile to provider syntax rules.
              </LI>
              <LI>A “healthy” run often has a mid-range length with some variance.</LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>What to do if it looks off</H>
            <UL>
              <LI>Many long queries + many zero-results → simplify queries/exclusions.</LI>
              <LI>Many very short queries + high dominance in Phase D → add more facet-specific queries.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "c.generated_queries": {
    title: { de: "Generated Queries", en: "Generated Queries" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Hier siehst du die konkreten Queries, die an OpenAlex und Semantic Scholar geschickt werden. Diese sind
            “Candidate‑Generatoren”: downstream wird dedupliziert, gescored, gepruned und (optional) rerankt.
          </P>
          <div className="space-y-2">
            <H>Wichtige Felder</H>
            <UL>
              <LI>
                <InlineCode>intent</InlineCode>: <InlineCode>match</InlineCode> (thematisch) vs{" "}
                <InlineCode>authority</InlineCode> (zitations‑/impact‑getrieben).
              </LI>
              <LI>
                <InlineCode>language</InlineCode>: EN/DE Coverage ist Absicht (bilinguale Retrieval‑Anforderung).
              </LI>
              <LI>
                OpenAlex‑Extras (<InlineCode>filters</InlineCode>, <InlineCode>sort</InlineCode>,{" "}
                <InlineCode>search_field</InlineCode>) beeinflussen stark Recall/Precision.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Gute vs. schlechte Muster</H>
            <UL>
              <LI>
                <span className="text-foreground">Gut:</span> Notes passen zum Intent (“broad authority works”, “facet
                specific match”), Query enthält Anchors, Exclusions sind plausibel.
              </LI>
              <LI>
                <span className="text-foreground">Auffällig:</span> gleiche Query mehrfach (Duplikate), fehlende Anchors,
                oder sehr viele NOT‑Klauseln → oft Zero‑Results.
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This table shows the concrete queries sent to OpenAlex and Semantic Scholar. These are “candidate generators”:
            downstream we deduplicate, score, prune, and (optionally) rerank.
          </P>
          <div className="space-y-2">
            <H>Key fields</H>
            <UL>
              <LI>
                <InlineCode>intent</InlineCode>: <InlineCode>match</InlineCode> (topical) vs{" "}
                <InlineCode>authority</InlineCode> (citation/impact driven).
              </LI>
              <LI>
                <InlineCode>language</InlineCode>: EN/DE coverage is intentional (bilingual retrieval requirement).
              </LI>
              <LI>
                OpenAlex extras (<InlineCode>filters</InlineCode>, <InlineCode>sort</InlineCode>,{" "}
                <InlineCode>search_field</InlineCode>) strongly shape recall vs precision.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Good vs. suspicious patterns</H>
            <UL>
              <LI>
                <span className="text-foreground">Good:</span> notes match intent, anchors are present, exclusions look
                reasonable.
              </LI>
              <LI>
                <span className="text-foreground">Suspicious:</span> duplicates, missing anchors, or many NOT clauses →
                often produces zero-results.
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  // -------------------------
  // D: Retrival
  // -------------------------
  "d.provider_totals": {
    title: { de: "Provider Totals", en: "Provider Totals" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Diese Karten zeigen, wie viele Records pro Provider (OpenAlex vs S2) tatsächlich abgerufen wurden – plus
            Aufteilung nach <InlineCode>intent</InlineCode> (match/authority) und nach Abstract‑Verfügbarkeit.
          </P>
          <div className="space-y-2">
            <H>Warum ist das wichtig?</H>
            <UL>
              <LI>
                Phase D ist der “Volumen‑Regler”: mehr Records → mehr Kandidaten → mehr Scoring/Embedding‑Kosten.
              </LI>
              <LI>
                Niedrige Abstract‑Quote reduziert die Qualität von Stage‑2 Scoring und Coverage‑Tags (weniger echte
                Evidenz).
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Typische Muster</H>
            <UL>
              <LI>OpenAlex liefert oft mehr/ schneller; S2 kann ergänzen oder diversifizieren.</LI>
              <LI>Extrem einseitige Provider‑Verteilung kann auf Query‑Probleme oder API‑Limits hindeuten.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            These cards show how many records were actually retrieved per provider (OpenAlex vs S2), split by{" "}
            <InlineCode>intent</InlineCode> (match/authority) and by abstract availability.
          </P>
          <div className="space-y-2">
            <H>Why it matters</H>
            <UL>
              <LI>Phase D is the “volume dial”: more records → more candidates → more scoring/embedding cost.</LI>
              <LI>Low abstract share reduces Stage‑2 scoring and coverage-tag evidence quality.</LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Typical patterns</H>
            <UL>
              <LI>OpenAlex often returns more/faster; S2 may complement or diversify.</LI>
              <LI>Extreme provider imbalance can indicate query issues or API/rate-limit constraints.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "d.provider_summary": {
    title: { de: "Phase D — Provider Summary", en: "Phase D — Provider Summary" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Diese Tabelle fasst pro Provider zusammen, wie “gesund” die Retrieval‑Query‑Liste performt: Anzahl Queries,
            Fehler, Records, Zero‑Queries und einfache Verteilungsstatistiken.
          </P>
          <div className="space-y-2">
            <H>Wichtige Kennzahlen</H>
            <UL>
              <LI>
                <InlineCode>zero_q</InlineCode>/<InlineCode>zero_rate</InlineCode>: wie viele Queries liefern 0 Records.
              </LI>
              <LI>
                <InlineCode>p90</InlineCode> und <InlineCode>max</InlineCode>: zeigen “breite” Queries.
              </LI>
              <LI>
                <InlineCode>dominance</InlineCode>: Anteil der Records, der von der größten Query kommt. Heuristik:
                <span className="text-foreground"> warn ≥ 30%</span>, <span className="text-foreground"> fail ≥ 50%</span>.
                Hohe Dominanz korreliert oft mit Off‑Topic‑Pollution.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Wenn dominance hoch ist…</H>
            <UL>
              <LI>Schau in “Top 10 Queries”: welche Query dominiert?</LI>
              <LI>Queries enger machen oder mehr facet‑spezifische Queries erzeugen (Phase B/C).</LI>
              <LI>Exclusions prüfen: fehlt ein offensichtlicher Drift‑Ausschluss?</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This table summarizes how “healthy” retrieval looks per provider: query count, failures, records, zero-result
            queries, and simple distribution stats.
          </P>
          <div className="space-y-2">
            <H>Key metrics</H>
            <UL>
              <LI>
                <InlineCode>zero_q</InlineCode>/<InlineCode>zero_rate</InlineCode>: how many queries return 0 records.
              </LI>
              <LI>
                <InlineCode>p90</InlineCode> and <InlineCode>max</InlineCode>: indicate “broad” queries.
              </LI>
              <LI>
                <InlineCode>dominance</InlineCode>: share of records contributed by the single largest query. Heuristic:
                <span className="text-foreground"> warn ≥ 30%</span>, <span className="text-foreground"> fail ≥ 50%</span>.
                High dominance often correlates with off-topic pollution.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>If dominance is high…</H>
            <UL>
              <LI>Inspect “Top 10 Queries”: which query dominates?</LI>
              <LI>Tighten the broad query or add more facet-specific queries (Phase B/C).</LI>
              <LI>Review exclusions: is an obvious drift exclusion missing?</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "d.year_distribution": {
    title: { de: "Year Distribution of Retrieved Records", en: "Year Distribution of Retrieved Records" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Dieses Diagramm zeigt, aus welchen Publikationsjahren die abgerufenen Records stammen (OpenAlex vs S2). Es
            ist ein schneller Drift‑Check: Stimmen die Jahre grob mit deinem Themenfeld überein?
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>
                Ein Peak in sehr modernen Jahren ist oft ok (aktuelle Forschung), kann aber auch Drift (z. B. moderne
                Themenbegriffe) bedeuten.
              </LI>
              <LI>
                Sehr viele sehr alte Jahre können ok sein (klassische Literatur), kann aber auch auf “authority‑only”
                Query‑Bias hindeuten.
              </LI>
            </UL>
          </div>
          <P>
            Tipp: Vergleiche dieses Bild mit “Top cited but NO anchors” in Kandidaten – das ist eine starke Drift‑Kombi.
          </P>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This chart shows the publication-year distribution of retrieved records (OpenAlex vs S2). It’s a quick drift
            check: do the years broadly match your expected research landscape?
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>A strong modern-year peak can be fine (recent research) but can also signal drift.</LI>
              <LI>Very old-heavy distributions can be fine (classic literature) but may indicate an authority bias.</LI>
            </UL>
          </div>
          <P>
            Tip: cross-check with “Top cited but NO anchors” in Candidates – that combo often indicates off-topic pull.
          </P>
        </div>
      ),
    },
  },

  "d.top_bottom_queries": {
    title: { de: "Top / Bottom Queries", en: "Top / Bottom Queries" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Die “Top 10” sind Queries mit den meisten Records. Die “Bottom 10 (non‑zero)” sind die engsten Queries, die
            aber immerhin etwas liefern. Beides hilft, Query‑Breite und Balance zu verstehen.
          </P>
          <div className="space-y-2">
            <H>Was ist gut?</H>
            <UL>
              <LI>Top‑Queries sollten nicht ausschließlich aus 1–2 sehr allgemeinen Queries bestehen.</LI>
              <LI>Bottom‑Queries zeigen oft die facet‑spezifischsten Suchen – gut für Precision.</LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Red Flags</H>
            <UL>
              <LI>Top 1 Query extrem hoch → hohe Dominance → Kandidatenraum wird “einseitig”.</LI>
              <LI>Bottom‑Queries sind fast alle 1–2 Records → Queries zu eng oder falsche Operatoren.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            “Top 10” are the queries with the most records. “Bottom 10 (non-zero)” are the narrowest queries that still
            return something. Together they help you understand query breadth and balance.
          </P>
          <div className="space-y-2">
            <H>What looks good?</H>
            <UL>
              <LI>Top queries should not be dominated by 1–2 extremely general queries.</LI>
              <LI>Bottom queries are often the most facet-specific – good for precision.</LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Red flags</H>
            <UL>
              <LI>Top 1 query extremely high → high dominance → one-sided candidate universe.</LI>
              <LI>Bottom queries are mostly 1–2 records → too strict or broken operators.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "d.zero_result_queries": {
    title: { de: "Zero‑Result Queries", en: "Zero‑Result Queries" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Das sind Queries, die 0 Records geliefert haben. Sie sind nicht “schlecht” per se – aber viele Zero‑Queries
            deuten auf zu strikte Query‑Strings, falsche Sprache/Filter oder unglückliche Exclusions hin.
          </P>
          <div className="space-y-2">
            <H>Wie du damit arbeitest</H>
            <UL>
              <LI>Hover zeigt den vollständigen Query‑String – suche nach sehr langen NOT‑Listen oder seltenen Begriffen.</LI>
              <LI>Wenn viele Zero‑Queries in einer Sprache auftreten: Anchors/Begriffe für diese Sprache prüfen.</LI>
              <LI>Wenn beide Provider viele Zero‑Queries haben: Phase B (Facets/Anchors) ist oft die Ursache.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            These are queries that returned 0 records. They are not automatically “bad”, but a high number of zeros often
            means overly strict strings, wrong language/filters, or overly aggressive exclusions.
          </P>
          <div className="space-y-2">
            <H>How to use this list</H>
            <UL>
              <LI>Hover shows the full query string – look for long NOT lists or very rare terms.</LI>
              <LI>If zeros cluster in one language: review anchors/terms for that language.</LI>
              <LI>If both providers have many zeros: Phase B (facets/anchors) is often the root cause.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  // -------------------------
  // E: Kandidaten
  // -------------------------
  "e.kpis": {
    title: { de: "Kandidaten (KPIs)", en: "Candidates (KPIs)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            In Phase E werden die abgerufenen Records (Phase D) zu einem Kandidaten‑Set konsolidiert. Dabei werden
            Metadaten normalisiert (z. B. DOI, Titel, Venue, Autoren) und Duplikate über Provider/Queries hinweg
            zusammengeführt.
          </P>
          <div className="space-y-2">
            <H>Was bedeuten die KPIs?</H>
            <UL>
              <LI>
                <span className="text-foreground">Gesamt</span>: eindeutige Kandidaten nach Dedup/Merge – diese gehen
                downstream in Phase F/I.
              </LI>
              <LI>
                <span className="text-foreground">Normalized</span>: normalisierte “Roh‑Kandidaten” vor Dedup (inkl.
                Duplikate).
              </LI>
              <LI>
                <span className="text-foreground">Duplikate entfernt</span>: kollabierte Duplikate (≈{" "}
                <InlineCode>Normalized − Gesamt</InlineCode>).
              </LI>
              <LI>
                <span className="text-foreground">Merged</span>: Anzahl Merge‑Operationen, z. B. wenn OpenAlex + S2
                denselben Paper‑Record referenzieren.
              </LI>
              <LI>
                <span className="text-foreground">DOI vorhanden</span>: Kandidaten mit DOI (hilft beim Mergen und später
                beim Öffnen/Referenzieren).
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Wie interpretierst du Abweichungen?</H>
            <UL>
              <LI>
                <span className="text-foreground">Sehr viele Kandidaten</span> → Retrieval zu breit; Phase F (Embeddings)
                und Phase I (Rerank) werden teurer/langsamer.
              </LI>
              <LI>
                <span className="text-foreground">Sehr hohe Duplikat‑Quote</span> kann normal sein (Provider überlappen),
                zeigt aber auch “wasted retrieval”.
              </LI>
              <LI>
                <span className="text-foreground">Sehr wenige DOIs</span> ist in manchen Geisteswissenschaften erwartbar,
                erhöht aber das Risiko ungenauer Merges (ähnliche Titel/Editionen).
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            In Phase E, retrieved records (Phase D) are consolidated into a candidate set. Metadata is normalized (e.g.,
            DOI, title, venue, authors) and duplicates across providers/queries are merged.
          </P>
          <div className="space-y-2">
            <H>What do the KPIs mean?</H>
            <UL>
              <LI>
                <span className="text-foreground">Gesamt / Total</span>: unique candidates after dedup/merge – these proceed
                downstream into Phase F/I.
              </LI>
              <LI>
                <span className="text-foreground">Normalized</span>: normalized “raw candidates” before dedup (including
                duplicates).
              </LI>
              <LI>
                <span className="text-foreground">Duplicates removed</span>: collapsed duplicates (≈{" "}
                <InlineCode>Normalized − Total</InlineCode>).
              </LI>
              <LI>
                <span className="text-foreground">Merged</span>: number of merge operations, e.g. when OpenAlex + S2 refer
                to the same work.
              </LI>
              <LI>
                <span className="text-foreground">DOI present</span>: candidates with a DOI (helps merging and later
                linking/citation).
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>How to interpret deviations</H>
            <UL>
              <LI>
                <span className="text-foreground">Very many candidates</span> → retrieval is too broad; Phase F (embeddings)
                and Phase I (rerank) become slower and more expensive.
              </LI>
              <LI>
                <span className="text-foreground">Very high duplicate share</span> can be normal (provider overlap), but it
                also indicates wasted retrieval.
              </LI>
              <LI>
                <span className="text-foreground">Very few DOIs</span> is expected in some humanities domains, but increases
                the risk of ambiguous merges (similar titles/editions).
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "e.pool_distribution": {
    title: { de: "Pool‑Verteilung", en: "Pool Distribution" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Pools trennen Kandidaten mit Abstract (<InlineCode>with_abstract</InlineCode>) von Kandidaten ohne Abstract
            (<InlineCode>without_abstract</InlineCode>). Diese Trennung bleibt downstream strikt bestehen.
          </P>
          <div className="space-y-2">
            <H>Warum das wichtig ist</H>
            <UL>
              <LI>
                Stage‑2 Scoring (Abstract‑Chunk‑Embeddings) ist nur für <InlineCode>with_abstract</InlineCode> möglich.
              </LI>
              <LI>
                Coverage‑Tags und Rerank können für <InlineCode>without_abstract</InlineCode> weniger “Evidenz” haben →
                häufiger <InlineCode>insufficient_info</InlineCode> in Phase I.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Heuristiken</H>
            <UL>
              <LI>
                Als grobe Orientierung: Warnsignal, wenn <InlineCode>with_abstract</InlineCode> deutlich unter ~70% fällt
                (domain‑abhängig).
              </LI>
              <LI>Sehr niedrige Abstract‑Quote erklärt oft “schwache” Coverage‑Tags und noisige Reranks.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Pools separate candidates with an abstract (<InlineCode>with_abstract</InlineCode>) from those without
            (<InlineCode>without_abstract</InlineCode>). This separation is strict downstream.
          </P>
          <div className="space-y-2">
            <H>Why it matters</H>
            <UL>
              <LI>Stage‑2 scoring (abstract chunk embeddings) is only possible for <InlineCode>with_abstract</InlineCode>.</LI>
              <LI>
                Coverage tags and rerank prompts have less evidence for <InlineCode>without_abstract</InlineCode> →
                higher <InlineCode>insufficient_info</InlineCode> in Phase I.
              </LI>
            </UL>
          </div>
          <div className="space-y-2">
            <H>Heuristics</H>
            <UL>
              <LI>As a rough guide: it’s a warning sign if <InlineCode>with_abstract</InlineCode> falls far below ~70% (domain-dependent).</LI>
              <LI>Very low abstract share often explains weak coverage tags and noisy reranks.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "e.top_cited": {
    title: { de: "Top‑zitierte Kandidaten", en: "Top Cited Candidates" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Diese Liste zeigt die am stärksten zitierten Kandidaten nach Normalisierung/Dedup. Sie ist ein “Sanity Check”
            für den Kandidatenraum, nicht der finale Output.
          </P>
          <div className="space-y-2">
            <H>Wie du es liest</H>
            <UL>
              <LI>
                <span className="text-foreground">Gut:</span> viele Titel wirken “on‑topic” und passen zu Facets/Anchors.
              </LI>
              <LI>
                <span className="text-foreground">Auffällig:</span> sehr viele generische Standardwerke ohne Bezug → Query
                Drift (Phase B/C/D) oder fehlende Exclusions.
              </LI>
            </UL>
          </div>
          <P>
            Tipp: Wenn viele “Top cited” gleichzeitig in “NO Anchors” auftauchen, ist das ein starkes Off‑Topic‑Signal.
          </P>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This list shows the most-cited candidates after normalization and deduplication. It is a sanity check for the
            candidate universe, not the final output.
          </P>
          <div className="space-y-2">
            <H>How to read it</H>
            <UL>
              <LI>
                <span className="text-foreground">Good:</span> many titles look on-topic and align with facets/anchors.
              </LI>
              <LI>
                <span className="text-foreground">Suspicious:</span> many generic classics unrelated to your topic →
                query drift (Phase B/C/D) or missing exclusions.
              </LI>
            </UL>
          </div>
          <P>
            Tip: if many “Top cited” also appear in “NO anchors”, that’s a strong off-topic signal.
          </P>
        </div>
      ),
    },
  },

  "e.top_no_anchors": {
    title: { de: "Top Cited but NO Anchors", en: "Top Cited but NO Anchors" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Diese Liste ist bewusst als “Red Flag” gedacht: stark zitierte Kandidaten, die keinen Anchor‑Treffer haben.
            Das heißt nicht automatisch falsch, aber häufig deutet es auf Drift hin.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>
                Wenn viele Einträge hier auftauchen, checke Exclusions und Anchors (Phase B) sowie breite Queries (Phase D
                Top‑Queries).
              </LI>
              <LI>
                Manche Domänenbegriffe tauchen nicht in Titeln/Abstracts auf → dann ist diese Heuristik schwächer.
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This list is intentionally a “red flag”: highly cited candidates with no anchor hit. It is not automatically
            wrong, but it often indicates drift.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Many entries here → review exclusions/anchors (Phase B) and broad queries (Phase D top queries).</LI>
              <LI>In some domains, anchors may not appear in titles/abstracts → the heuristic becomes weaker.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "e.top_econ_hit": {
    title: { de: "Top Econ‑Hit Candidates", en: "Top Econ-Hit Candidates" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            “Econ‑Hit” ist eine einfache Heuristik: Wie oft tauchen globale kanonische Begriffe (Phase B Global Terms) im
            Titel/Abstract auf? Diese Liste hilft, schnell thematisch dichte Kandidaten zu sehen – aber sie ist kein
            Ranking‑Score.
          </P>
          <div className="space-y-2">
            <H>Wie du es nutzt</H>
            <UL>
              <LI>Hohe Hits + hohe Zitationen sind oft “sichere” Kandidaten.</LI>
              <LI>Hohe Hits aber off-topic Titel → Global Terms sind zu generisch.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            “Econ hit” is a simple heuristic: how often do global canonical terms (Phase B global terms) appear in the
            title/abstract? This list helps surface thematically dense candidates quickly, but it is not a ranking score.
          </P>
          <div className="space-y-2">
            <H>How to use it</H>
            <UL>
              <LI>High hits + high citations often indicate “safe” candidates.</LI>
              <LI>High hits but clearly off-topic titles → global terms are too generic.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  // -------------------------
  // F: Scoring
  // -------------------------
  "f.stage2_candidates": {
    title: { de: "Stage‑2 Candidates", en: "Stage‑2 Candidates" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Stage‑2 Candidates sind Kandidaten, die nach Stage‑1 Scoring &amp; Pruning für das teurere Abstract‑Scoring
            ausgewählt wurden. Stage‑2 nutzt Abstract‑Chunks und eine Late‑Interaction‑ähnliche Aggregation pro Facet.
          </P>
          <UL>
            <LI>0 ist möglich, aber meist ein Warnsignal: zu wenige Abstracts oder zu aggressives Pruning.</LI>
            <LI>Mehr Stage‑2 Candidates → bessere Evidenzqualität, aber höhere Embedding‑Kosten.</LI>
          </UL>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Stage‑2 candidates are those selected after Stage‑1 scoring and pruning for the expensive abstract-based
            scoring. Stage‑2 uses abstract chunks and a late-interaction-like aggregation per facet.
          </P>
          <UL>
            <LI>0 can happen, but it’s often a warning: too few abstracts or overly aggressive pruning.</LI>
            <LI>More Stage‑2 candidates → better evidence quality but higher embedding cost.</LI>
          </UL>
        </div>
      ),
    },
  },

  "f.facets_used": {
    title: { de: "Facets Used", en: "Facets Used" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Facets werden in Phase B erzeugt und definieren, welche “Aspekte” deines Themas im Scoring gesucht werden. In
            Phase F werden Facets u. a. genutzt, um Coverage‑Tags zu vergeben und Abstract‑Evidence (Stage‑2) gezielt nach
            Facet‑Bezug zu bewerten.
          </P>
          <div className="space-y-2">
            <H>Wie du es interpretierst</H>
            <UL>
              <LI>
                <span className="text-foreground">Typisch:</span> Facets Used ≈ Facets Count aus B: Planung (es werden alle
                Facets genutzt).
              </LI>
              <LI>
                <span className="text-foreground">Auffällig niedrig:</span> Facets fehlen/werden nicht genutzt → weniger
                strukturierte Coverage‑Tags, schlechtere Differenzierung.
              </LI>
              <LI>
                <span className="text-foreground">Sehr hoch:</span> kann helfen (breites Thema), kann aber auch
                verwässern, wenn viele Facets sehr ähnlich oder zu generisch sind.
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Facets are created in Phase B and define which “aspects” of your topic the scoring should look for. In Phase F
            they are used to assign coverage tags and to evaluate abstract evidence (Stage‑2) with facet-specific signals.
          </P>
          <div className="space-y-2">
            <H>How to interpret it</H>
            <UL>
              <LI>
                <span className="text-foreground">Typical:</span> Facets Used ≈ Facets Count from B: Planning (all facets
                are used).
              </LI>
              <LI>
                <span className="text-foreground">Suspiciously low:</span> facets are missing/not used → weaker coverage
                tags and less differentiation.
              </LI>
              <LI>
                <span className="text-foreground">Very high:</span> can help for broad topics, but may dilute signal if
                many facets are too similar or generic.
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "f.embedding_cost": {
    title: { de: "Kosten (Embeddings)", en: "Cost (Embeddings)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Das sind die geschätzten Kosten für Embedding‑API‑Calls in Phase F. Embeddings sind oft der größte
            Nicht‑LLM‑Kostenblock – insbesondere, wenn Stage‑2 viele Abstract‑Chunks embedden muss.
          </P>
          <div className="space-y-2">
            <H>Was treibt die Kosten?</H>
            <UL>
              <LI>Viele Kandidaten (Phase D/C zu breit) → mehr Meta‑Embeddings.</LI>
              <LI>Viele Stage‑2 Candidates + lange Abstracts → viele Chunk‑Embeddings.</LI>
              <LI>Wenig Cache‑Hits (lokal/global) → mehr echte API‑Calls.</LI>
            </UL>
          </div>
          <P>
            Hinweis: “Billiger” ist nicht immer besser – wenn Pruning zu aggressiv ist, gehen relevante Kandidaten
            verloren.
          </P>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            These are the estimated costs for embedding API calls in Phase F. Embeddings are often the largest non‑LLM
            cost block, especially when Stage‑2 has to embed many abstract chunks.
          </P>
          <div className="space-y-2">
            <H>What drives cost?</H>
            <UL>
              <LI>Many candidates (too-broad Phase C/D) → more metadata embeddings.</LI>
              <LI>Many Stage‑2 candidates + long abstracts → many chunk embeddings.</LI>
              <LI>Few cache hits (local/global) → more real API calls.</LI>
            </UL>
          </div>
          <P>Note: “cheaper” is not always better — overly aggressive pruning can remove relevant candidates.</P>
        </div>
      ),
    },
  },

  "f.stage2_scored": {
    title: { de: "Stage‑2 Scored", en: "Stage‑2 Scored" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Stage‑2 Scored ist die Anzahl der Kandidaten, die das komplette Stage‑2 Abstract‑Scoring erfolgreich
            durchlaufen haben. Idealerweise ist dieser Wert nahe an <InlineCode>Stage‑2 Candidates</InlineCode>.
          </P>
          <div className="space-y-2">
            <H>Wenn es deutlich abweicht</H>
            <UL>
              <LI>
                <span className="text-foreground">Niedriger als Stage‑2 Candidates:</span> häufig fehlende/zu kurze Abstracts
                (oder Chunking/Embedding‑Fehler).
              </LI>
              <LI>
                <span className="text-foreground">0</span> bei Stage‑2 Candidates &gt; 0 deutet meist auf einen
                Pipeline‑Fehler oder fehlende Abstract‑Verfügbarkeit hin.
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Stage‑2 Scored is the number of candidates that successfully completed the full Stage‑2 abstract scoring. In an
            ideal run, it is close to <InlineCode>Stage‑2 Candidates</InlineCode>.
          </P>
          <div className="space-y-2">
            <H>If it deviates a lot</H>
            <UL>
              <LI>
                <span className="text-foreground">Lower than Stage‑2 Candidates:</span> often missing/too short abstracts (or
                chunking/embedding failures).
              </LI>
              <LI>
                <span className="text-foreground">0</span> while Stage‑2 Candidates &gt; 0 usually indicates a pipeline error
                or missing abstract availability.
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "f.pruning_kept": {
    title: { de: "Pruning Kept", en: "Pruning Kept" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Pruning begrenzt die Anzahl der Kandidaten, die in spätere Phasen gelangen, um Kosten zu kontrollieren. “Kept”
            ist die Gesamtanzahl der behaltenen IDs über alle Lane×Pool‑Gruppen.
          </P>
          <UL>
            <LI>Zu niedrig → Gefahr, dass relevante Literatur gar nicht mehr in Rankings auftaucht.</LI>
            <LI>Zu hoch → Embedding‑/Rerank‑Kosten und Laufzeit steigen.</LI>
          </UL>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Pruning limits how many candidates proceed to later phases to control cost. “Kept” is the total number of
            retained IDs across all lane×pool groups.
          </P>
          <UL>
            <LI>Too low → relevant literature may never reach the rankings.</LI>
            <LI>Too high → embedding/rerank cost and runtime increase.</LI>
          </UL>
        </div>
      ),
    },
  },

  "f.anchor_hit_rate": {
    title: { de: "Anchor Hit Rate (Top 20)", en: "Anchor Hit Rate (Top 20)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Anchor Hit Rate ist ein schneller Relevanz‑Sanity‑Check: In den Top‑20 pro Lane/Pool wird geprüft, ob Titel
            (und je nach Pool auch Abstract) mindestens einen Primary Anchor enthalten.
          </P>
          <div className="space-y-2">
            <H>Wie du es liest</H>
            <UL>
              <LI>
                <span className="text-foreground">Hoch</span> (z. B. ≥80%) ist meist gut: Ergebnisse sind im Kern on‑topic.
              </LI>
              <LI>
                <span className="text-foreground">Niedrig</span> bedeutet nicht automatisch falsch, ist aber oft ein
                Drift‑Signal.
              </LI>
              <LI>
                <InlineCode>without_abstract</InlineCode> kann naturgemäß niedriger sein (weniger Text für Treffer).
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Anchor hit rate is a quick relevance sanity check: within the top 20 per lane/pool, we check whether the
            title (and, depending on pool, the abstract) contains at least one primary anchor.
          </P>
          <div className="space-y-2">
            <H>How to read it</H>
            <UL>
              <LI>
                <span className="text-foreground">High</span> (e.g. ≥80%) is usually good: the top results are on-topic.
              </LI>
              <LI>
                <span className="text-foreground">Low</span> is not automatically wrong but often signals drift.
              </LI>
              <LI>
                <InlineCode>without_abstract</InlineCode> can naturally be lower (less text available for hits).
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "f.lane_distributions": {
    title: { de: "Lane Distribution (Match/Authority)", en: "Lane Distribution (Match/Authority)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Diese Histogramme zeigen die Verteilung der Lane‑Scores für alle Kandidaten (getrennt nach Pool). Sie helfen
            zu erkennen, ob die Scores “trennen” können oder ob fast alles gleich bewertet wird.
          </P>
          <div className="space-y-2">
            <H>Typische Muster</H>
            <UL>
              <LI>
                <span className="text-foreground">Gesunde Trennung:</span> viele Kandidaten im unteren Bereich, wenige im
                oberen Bereich (gute Selektivität).
              </LI>
              <LI>
                <span className="text-foreground">Flach/gleichförmig:</span> kann auf schwache Facets oder zu breite
                Queries hinweisen.
              </LI>
              <LI>
                <InlineCode>without_abstract</InlineCode> ist oft “komprimierter”, weil weniger Evidenz verfügbar ist.
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            These histograms show the distribution of lane scores across all candidates (split by pool). They help you
            see whether scores meaningfully separate candidates or whether everything is scored similarly.
          </P>
          <div className="space-y-2">
            <H>Typical patterns</H>
            <UL>
              <LI>
                <span className="text-foreground">Healthy separation:</span> many candidates low, few high (selective).
              </LI>
              <LI>
                <span className="text-foreground">Flat/uniform:</span> can indicate weak facets or overly broad queries.
              </LI>
              <LI>
                <InlineCode>without_abstract</InlineCode> is often more compressed because less evidence is available.
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  // -------------------------
  // I: Rerank
  // -------------------------
  "i.tasks": {
    title: { de: "Tasks", en: "Tasks" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            <InlineCode>Tasks</InlineCode> sind die einzelnen Rerank‑Aufgaben: Kandidaten, die vom LLM bewertet werden. In
            der Regel entspricht das ungefähr <InlineCode>top‑K</InlineCode> pro Lane×Pool (z. B. 40×4 = 160), kann aber
            durch Filter/Insufficient‑Handling variieren.
          </P>
          <div className="space-y-2">
            <H>Warum ist das wichtig?</H>
            <UL>
              <LI>Mehr Tasks → mehr LLM‑Arbeit, höhere Kosten und längere Laufzeit.</LI>
              <LI>Weniger Tasks → billiger, aber weniger “LLM‑Feinsortierung” im Top‑Segment.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            <InlineCode>Tasks</InlineCode> are the individual rerank jobs: candidates that are scored by the LLM. This is
            usually close to <InlineCode>top‑K</InlineCode> per lane×pool (e.g. 40×4 = 160), but can vary due to filtering
            or insufficient handling.
          </P>
          <div className="space-y-2">
            <H>Why it matters</H>
            <UL>
              <LI>More tasks → more LLM work, higher cost, longer runtime.</LI>
              <LI>Fewer tasks → cheaper, but less LLM “fine ordering” within the top segment.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "i.calls_failures": {
    title: { de: "Calls / Failures", en: "Calls / Failures" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            <InlineCode>Calls</InlineCode> sind die tatsächlichen API‑Requests an das LLM. Tasks können gebatcht werden,
            daher gilt nicht zwingend <InlineCode>Calls = Tasks</InlineCode>. <InlineCode>Failures</InlineCode> zählen
            fehlgeschlagene Requests/Antworten (z. B. Timeout, Rate‑Limit, Parsing‑Fehler).
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Ein paar Failures sind in der Praxis manchmal unvermeidbar (Netz/Provider).</LI>
              <LI>Viele Failures → Concurrency zu hoch, Budget‑Stop greift, Prompt/Output ist instabil.</LI>
              <LI>Wenn Failures auftreten, kann die Rerank‑Abdeckung unvollständig sein (einige Kandidaten ohne LLM‑Score).</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            <InlineCode>Calls</InlineCode> are the actual API requests sent to the LLM. Tasks may be batched, so{" "}
            <InlineCode>Calls ≠ Tasks</InlineCode> is possible. <InlineCode>Failures</InlineCode> counts failed requests or
            responses (timeouts, rate limits, parsing errors).
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>A few failures can happen in real systems (network/provider).</LI>
              <LI>Many failures → concurrency too high, budget stop triggered, or prompt/output instability.</LI>
              <LI>If failures occur, rerank coverage may be incomplete (some candidates without an LLM score).</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "i.cost": {
    title: { de: "Kosten (Rerank)", en: "Cost (Rerank)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Das sind die Kosten der Rerank‑Phase (LLM). Sie hängen vor allem von <InlineCode>Tasks</InlineCode>, der
            Prompt‑Länge (z. B. Coverage‑Tags/Rationales) und dem Modell ab.
          </P>
          <div className="space-y-2">
            <H>Heuristik</H>
            <UL>
              <LI>Wenn Rerank deutlich teurer wird als erwartet, prüfe: Tasks‑Anzahl, sehr lange Rationales, zu hohes Modell.</LI>
              <LI>Hohe Kosten bei gleichzeitig vielen <InlineCode>insufficient_info</InlineCode> → Evidenz fehlt; mehr LLM hilft dann oft nicht.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This is the cost of the rerank phase (LLM). It depends mainly on <InlineCode>Tasks</InlineCode>, prompt length
            (e.g., coverage tags/rationales), and the chosen model.
          </P>
          <div className="space-y-2">
            <H>Rule of thumb</H>
            <UL>
              <LI>If rerank becomes much more expensive than expected, check: task count, very long rationales, too large model.</LI>
              <LI>High cost plus many <InlineCode>insufficient_info</InlineCode> often means missing evidence; “more LLM” may not fix it.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "i.latency_p50": {
    title: { de: "p50 Latency", en: "p50 Latency" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            <InlineCode>p50 Latency</InlineCode> ist die mediane Laufzeit pro LLM‑Call in der Rerank‑Phase. Sie ist ein
            guter Indikator dafür, ob das System gerade “gesund” arbeitet (Modell‑Latency, Netzwerk, Rate‑Limits).
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Steigt p50 stark an, dauert die gesamte Pipeline länger – besonders bei vielen Calls.</LI>
              <LI>Sehr hohe p50 + viele Failures → häufig Rate‑Limit/Backpressure oder zu hohe Concurrency.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            <InlineCode>p50 Latency</InlineCode> is the median duration per LLM call in the rerank phase. It’s a useful
            health signal for model latency, network conditions, and rate limiting.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>If p50 increases, the whole run becomes slower — especially with many calls.</LI>
              <LI>Very high p50 plus many failures often indicates rate limits/backpressure or too much concurrency.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "i.token_usage": {
    title: { de: "Token Usage", en: "Token Usage" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Token‑Usage zeigt die Summe aller Input‑ und Output‑Tokens in Phase I. Tokens sind die direkte Grundlage für
            LLM‑Kosten: <InlineCode>Input</InlineCode> (Prompt + Kandidaten‑Evidenz) und <InlineCode>Output</InlineCode>{" "}
            (Score + rationale/JSON).
          </P>
          <div className="space-y-2">
            <H>Worauf achten?</H>
            <UL>
              <LI>Sehr hohe Input‑Tokens → Evidence pro Task ist zu lang (z. B. zu viele Coverage‑Tags oder lange Abstract‑Snippets).</LI>
              <LI>Sehr hohe Output‑Tokens → Rationale zu lang/zu “gesprächig”; kürzere Output‑Schemas sparen Kosten.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Token usage shows total input and output tokens in Phase I. Tokens are the direct driver of LLM cost:{" "}
            <InlineCode>Input</InlineCode> (prompt + candidate evidence) and <InlineCode>Output</InlineCode> (score +
            rationale/JSON).
          </P>
          <div className="space-y-2">
            <H>What to watch</H>
            <UL>
              <LI>Very high input tokens → evidence per task is too long (too many tags or long abstract snippets).</LI>
              <LI>Very high output tokens → rationales are too verbose; tighter output schemas reduce cost.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "i.insufficient": {
    title: { de: "Insufficient", en: "Insufficient" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            <InlineCode>insufficient_info</InlineCode> ist eine Ehrlichkeits‑Flag des Rerankers: wenn nicht genug Evidenz
            vorhanden ist, soll der Reranker das explizit markieren (besonders im Pool{" "}
            <InlineCode>without_abstract</InlineCode>).
          </P>
          <div className="space-y-2">
            <H>Wie du es interpretierst</H>
            <UL>
              <LI>
                Viele Insufficient‑Fälle in <InlineCode>without_abstract</InlineCode> sind erwartbar.
              </LI>
              <LI>
                Viele Insufficient‑Fälle auch in <InlineCode>with_abstract</InlineCode> können auf schwache Coverage‑Tags
                oder zu wenig Stage‑2 Evidence hindeuten.
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            <InlineCode>insufficient_info</InlineCode> is the reranker’s honesty flag: if there is not enough evidence, it
            should explicitly mark the result as insufficient (especially for the{" "}
            <InlineCode>without_abstract</InlineCode> pool).
          </P>
          <div className="space-y-2">
            <H>How to interpret it</H>
            <UL>
              <LI>Many insufficient cases in <InlineCode>without_abstract</InlineCode> are expected.</LI>
              <LI>
                Many insufficient cases even in <InlineCode>with_abstract</InlineCode> can indicate weak coverage tags or
                too little Stage‑2 evidence.
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "i.score_distribution": {
    title: { de: "LLM Score Distribution (0–100)", en: "LLM Score Distribution (0–100)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Die Verteilung der Rerank‑Scores (<InlineCode>0–100</InlineCode>) für die top‑K Kandidaten pro Lane/Pool.
            Wichtig: Rerank beeinflusst nur die Reihenfolge im Top‑Segment; es ist kein globales Rescoring aller Kandidaten.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>
                Wenn fast alle Scores sehr hoch sind, kann der Prompt zu wenig differenzieren oder die Kandidaten sind
                sehr ähnlich.
              </LI>
              <LI>
                Wenn Scores sehr niedrig + viele <InlineCode>insufficient_info</InlineCode>, fehlt oft Evidenz
                (Coverage‑Tags / Abstracts).
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Distribution of rerank scores (<InlineCode>0–100</InlineCode>) for the top‑K candidates per lane/pool. Note:
            rerank only changes ordering within the top segment; it does not rescore the entire candidate universe.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>If almost all scores are very high, the prompt may not differentiate well or candidates are too similar.</LI>
              <LI>
                Low scores + many <InlineCode>insufficient_info</InlineCode> usually indicate missing evidence (coverage tags / abstracts).
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  // -------------------------
  // Bericht (last)
  // -------------------------
  "report.records_total": {
    title: { de: "Records abgerufen", en: "Records Retrieved" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            <InlineCode>Records abgerufen</InlineCode> ist die Anzahl der Provider‑Treffer aus Phase D (OpenAlex + Semantic
            Scholar) – noch vor Normalisierung und Dedup in Phase E. Wichtig: Das sind keine “unique papers”; ein Paper kann
            mehrfach vorkommen (mehrere Queries, beide Provider, Varianten).
          </P>
          <div className="space-y-2">
            <H>Wie du es interpretierst</H>
            <UL>
              <LI>
                <span className="text-foreground">Sehr hoch</span> → Retrieval ist breit; gut für Recall, aber mehr Compute
                und mehr Dedup‑Arbeit in Phase E/F.
              </LI>
              <LI>
                <span className="text-foreground">Sehr niedrig</span> → Queries sind zu eng oder viele Zero‑Result Queries.
              </LI>
              <LI>Wenn ein Provider fast alles liefert, ist dein Ergebnis‑Set stark von dessen Coverage abhängig.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            <InlineCode>Records retrieved</InlineCode> is the number of provider hits from Phase D (OpenAlex + Semantic
            Scholar) before normalization and dedup in Phase E. Important: these are not unique papers; a work can appear
            multiple times (multiple queries, both providers, variants).
          </P>
          <div className="space-y-2">
            <H>How to interpret it</H>
            <UL>
              <LI>
                <span className="text-foreground">Very high</span> → retrieval is broad; good for recall, but more compute
                and dedup work in Phase E/F.
              </LI>
              <LI>
                <span className="text-foreground">Very low</span> → queries are too strict or many zero-result queries.
              </LI>
              <LI>If one provider contributes almost everything, your result set depends heavily on that provider’s coverage.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.candidates_total": {
    title: { de: "Kandidaten", en: "Candidates" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            <InlineCode>Kandidaten</InlineCode> ist die Anzahl eindeutiger Kandidaten nach Phase E (Normalisierung + Dedup +
            Merge). Das ist die Menge, die Phase F (Scoring) als “Universum” betrachtet – und damit ein zentraler
            Kosten‑/Laufzeit‑Treiber.
          </P>
          <div className="space-y-2">
            <H>Gute vs. auffällige Werte</H>
            <UL>
              <LI>
                <span className="text-foreground">Zu viele Kandidaten</span> → oft breite Queries/Exclusions zu schwach. Das
                erhöht Kosten in F/I.
              </LI>
              <LI>
                <span className="text-foreground">Zu wenige Kandidaten</span> → Gefahr, dass relevante Literatur fehlt (zu
                enge Anchors/Filters).
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            <InlineCode>Candidates</InlineCode> is the number of unique candidates after Phase E (normalization + dedup +
            merge). This is the universe that Phase F (scoring) operates on — and a key driver of runtime and cost.
          </P>
          <div className="space-y-2">
            <H>Good vs. suspicious values</H>
            <UL>
              <LI>
                <span className="text-foreground">Too many candidates</span> → often broad queries or weak exclusions; Phase
                F/I becomes more expensive.
              </LI>
              <LI>
                <span className="text-foreground">Too few candidates</span> → risk of missing relevant literature (anchors/filters too strict).
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.facets_count": {
    title: { de: "Facetten", en: "Facets" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            <InlineCode>Facetten</InlineCode> sind die thematischen “Dimensionen” aus B: Planung. Jede Facet hat Labels,
            Canonical Terms, Neighbor Terms und Exclusions. Downstream werden Facets genutzt, um Coverage‑Tags zu vergeben
            und Abstract‑Evidence gezielt zu bewerten.
          </P>
          <div className="space-y-2">
            <H>Wie du es interpretierst</H>
            <UL>
              <LI>Zu wenige Facetten → Thema ist zu grob modelliert; Scoring differenziert schlechter.</LI>
              <LI>Zu viele Facetten → kann helfen, aber auch verwässern, wenn viele Facets sehr ähnlich/generisch sind.</LI>
              <LI>Wenn Facets “falsch” sind, ziehen sie Queries (C/D) und Scoring (F) gemeinsam off-topic.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            <InlineCode>Facets</InlineCode> are the thematic “dimensions” created in B: Planning. Each facet has labels,
            canonical terms, neighbor terms, and exclusions. Downstream, facets drive coverage tags and facet-specific
            abstract evidence scoring.
          </P>
          <div className="space-y-2">
            <H>How to interpret it</H>
            <UL>
              <LI>Too few facets → the topic is modeled too coarsely; scoring differentiates less.</LI>
              <LI>Too many facets → can help, but may dilute signal if many facets are generic/overlapping.</LI>
              <LI>If facets are off, they can pull both queries (C/D) and scoring (F) off-topic.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.queries_total": {
    title: { de: "Queries", en: "Queries" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            <InlineCode>Queries</InlineCode> ist die Summe aller generierten Suchstrings in Phase C (OpenAlex + Semantic
            Scholar), über Lane (match/authority) und Sprachen hinweg. Queries sind der Hebel für Recall vs. Precision im
            Retrieval.
          </P>
          <div className="space-y-2">
            <H>Heuristik</H>
            <UL>
              <LI>Mehr Queries → breiterer Recall, aber mehr Overlap/Duplikate möglich.</LI>
              <LI>Weniger Queries → schneller/gezielter, aber Risiko, Sub‑Themen zu verpassen.</LI>
              <LI>Viele Zero‑Result Queries sprechen oft für zu strikte Anchors/Exclusions oder falsche Sprache/Filter.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            <InlineCode>Queries</InlineCode> is the total number of query strings generated in Phase C (OpenAlex + Semantic
            Scholar), across lanes (match/authority) and languages. Queries are the main lever for recall vs. precision in
            retrieval.
          </P>
          <div className="space-y-2">
            <H>Rule of thumb</H>
            <UL>
              <LI>More queries → broader recall, but more overlap/duplicates.</LI>
              <LI>Fewer queries → faster and more focused, but risk missing sub-topics.</LI>
              <LI>Many zero-result queries often indicate overly strict anchors/exclusions or wrong language/filters.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.publication_year": {
    title: { de: "Publication Year (Ranked IDs)", en: "Publication Year (Ranked IDs)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Diese Verteilung zeigt, aus welchen Publikationsjahren die (gerankten) Top‑K Kandidaten stammen. Sie ist ein
            schneller Check, ob die Pipeline zeitlich in einem plausiblen Bereich landet – oder ob z. B. modernere
            Sekundärliteratur alles dominiert.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Erwartbar ist eine Mischung, die zu deinem Thema passt (Epoche, Datenlage, Fach).</LI>
              <LI>Wenn fast alles extrem aktuell ist, sind Queries oft zu “modern” formuliert oder Provider‑Coverage verzerrt.</LI>
              <LI>Wenn sehr viele Jahre fehlen, können Metadaten (year) unvollständig sein – dann ist der Plot weniger aussagekräftig.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This distribution shows which publication years the ranked top-K candidates come from. It’s a quick sanity
            check for temporal plausibility — e.g., whether modern secondary literature dominates unexpectedly.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>You expect a mix that fits your topic (period, data availability, field norms).</LI>
              <LI>If almost everything is very recent, queries may be phrased too “modern” or provider coverage is biased.</LI>
              <LI>If many years are missing, metadata may be incomplete — making the plot less informative.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.citations_log10": {
    title: { de: "Citations (log10(1+cites))", en: "Citations (log10(1+cites))" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Zitationen haben eine starke Long‑Tail‑Verteilung. Deshalb wird hier <InlineCode>log10(1 + cites)</InlineCode>{" "}
            geplottet: so sind “10 vs 100 vs 1000 Zitationen” besser vergleichbar. Der Plot hilft zu sehen, ob die Top‑K
            eher aus “klassischen” Autoritäts‑Papers oder aus wenig zitierten Nischen‑Papers bestehen.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Ein gesundes Bild hat oft sowohl mittlere als auch hohe Zitations‑Bins.</LI>
              <LI>Wenn alles extrem hoch ist, dominiert “Authority”; prüfe Drift‑Signale (NO Anchors, Match vs Authority).</LI>
              <LI>Wenn alles sehr niedrig ist, kann das Thema sehr neu/nischig sein – oder Citation‑Metadaten fehlen.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Citations follow a heavy long-tail distribution. That’s why we plot <InlineCode>log10(1 + cites)</InlineCode>:
            it makes “10 vs 100 vs 1000 citations” comparable. This chart helps you see whether the top-K is dominated by
            classic authority papers or low-citation niche work.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>A healthy picture often contains both mid and high citation bins.</LI>
              <LI>If everything is extremely high, “authority” may dominate; review drift signals (NO anchors, Match vs Authority).</LI>
              <LI>If everything is very low, the topic may be new/niche — or citation metadata might be missing.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.coverage_tags_count": {
    title: { de: "Coverage Tags Count", en: "Coverage Tags Count" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Coverage‑Tags sind Facet‑Labels, für die ein Kandidat starke Evidenz zeigt (Titel/Abstract/Facet‑Scoring). Dieser
            Plot zeigt, wie viele Tags Kandidaten typischerweise haben.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Mehr Tags → Kandidat deckt mehrere Facets ab (breiter), kann aber auch “zu generisch” sein.</LI>
              <LI>Sehr wenige Tags → Kandidat hat wenig strukturierte Evidenz; Rerank kann häufiger <InlineCode>insufficient_info</InlineCode> setzen.</LI>
              <LI>Wenn fast alle Kandidaten sehr viele Tags haben, sind Facets/Terms vermutlich zu unspezifisch.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Coverage tags are facet labels for which a candidate shows strong evidence (title/abstract/facet scoring). This
            plot shows how many tags candidates typically receive.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>More tags → broader coverage, but can also indicate overly generic candidates.</LI>
              <LI>Very few tags → weak structured evidence; rerank may mark more items as <InlineCode>insufficient_info</InlineCode>.</LI>
              <LI>If almost all candidates have very many tags, facets/terms may be too unspecific.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.llm_score_distribution": {
    title: { de: "LLM Rerank Score Distribution", en: "LLM Rerank Score Distribution" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Die Verteilung der Rerank‑Scores (<InlineCode>0–100</InlineCode>) für die rerankten Kandidaten. Der Plot zeigt,
            ob das LLM im Top‑Segment fein differenziert oder alles “gleich gut” bewertet.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Viele sehr hohe Scores → Prompt differenziert evtl. zu wenig oder Kandidaten sind sehr ähnlich.</LI>
              <LI>Viele niedrige Scores + viele <InlineCode>insufficient_info</InlineCode> → Evidenz/Tags sind schwach.</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Distribution of rerank scores (<InlineCode>0–100</InlineCode>) for reranked candidates. It shows whether the
            LLM meaningfully differentiates within the top segment or scores everything as “equally good”.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Many very high scores → prompt may not differentiate enough or candidates are very similar.</LI>
              <LI>Many low scores + many <InlineCode>insufficient_info</InlineCode> → weak evidence/tags.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.match_lane_distribution": {
    title: { de: "Match Lane Distribution", en: "Match Lane Distribution" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Der Match‑Lane‑Score ist das “Relevanz‑Signal” der Pipeline (0..1). Diese Verteilung zeigt, ob die Pipeline im
            Kandidaten‑Universum viele stark relevante Items findet oder ob die Scores eher flach/low sind.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Rechts‑lastig (viele hohe Scores) ist oft gut: Retrieval + Scoring sind on-topic.</LI>
              <LI>Sehr flach oder links‑lastig → häufig Query‑Drift oder Facets/Anchors zu generisch.</LI>
              <LI><InlineCode>without_abstract</InlineCode> ist oft niedriger/noisiger (weniger Text‑Evidenz).</LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            The match lane score is the pipeline’s core “relevance” signal (0..1). This distribution shows whether the
            pipeline finds many strongly relevant items or whether scores are flat/low.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>Right-skewed (many high scores) is often good: retrieval + scoring are on-topic.</LI>
              <LI>Very flat or left-skewed → often query drift or facets/anchors too generic.</LI>
              <LI><InlineCode>without_abstract</InlineCode> is typically lower/noisier due to less text evidence.</LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.coverage_tags_top": {
    title: { de: "Coverage Tags (Top Facets)", en: "Coverage Tags (Top Facets)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Dieser Plot zeigt die am häufigsten vergebenen Coverage‑Tags (Facets) in den Top‑Listen. Er beantwortet: “Welche
            Facets treiben meine Top‑Ergebnisse?”.
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>
                <span className="text-foreground">Gut:</span> die Top‑Tags passen zu deiner Kapitel‑Fragestellung und sind
                nicht nur generische “Hintergrund”‑Facets.
              </LI>
              <LI>
                <span className="text-foreground">Auffällig:</span> ein einzelnes irrelevantes Tag dominiert → Facets/Terms
                in Phase B prüfen (und Query‑Plan in Phase C).
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This chart shows the most frequently assigned coverage tags (facets) in the top lists. It answers: “Which
            facets drive my top results?”
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>
                <span className="text-foreground">Good:</span> top tags align with your research question, not just generic
                background facets.
              </LI>
              <LI>
                <span className="text-foreground">Suspicious:</span> one irrelevant tag dominates → review facets/terms in
                Phase B (and query plan in Phase C).
              </LI>
            </UL>
          </div>
        </div>
      ),
    },
  },

  "report.llm_vs_lane": {
    title: { de: "LLM Score vs Lane Score", en: "LLM Score vs Lane Score" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Dieses Scatter‑Plot zeigt für rerankte Kandidaten den Zusammenhang zwischen dem Pipeline‑Lane‑Score (x‑Achse)
            und dem LLM‑Rerank‑Score (y‑Achse). Idealerweise stimmt die grobe Ordnung überein – aber der Reranker darf
            begründet umsortieren.
          </P>
          <div className="space-y-2">
            <H>Wie du es liest</H>
            <UL>
              <LI>
                <span className="text-foreground">Positive Tendenz</span>: LLM bestätigt die Pipeline‑Sortierung grob.
              </LI>
              <LI>
                <span className="text-foreground">Wilde Streuung</span>: LLM disagrees stark – kann heißen: Coverage‑Tags
                zeigen andere Evidenz als Embedding‑Scores vermuten lassen.
              </LI>
              <LI>
                <InlineCode>without_abstract</InlineCode> ist oft tiefer/noisiger, weil Evidenz fehlt und das LLM häufiger{" "}
                <InlineCode>insufficient_info</InlineCode> setzt.
              </LI>
            </UL>
          </div>
          <P>
            Wichtig: Ein perfekter diagonal‑Trend ist nicht unbedingt das Ziel – der Reranker soll inhaltlich korrigieren,
            nicht nur kopieren.
          </P>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This scatter plot shows, for reranked candidates, the relationship between the pipeline lane score (x-axis)
            and the LLM rerank score (y-axis). Ideally the coarse ordering aligns, while the reranker may still
            legitimately reshuffle based on evidence.
          </P>
          <div className="space-y-2">
            <H>How to read it</H>
            <UL>
              <LI>
                <span className="text-foreground">Positive trend</span>: the LLM broadly agrees with the pipeline ordering.
              </LI>
              <LI>
                <span className="text-foreground">Very noisy scatter</span>: strong disagreement – can mean coverage tags
                provide evidence that contradicts embedding-based scores.
              </LI>
              <LI>
                <InlineCode>without_abstract</InlineCode> often looks lower/noisier due to missing evidence and more{" "}
                <InlineCode>insufficient_info</InlineCode>.
              </LI>
            </UL>
          </div>
          <P>Note: a perfectly diagonal pattern is not necessarily the goal – rerank should correct, not just copy.</P>
        </div>
      ),
    },
    images: [
      {
        src: "/pipeline-help/llm_vs_lane_positive.svg",
        alt: "Example: positive relationship between lane score and llm score",
        caption: {
          de: "Beispiel A: grob positive Beziehung – Rerank bestätigt die Pipeline‑Sortierung.",
          en: "Example A: broadly positive relationship – rerank mostly confirms the pipeline ordering.",
        },
      },
      {
        src: "/pipeline-help/llm_vs_lane_flat.svg",
        alt: "Example: no clear relationship",
        caption: {
          de: "Beispiel B: kaum Zusammenhang – LLM unterscheidet anders (oder Evidenz ist schwach).",
          en: "Example B: little relationship – the LLM differentiates differently (or evidence is weak).",
        },
      },
      {
        src: "/pipeline-help/llm_vs_lane_pool_gap.svg",
        alt: "Example: pool gap pattern",
        caption: {
          de: "Beispiel C: Pool‑Gap – with_abstract stabiler, without_abstract tiefer/noisiger.",
          en: "Example C: pool gap – with_abstract more stable, without_abstract lower/noisier.",
        },
      },
    ],
  },

  "report.match_vs_authority": {
    title: { de: "Match vs Authority (Top 500)", en: "Match vs Authority (Top 500)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Dieser Plot zeigt für die Top‑500 (nach <InlineCode>match_lane</InlineCode>) den Zusammenhang von{" "}
            <InlineCode>match</InlineCode> (x) und <InlineCode>authority</InlineCode> (y). Er hilft, “relevant aber low
            authority” vs “high authority aber drift‑gefährdet” zu erkennen.
          </P>
          {lanesPools.de}
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>
                Viele Punkte mit <InlineCode>authority</InlineCode> hoch, <InlineCode>match</InlineCode> niedrig → Gefahr:
                hoch zitierte Off‑Topic Literatur dominiert.
              </LI>
              <LI>
                Punktewolke mit ordentlicher <InlineCode>match</InlineCode>‑Basis ist oft gesund (relevante Kandidaten).
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            This plot shows, for the top 500 (by <InlineCode>match_lane</InlineCode>), the relationship between{" "}
            <InlineCode>match</InlineCode> (x) and <InlineCode>authority</InlineCode> (y). It helps distinguish “relevant
            but low authority” from “high authority but drift-prone”.
          </P>
          {lanesPools.en}
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>
                Many points with high <InlineCode>authority</InlineCode> but low <InlineCode>match</InlineCode> → risk:
                classic, highly cited off-topic literature dominates.
              </LI>
              <LI>A cloud with a solid match baseline is often healthy (relevant candidates).</LI>
            </UL>
          </div>
        </div>
      ),
    },
    images: [
      {
        src: "/pipeline-help/match_vs_authority_balanced.svg",
        alt: "Example: balanced match and authority",
        caption: {
          de: "Beispiel A: Balanced – viele Kandidaten haben sowohl Match als auch Authority‑Signal.",
          en: "Example A: balanced – many candidates show both match and authority signal.",
        },
      },
      {
        src: "/pipeline-help/match_vs_authority_offtopic.svg",
        alt: "Example: high authority low match cluster",
        caption: {
          de: "Beispiel B: Authority‑Cluster bei niedrigem Match – oft Off‑Topic‑Risiko.",
          en: "Example B: authority-heavy cluster at low match – often an off-topic risk.",
        },
      },
    ],
  },

  "report.lane_score_by_rank": {
    title: { de: "Lane Score by Rank (Top 200)", en: "Lane Score by Rank (Top 200)" },
    body: {
      de: (
        <div className="space-y-3">
          <P>
            Zeigt, wie schnell der Lane‑Score in den Top‑Ranks abfällt. Das ist ein “Trennschärfe‑Plot”: Kann die Pipeline
            die Top‑K wirklich unterscheiden, oder sind viele Kandidaten praktisch gleich gut?
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>
                <span className="text-foreground">Sanfter Abfall</span> ist normal.
              </LI>
              <LI>
                <span className="text-foreground">Lange Plateaus</span> können bedeuten: Scores saturieren, Facets sind zu
                ähnlich, oder Queries sind zu breit (viele ähnliche Kandidaten).
              </LI>
              <LI>
                Starker Gap zwischen Pools kann auf Evidenz‑Unterschiede (Abstract) oder unterschiedliche Thresholds
                zurückgehen.
              </LI>
            </UL>
          </div>
        </div>
      ),
      en: (
        <div className="space-y-3">
          <P>
            Shows how quickly the lane score drops across the top ranks. Think of it as a “separation” plot: does the
            pipeline meaningfully separate the top-K, or are many candidates scored almost equally?
          </P>
          <div className="space-y-2">
            <H>Interpretation</H>
            <UL>
              <LI>A smooth decline is normal.</LI>
              <LI>
                Long plateaus can mean scores saturate, facets are too similar, or queries are too broad (many very
                similar candidates).
              </LI>
              <LI>A large gap between pools can reflect evidence differences (abstract availability) and thresholds.</LI>
            </UL>
          </div>
        </div>
      ),
    },
    images: [
      {
        src: "/pipeline-help/lane_score_by_rank_smooth.svg",
        alt: "Example: smooth decay",
        caption: {
          de: "Beispiel A: Smooth decay – typische Trennschärfe.",
          en: "Example A: smooth decay – typical separation.",
        },
      },
      {
        src: "/pipeline-help/lane_score_by_rank_plateau.svg",
        alt: "Example: plateau",
        caption: {
          de: "Beispiel B: Plateau – viele Kandidaten haben sehr ähnliche Scores.",
          en: "Example B: plateau – many candidates have very similar scores.",
        },
      },
    ],
  },
};
