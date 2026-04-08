"""
Regression checks for the two-lane query-builder lint behavior.

This script is intentionally standalone and assertion-based so it can run in CI or locally
without requiring a pytest setup.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.two_lane_sources.pipeline import (
    AuthorityBlueprint,
    BilingualTerms,
    Facet,
    OpenAlexQuery,
    QueryPlan,
    S2BulkQuery,
    _normalize_openalex_query,
    _normalize_s2_query,
    _repair_query_plan,
    _validate_match_core_object_presence,
    _validate_openalex_anchor_presence,
    _validate_openalex_match_anchor_fingerprint_diversity,
    _validate_s2_advanced_syntax_budget,
    _validate_s2_match_required_group_budget,
    diagnose_query_plan,
)


PIPELINE_PATH = BACKEND_ROOT / "services" / "two_lane_sources" / "pipeline.py"


def _make_plan() -> QueryPlan:
    return QueryPlan(
        topic_summary_en="Automation of financial document analysis",
        topic_summary_de="Automatisierung der Analyse von Finanzdokumenten",
        primary_context_anchors=BilingualTerms(
            en=["balance sheet", "BWA", "market follow up", "bank back office", "LLM"],
            de=["Bilanzen", "BWA", "Marktfolge", "Dokumentenanalyse", "LLM"],
        ),
        core_object_terms=BilingualTerms(
            en=["balance sheet", "BWA", "financial contract", "financial statement"],
            de=["Bilanz", "Bilanzen", "BWA", "Verträge"],
        ),
        must_keep_constraints=[],
        drift_risks=[],
        authority_blueprints=[],
        facets=[],
        global_canonical_terms=BilingualTerms(en=[], de=[]),
        global_exclusions=BilingualTerms(en=[], de=[]),
    )


def _buggy_fingerprint_passes(queries: list[OpenAlexQuery], plan: QueryPlan, *, max_share: float = 0.60) -> bool:
    for lang in ("en", "de"):
        anchors = [anchor for anchor in getattr(plan.primary_context_anchors, lang, []) if str(anchor or "").strip()]
        match_qs = [query for query in queries if query.intent == "match" and query.language == lang]
        if len(match_qs) < 4:
            continue

        counts: Counter[tuple[str, str]] = Counter()
        eligible = 0
        for query in match_qs:
            hits = [anchor for anchor in anchors if str(anchor).casefold() in str(query.query_string or "").casefold()]
            top2 = tuple(str(hit).lower() for hit in hits[:2])
            if len(top2) < 2:
                continue
            counts[top2] += 1
            eligible += 1

        if eligible < 4 or not counts:
            continue
        _fp, count = counts.most_common(1)[0]
        if (count / max(eligible, 1)) > float(max_share):
            return False
    return True


def _relevant_duplicate_functions() -> dict[str, list[int]]:
    tree = ast.parse(PIPELINE_PATH.read_text(encoding="utf-8"))
    defs: dict[str, list[int]] = defaultdict(list)
    relevant = {
        "_normalize_openalex_query",
        "_normalize_s2_query",
        "_find_anchor_terms_in_text",
        "_validate_openalex_anchor_presence",
        "_validate_s2_anchor_presence",
        "_validate_openalex_match_anchor_fingerprint_diversity",
    }
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in relevant:
            defs[node.name].append(int(node.lineno))
    return {name: lines for name, lines in defs.items() if len(lines) > 1}


def test_openalex_fingerprint_ignores_always_on_object_anchors() -> None:
    plan = _make_plan()
    queries = [
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("balance sheet" OR "BWA") AND ("time savings" OR "processing time")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="EN outcomes",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("balance sheet" OR "BWA" OR "financial contract") AND ("annual statement" OR "contract text")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="EN object variants",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("balance sheet" OR "BWA" OR "financial contract") AND ("market follow up" OR "loan monitoring")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="EN workflow",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("balance sheet" OR "BWA" OR "financial contract") AND ("OCR" OR "table extraction" OR "LLM")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="EN methods",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="de",
                search_field="title_and_abstract.search",
                query_string='("Bilanz" OR "Bilanzen" OR "BWA") AND ("Zeitersparnis" OR "Verarbeitungszeit")',
                filters="is_paratext:false,is_retracted:false,language:de",
                sort="relevance_score:desc",
                per_page=200,
                notes="DE outcomes",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="de",
                search_field="title_and_abstract.search",
                query_string='("Bilanz" OR "Bilanzen" OR "BWA" OR "Verträge") AND ("Marktfolge" OR "Backoffice")',
                filters="is_paratext:false,is_retracted:false,language:de",
                sort="relevance_score:desc",
                per_page=200,
                notes="DE workflow",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="de",
                search_field="title_and_abstract.search",
                query_string='("Bilanz" OR "Bilanzen" OR "BWA" OR "Verträge") AND ("Dokumentenanalyse" OR "LLM")',
                filters="is_paratext:false,is_retracted:false,language:de",
                sort="relevance_score:desc",
                per_page=200,
                notes="DE methods",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="de",
                search_field="title_and_abstract.search",
                query_string='("Bilanz" OR "Bilanzen" OR "BWA") AND ("Jahresabschluss" OR "Vertragstext")',
                filters="is_paratext:false,is_retracted:false,language:de",
                sort="relevance_score:desc",
                per_page=200,
                notes="DE object variants",
            )
        ),
    ]

    assert _buggy_fingerprint_passes(queries, plan) is False
    _validate_openalex_match_anchor_fingerprint_diversity(queries, plan=plan)


def test_openalex_fingerprint_still_fails_for_true_low_diversity() -> None:
    plan = _make_plan()
    queries = []
    for lang, obj_term, pair_a, pair_b, alt_term in (
        ("en", "balance sheet", "market follow up", "bank back office", "LLM"),
        ("de", "Bilanz", "Marktfolge", "Dokumentenanalyse", "LLM"),
    ):
        for idx in range(5):
            variable_clause = (
                f'("{pair_a}" OR "{pair_b}")'
                if idx < 4
                else f'("{alt_term}" OR "OCR")'
            )
            queries.append(
                _normalize_openalex_query(
                    OpenAlexQuery(
                        intent="match",
                        language=lang,
                        search_field="title_and_abstract.search",
                        query_string=(
                            f'("{obj_term}" OR "BWA") AND '
                            f"{variable_clause} AND "
                            f'("time savings" OR "OCR" OR "LLM" OR "processing time" OR "Zeitersparnis")'
                        ),
                        filters=f"is_paratext:false,is_retracted:false,language:{lang}",
                        sort="relevance_score:desc",
                        per_page=200,
                        notes=f"Low diversity {lang} {idx}",
                    )
                )
            )

    try:
        _validate_openalex_match_anchor_fingerprint_diversity(queries, plan=plan)
    except ValueError as exc:
        assert "anchor fingerprint concentration too high" in str(exc)
    else:
        raise AssertionError("Expected low-diversity queries to fail the OpenAlex fingerprint validator")


def test_match_core_object_presence_still_enforced() -> None:
    plan = _make_plan()
    bad_query = _normalize_openalex_query(
        OpenAlexQuery(
            intent="match",
            language="en",
            search_field="title_and_abstract.search",
            query_string='("market follow up" OR "bank back office") AND ("OCR" OR "LLM" OR "processing time")',
            filters="is_paratext:false,is_retracted:false,language:en",
            sort="relevance_score:desc",
            per_page=200,
            notes="No core object term",
        )
    )

    try:
        _validate_match_core_object_presence([bad_query], plan=plan, provider="OpenAlex")
    except ValueError as exc:
        assert "match query missing core object term" in str(exc)
    else:
        raise AssertionError("Expected missing core object term to be rejected")


def test_openalex_match_anchor_presence_accepts_core_object_fallback() -> None:
    plan = QueryPlan(
        topic_summary_en="Automation of financial document analysis",
        topic_summary_de="Automatisierung der Analyse von Finanzdokumenten",
        primary_context_anchors=BilingualTerms(
            en=["balance sheets", "BWA reports", "Marktfolge back office", "bank document automation"],
            de=["Bilanzen", "BWA", "Marktfolge", "Backoffice Automatisierung"],
        ),
        core_object_terms=BilingualTerms(
            en=["balance sheet", "financial statements", "contracts"],
            de=["Bilanz", "Bilanzen", "Verträge"],
        ),
        must_keep_constraints=[],
        drift_risks=[],
        authority_blueprints=[],
        facets=[],
        global_canonical_terms=BilingualTerms(en=[], de=[]),
        global_exclusions=BilingualTerms(en=[], de=[]),
    )
    query = _normalize_openalex_query(
        OpenAlexQuery(
            intent="match",
            language="en",
            search_field="title_and_abstract.search",
            query_string='("balance sheet" OR "financial statements") AND ("back office" OR Marktfolge OR bank) AND (NLP OR LLM OR "information extraction")',
            filters="is_paratext:false,is_retracted:false,language:en",
            sort="relevance_score:desc",
            per_page=200,
            notes="Uses core object terms and partial workflow context",
        )
    )

    _validate_openalex_anchor_presence([query], plan=plan)

    authority_query = _normalize_openalex_query(
        OpenAlexQuery(
            intent="authority",
            language="en",
            search_field="title_and_abstract.search",
            query_string='("pilot project" OR "case study") AND (Sparkasse OR bank) AND ("balance sheet" OR contracts) AND ("back office" OR Marktfolge)',
            filters="is_paratext:false,is_retracted:false,language:en",
            sort="relevance_score:desc",
            per_page=200,
            notes="Authority query using decomposed anchor language",
        )
    )

    _validate_openalex_anchor_presence([authority_query], plan=plan)


def test_openalex_anchor_presence_accepts_object_facet_canonical_variants() -> None:
    plan = QueryPlan(
        topic_summary_en="Automation of financial document analysis",
        topic_summary_de="Automatisierung der Analyse von Finanzdokumenten",
        primary_context_anchors=BilingualTerms(
            en=[
                "balance sheets",
                "BWA reports",
                "contracts",
                "market follow-up",
                "Sparkassen pilots",
                "financial document automation",
            ],
            de=["Bilanzen", "BWA", "Verträge", "Marktfolge", "Pilotprojekte"],
        ),
        core_object_terms=BilingualTerms(
            en=["balance sheets", "BWA reports", "contracts", "financial statements", "market follow-up documents"],
            de=["Bilanzen", "BWA", "Verträge", "Finanzdokumente"],
        ),
        must_keep_constraints=[],
        drift_risks=[],
        authority_blueprints=[],
        facets=[
            Facet(
                facet_id="document_balance_sheets",
                facet_label_en="Balance sheets",
                facet_label_de="Bilanzen",
                facet_type="data",
                facet_group="object",
                query_family_preference="object_core",
                language_strategy="en_de_parallel",
                authority_role="core",
                importance_weight=5,
                text_en="",
                text_de="",
                canonical_terms=BilingualTerms(
                    en=["balance sheet", "financial statement", "bank balance sheet"],
                    de=["Bilanz", "Bilanzen"],
                ),
                neighbor_terms=BilingualTerms(en=[], de=[]),
                exclusion_terms=BilingualTerms(en=[], de=[]),
            ),
            Facet(
                facet_id="document_bwa_reports",
                facet_label_en="BWA reports",
                facet_label_de="BWA Berichte",
                facet_type="data",
                facet_group="object",
                query_family_preference="object_core",
                language_strategy="en_plus_selective_de",
                authority_role="core",
                importance_weight=5,
                text_en="",
                text_de="",
                canonical_terms=BilingualTerms(
                    en=["BWA", "BWA report", "monthly BWA"],
                    de=["BWA", "BWA Bericht"],
                ),
                neighbor_terms=BilingualTerms(en=[], de=[]),
                exclusion_terms=BilingualTerms(en=[], de=[]),
            ),
            Facet(
                facet_id="document_contracts",
                facet_label_en="Contracts",
                facet_label_de="Verträge",
                facet_type="data",
                facet_group="object",
                query_family_preference="object_core",
                language_strategy="en_de_parallel",
                authority_role="core",
                importance_weight=5,
                text_en="",
                text_de="",
                canonical_terms=BilingualTerms(
                    en=["contract", "loan agreement", "service agreement"],
                    de=["Vertrag", "Verträge"],
                ),
                neighbor_terms=BilingualTerms(en=[], de=[]),
                exclusion_terms=BilingualTerms(en=[], de=[]),
            ),
        ],
        global_canonical_terms=BilingualTerms(en=[], de=[]),
        global_exclusions=BilingualTerms(en=[], de=[]),
    )
    queries = [
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("balance sheet" OR "financial statement") AND ("time savings" OR "processing time") AND ("automation" OR "document automation" OR "NLP" OR "LLM")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="Live-shape match query",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="authority",
                language="en",
                search_field="search",
                query_string='("Sparkasse" OR "Sparkassen" OR "German savings bank") AND ("pilot project" OR "case study") AND ("BWA" OR "BWA report" OR "balance sheet" OR "financial statement" OR "contract")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="cited_by_count:desc",
                per_page=200,
                notes="Live-shape authority query",
            )
        ),
    ]

    _validate_openalex_anchor_presence(queries, plan=plan)
    _validate_match_core_object_presence([queries[0]], plan=plan, provider="OpenAlex")


def test_s2_match_core_object_presence_rejects_workflow_only_primary_context() -> None:
    plan = QueryPlan(
        topic_summary_en="Automation of financial document analysis",
        topic_summary_de="Automatisierung der Analyse von Finanzdokumenten",
        primary_context_anchors=BilingualTerms(
            en=["balance sheets", "BWA reports", "contracts", "market follow-up", "financial document automation"],
            de=["Bilanzen", "BWA", "Verträge", "Marktfolge"],
        ),
        core_object_terms=BilingualTerms(
            en=["balance sheets", "BWA reports", "contracts", "financial statements", "market follow-up documents"],
            de=["Bilanzen", "BWA", "Verträge", "Finanzdokumente"],
        ),
        must_keep_constraints=[],
        drift_risks=[],
        authority_blueprints=[],
        facets=[],
        global_canonical_terms=BilingualTerms(en=[], de=[]),
        global_exclusions=BilingualTerms(en=[], de=[]),
    )
    bad_query = _normalize_s2_query(
        S2BulkQuery(
            intent="match",
            language="en",
            query_string='+("market follow-up" | "Marktfolge" | "financial document automation") +("post-trade operations" | "back office" | "bank operations automation" | "processing pipeline")',
            notes="Workflow-only context should fail",
        )
    )

    try:
        _validate_match_core_object_presence([bad_query], plan=plan, provider="S2")
    except ValueError as exc:
        assert "match query missing core object term" in str(exc)
    else:
        raise AssertionError("Expected workflow-only S2 query to be rejected")


def test_openalex_fingerprint_prefers_core_object_variation_over_reused_workflow_context() -> None:
    plan = QueryPlan(
        topic_summary_en="Automation of financial document analysis",
        topic_summary_de="Automatisierung der Analyse von Finanzdokumenten",
        primary_context_anchors=BilingualTerms(
            en=["Marktfolge back office", "bank document automation", "Sparkasse pilot projects"],
            de=["Marktfolge", "Backoffice Automatisierung", "Sparkasse Pilotprojekt"],
        ),
        core_object_terms=BilingualTerms(
            en=["balance sheet", "financial statements", "BWA", "BWA report", "contracts"],
            de=["Bilanz", "Bilanzen", "BWA", "Verträge"],
        ),
        must_keep_constraints=[],
        drift_risks=[],
        authority_blueprints=[],
        facets=[],
        global_canonical_terms=BilingualTerms(en=[], de=[]),
        global_exclusions=BilingualTerms(en=[], de=[]),
    )
    queries = [
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("balance sheet" OR "financial statements") AND ("bank document automation" OR "Marktfolge back office") AND (NLP OR LLM OR "information extraction")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="EN balance sheets",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("BWA report" OR BWA) AND ("bank document automation" OR "Marktfolge back office") AND (NLP OR LLM OR "information extraction")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="EN BWA",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='(contracts OR "financial statements") AND ("bank document automation" OR "Marktfolge back office") AND (NLP OR LLM OR "information extraction")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="EN contracts",
            )
        ),
        _normalize_openalex_query(
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("balance sheet" OR contracts) AND ("bank document automation" OR "Marktfolge back office") AND (NLP OR LLM OR "information extraction")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="EN mixed objects",
            )
        ),
    ]

    _validate_openalex_match_anchor_fingerprint_diversity(queries, plan=plan)


def test_query_plan_repair_demotes_excess_booster_facets_when_blueprint_capacity_is_full() -> None:
    def _facet(facet_id: str, *, authority_role: str, importance_weight: int, facet_group: str = "context") -> Facet:
        return Facet(
            facet_id=facet_id,
            facet_label_en=facet_id,
            facet_label_de=facet_id,
            facet_type="construct",
            facet_group=facet_group,
            query_family_preference="object_plus_context" if facet_group == "context" else "object_plus_data_proxy",
            language_strategy="en_plus_bilingual_fallback",
            authority_role=authority_role,
            importance_weight=importance_weight,
            text_en=facet_id,
            text_de=facet_id,
            canonical_terms=BilingualTerms(en=[facet_id], de=[facet_id]),
            neighbor_terms=BilingualTerms(en=[], de=[]),
            exclusion_terms=BilingualTerms(en=[], de=[]),
        )

    plan = QueryPlan(
        topic_summary_en="Automation of financial document analysis",
        topic_summary_de="Automatisierung der Analyse von Finanzdokumenten",
        primary_context_anchors=BilingualTerms(
            en=["balance sheet", "financial statements", "market follow up", "document automation"],
            de=["Bilanz", "Bilanzen", "Marktfolge", "Dokumentautomation"],
        ),
        core_object_terms=BilingualTerms(
            en=["balance sheet", "financial statements", "contracts"],
            de=["Bilanz", "Bilanzen", "Verträge"],
        ),
        must_keep_constraints=["focus on bank documents", "keep automation metrics", "include pilot evidence"],
        drift_risks=["generic NLP papers", "medical document extraction"],
        authority_blueprints=[
            AuthorityBlueprint(
                authority_kind="core",
                label_en="Core A",
                label_de="Core A",
                target_facet_ids=["core_a", "core_b", "core_c", "core_d"],
                language_strategy="en_core_only",
                search_breadth="tight",
                notes_en="Core authority coverage for bank documents",
            ),
            AuthorityBlueprint(
                authority_kind="core",
                label_en="Core B",
                label_de="Core B",
                target_facet_ids=["core_e"],
                language_strategy="en_core_only",
                search_breadth="tight",
                notes_en="Supplemental core authority coverage",
            ),
            AuthorityBlueprint(
                authority_kind="booster",
                label_en="Booster A",
                label_de="Booster A",
                target_facet_ids=["boost_a", "boost_b", "boost_c", "boost_d"],
                language_strategy="en_core_only",
                search_breadth="broad_ok",
                notes_en="Booster authority coverage for methods and proxies",
            ),
            AuthorityBlueprint(
                authority_kind="booster",
                label_en="Booster B",
                label_de="Booster B",
                target_facet_ids=["boost_e", "boost_f", "boost_g", "boost_h"],
                language_strategy="en_core_only",
                search_breadth="broad_ok",
                notes_en="Additional booster authority coverage",
            ),
        ],
        facets=[
            _facet("core_a", authority_role="core", importance_weight=5, facet_group="object"),
            _facet("core_b", authority_role="core", importance_weight=5, facet_group="object"),
            _facet("core_c", authority_role="core", importance_weight=4, facet_group="construct"),
            _facet("core_d", authority_role="core", importance_weight=4, facet_group="context"),
            _facet("core_e", authority_role="core", importance_weight=3, facet_group="context"),
            _facet("boost_a", authority_role="booster", importance_weight=5, facet_group="method"),
            _facet("boost_b", authority_role="booster", importance_weight=5, facet_group="method"),
            _facet("boost_c", authority_role="booster", importance_weight=4, facet_group="data_proxy"),
            _facet("boost_d", authority_role="booster", importance_weight=4, facet_group="context"),
            _facet("boost_e", authority_role="booster", importance_weight=3, facet_group="context"),
            _facet("boost_f", authority_role="booster", importance_weight=3, facet_group="context"),
            _facet("boost_g", authority_role="booster", importance_weight=2, facet_group="context"),
            _facet("boost_h", authority_role="booster", importance_weight=2, facet_group="context"),
            _facet("boost_overflow", authority_role="booster", importance_weight=1, facet_group="data_proxy"),
        ],
        global_canonical_terms=BilingualTerms(en=[], de=[]),
        global_exclusions=BilingualTerms(en=[], de=[]),
    )

    repaired, notes = _repair_query_plan(plan)
    critical = diagnose_query_plan(repaired).get("critical_issues") or []
    assert not any("authority_role='booster'" in issue for issue in critical), f"Booster coverage issue remained after repair: {critical}"
    repaired_roles = {facet.facet_id: facet.authority_role for facet in repaired.facets}
    assert repaired_roles["boost_overflow"] == "none"
    assert any("demoted booster authority_role to 'none'" in note for note in notes)


def test_s2_validators_still_accept_reasonable_queries() -> None:
    queries = [
        _normalize_s2_query(
            S2BulkQuery(
                intent="match",
                language="en",
                query_string='+("balance sheet" | "BWA") +("time savings" | "OCR" | "LLM")',
                notes="EN S2 match",
            )
        ),
        _normalize_s2_query(
            S2BulkQuery(
                intent="match",
                language="de",
                query_string='+("Bilanz" | "BWA") +("Zeitersparnis" | "Dokumentenanalyse" | "LLM")',
                notes="DE S2 match",
            )
        ),
    ]
    _validate_s2_match_required_group_budget(queries)
    _validate_s2_advanced_syntax_budget(queries)


def test_s2_normalization_unescapes_negative_quotes() -> None:
    query = _normalize_s2_query(
        S2BulkQuery(
            intent="match",
            language="en",
            query_string='+("balance sheet" | "BWA") +("time savings" | "OCR") -(\\"front office\\")',
            notes="Escaped negative quotes",
        )
    )
    assert '\\"' not in query.query_string
    _validate_s2_match_required_group_budget([query])
    _validate_s2_advanced_syntax_budget([query])


def test_relevant_shadowed_definitions_removed() -> None:
    duplicates = _relevant_duplicate_functions()
    assert duplicates == {}, f"Unexpected duplicate top-level helper definitions remain: {duplicates}"


def main() -> int:
    tests = [
        test_openalex_fingerprint_ignores_always_on_object_anchors,
        test_openalex_fingerprint_still_fails_for_true_low_diversity,
        test_match_core_object_presence_still_enforced,
        test_openalex_match_anchor_presence_accepts_core_object_fallback,
        test_openalex_anchor_presence_accepts_object_facet_canonical_variants,
        test_s2_match_core_object_presence_rejects_workflow_only_primary_context,
        test_openalex_fingerprint_prefers_core_object_variation_over_reused_workflow_context,
        test_query_plan_repair_demotes_excess_booster_facets_when_blueprint_capacity_is_full,
        test_s2_validators_still_accept_reasonable_queries,
        test_s2_normalization_unescapes_negative_quotes,
        test_relevant_shadowed_definitions_removed,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
