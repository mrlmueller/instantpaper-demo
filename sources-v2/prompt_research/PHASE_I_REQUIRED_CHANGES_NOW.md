# Phase I Required Changes Now

Status: immediate follow-up note after the live Phase I run on `ca79147de41f8edbfb47c9e5`.

This document does not replace the earlier Phase I implementation plan. It supersedes it in the places where the live run showed that the current production shape is still not good enough. The goal of this note is to capture what needs to change right now before another implementation pass.

## Why this note exists

The live run showed two different problems at the same time.

The first problem is operational. Phase I produced too many `call_failed` fallback judgments, and those failed judgments were then reused from cache as if they were real rerank decisions. In this run, `29` final pointwise rerank rows ended up as `call_failed=true`. That alone is enough to distort the final ranking badly, because several genuinely promising papers were pushed down to score `0` only because the rerank call never completed successfully.

The second problem is semantic. Even when the rerank call succeeds, the current prompt still does not explain the task sharply enough. The model is given useful chapter data, but it is not told clearly enough what that data means, how trustworthy each part is, and what kind of judgment it is supposed to make in the context of the whole pipeline. The result is that broad “Late Antiquity / transformation / Roman world” papers are still being treated too generously, while the actual chapter target is narrower: a chapter about economic explanatory approaches to the decline or transformation of the Western Roman Empire.

So the right conclusion is not that Phase I needs less information. The right conclusion is that Phase I needs better explained information, a more explicit task framing, and a much safer token budget.

## What the live run proved

The live run established several facts that the next Phase I revision should treat as non-negotiable.

First, the current output budget is too small for the current prompt package. The failure mode is not subtle. The saved debug responses show repeated `status="incomplete"` with `reason="max_output_tokens"`. Successful pointwise prompts had a median size of about `4205` characters and about `1257` input tokens, while failed pointwise attempts had a median size of about `6091` characters and about `1628` input tokens. In other words, the longer and richer prompts are exactly the ones that currently hit the token ceiling. If we want to keep the richer context, then the output budget must go up substantially.

Second, the current prompt is not “empty.” It already includes a chapter contract, lane guidance, required facets, candidate metadata, and evidence tags. The problem is more specific: it does not explain the role of those inputs well enough. It does not explain clearly that the evidence tags are downstream retrieval hints rather than verified facts. It does not explain strongly enough that this is the final ranking stage after a deliberately broad retrieval pipeline. It does not explain sharply enough that the model should prefer papers that directly help write a chapter comparing economic explanations, not papers that merely sit somewhere in the same historical neighborhood.

Third, the current reranker is still too generous with broad contextual literature. In the live run, candidates such as `Romans, Barbarians, and the Transformation of the Roman World...` and `Climate and the Decline and Fall of the Western Roman Empire...` received quite generous scores, while some more directly useful economic pieces were pushed out of the top slice by failed calls. This is not only a prompt issue, because the upstream evidence tags are sometimes overclaiming facet support. But Phase I is still the last place where this should be corrected, and right now it is not correcting it aggressively enough.

Fourth, the pairwise pass is not the main problem. Pairwise calls succeeded reliably in the live run and did not produce the same failure pattern. The primary issue sits in the pointwise rerank prompt and the pointwise runtime settings.

## Core design decision

The next Phase I revision should keep the richer information package and make it more interpretable, not smaller. The model should receive more narrative explanation of what the inputs are, what they mean, how much it should trust them, and what exact judgment it is being asked to make.

This means the next prompt should stop behaving like a compact technical checklist and start behaving more like a carefully written judging brief. The prompt can still end in a strict JSON schema, but the instruction body should contain more explanatory prose. The model should be told, in paragraph form, what this pipeline is doing and why this candidate is now in front of it.

At the same time, since we are intentionally keeping the rich input package, the token budget has to be raised to the point where `max_output_tokens` stops being a realistic failure mode. A rerank stage that silently turns relevant papers into score `0` because the model ran out of budget is not acceptable.

## Required prompt changes

The current prompt should be rewritten around the idea that the model is performing a final scientific usefulness judgment inside a larger retrieval pipeline.

The system prompt should explain, in prose, that the candidate was produced by earlier high-recall stages. It should explicitly say that the earlier stages are intentionally broad, that the evidence tags are informative but noisy, and that the model’s job is to decide whether this source would actually help write the exact target chapter. The prompt should state clearly that late-antique adjacency is not enough, Roman adjacency is not enough, and general transformation literature is not enough. What matters is whether the candidate directly advances or tests economic explanations for the Western Roman Empire’s decline or transformation in Late Antiquity.

The user prompt should continue to include the structured blocks, but each block should be introduced by an explanation of what it means.

The prompt should explain the original chapter title and original chapter specification text in full. The full `chapter_title` and the full `chapter_spec_text` should be passed, not only the compact contract derived from them. The compact contract should still stay in the prompt, but now it should be framed as an interpretive summary layer rather than the only source of task context.

The prompt should explain the lane in full sentences. For `match`, the model should be told that it is looking for papers that are directly about the chapter’s problem or are clearly useful evidence for evaluating competing economic explanations. For `authority`, the model should be told that “foundational” does not mean broadly famous or generally important. It means foundational for this specific debate. A globally important paper on trade, climate, migration, religion, or general late-antique transition is still weak if it does not materially help with the chapter’s economic explanatory comparison.

The prompt should explain the pool in full sentences. For `with_abstract`, the abstract is the main place to judge actual topical fit and argumentative utility. For `without_abstract`, the model should be told that metadata-only judgments are possible but should remain conservative and should not be treated as strong evidence unless the rest of the metadata is unusually direct.

The prompt should explain the candidate metadata field by field. It should say what the title contributes, what the year contributes, what the venue contributes, what citation counts can and cannot mean, and how to use the abstract. Citations should be framed as a weak secondary clue, never as a substitute for topic fit.

The prompt should explain the evidence tags field by field. It should say explicitly that a tag is a retrieved evidence snippet from an earlier stage, not a verified truth claim. The `facet_id` tells the model what earlier stages thought the snippet might be relevant to. The `score` tells the model how strongly earlier stages matched that snippet. The `excerpt` is the actual local evidence. The model should be told that it must rely on the excerpt itself and not blindly trust the facet label. If the excerpt only gives broad adjacency, then the model should treat the tag as weak.

The prompt should explain what each scoring dimension is supposed to mean and, equally important, what evidence each dimension should be based on.

`topical_fit_0_4` should be described as a judgment based primarily on the original chapter title, the original chapter specification text, and the candidate’s title and abstract. This dimension should answer the question: is this source centrally about the chapter’s target problem?

`evidence_strength_0_4` should be described as a judgment based primarily on the evidence tag excerpts and the candidate abstract. This dimension should not reward the mere existence of many tags. It should reward specific, concrete, and clearly relevant evidence.

`chapter_utility_0_4` should be described as a writing-task judgment. The model should ask: if I were writing this exact chapter, would this source materially help me reconstruct, compare, or test economic explanations for the Western Roman Empire’s decline or transformation? This dimension should strongly demote papers that are only background context.

`lane_fit_0_4` should be described as a secondary judgment after topical relevance is already considered. For `match`, it should reflect direct fit to the chapter problem. For `authority`, it should reflect foundational value for the chapter’s actual debate, not general academic importance.

The prompt should also introduce an explicit centrality concept in prose, even if it does not become a separate output field yet. The model should be told that a source can mention the right historical world and still not be centrally about the chapter. If the source only touches economic material incidentally, or mainly studies identity, religion, migration, climate, or cultural change without making economic mechanisms central, then it should score conservatively.

## Required instruction style changes

The prompt should use more paragraphs and fewer isolated bullet lines. The current short-rule style is too easy for the model to treat as a generic schema-filling task. The next version should read more like a short written brief from a human research lead.

The model should be told, in prose, that it is looking at the final filtering step of a deliberately broad pipeline. It should be told that some candidates are present precisely because earlier stages were optimized for recall. It should therefore not interpret presence in the candidate set as evidence that a source is good. It should also be told that it is expected to reject many candidates strongly.

The prompt should also explicitly tell the model that high scores should be rare. A score above `80` should be reserved for papers that are either directly about the chapter’s target explanatory debate or clearly indispensable for evaluating it. A score around `50` should mean “useful but partial.” A score around `20-30` should mean “adjacent or background-only.” This kind of prose calibration is important for comparability across about `160` calls per run.

## Required reliability changes

The next revision must treat `max_output_tokens` failures as a critical production defect, not a tolerable fallback.

The pointwise rerank `max_output_tokens` should be increased substantially. The target is not “probably enough.” The target is “large enough that this failure mode stops happening in normal runs.” Given the observed failure pattern, the next implementation should start the pointwise budget at roughly `2500` output tokens. The actual JSON output will remain short, but the extra budget gives the nano model enough room to finish its hidden reasoning and still emit the structured result.

The pairwise rerank budget should also be raised, though less aggressively. A starting value around `1500` output tokens is appropriate.

Failed pointwise results should no longer be treated as valid cached judgments. They may still be written to disk for diagnostics, but they should not be reused as if they were trustworthy rerank outputs. On rerun, a `call_failed=true` cache entry should be retried automatically rather than accepted as a cache hit.

The same logic should apply to incomplete structured-output responses. If the model did not produce a valid final JSON answer, that record should be considered diagnostically useful but semantically invalid.

## Required semantic changes to the judgment policy

The next prompt should tell the model much more explicitly how to distinguish four different cases.

The first case is direct chapter fit. These are papers that directly discuss economic mechanisms, economic structures, or economic explanatory models for the Western Roman Empire’s decline or transformation in Late Antiquity. These should score highest.

The second case is strong evaluative support. These are papers that are not themselves framed as grand explanatory syntheses but provide strong source-based evidence that can test such explanations, for example through coinage, trade, taxation, land use, demography, or other economically relevant proxies in the right corpus and time frame. These should score well, but below direct chapter-fit papers.

The third case is broad historical context. These are papers about Late Antiquity, the Roman world, regional transformation, migration, religion, identity, or environmental change that may be adjacent to the chapter but are not clearly useful for the chapter’s economic explanatory comparison. These should be scored conservatively.

The fourth case is off-topic literature. These are papers that happen to share a few retrieval terms, or happen to sit in the same large historical landscape, but do not materially help with the chapter. These should be marked off-topic and kept low.

The authority lane needs a separate warning paragraph. It should say that authority does not mean “good background reading” and does not mean “highly cited in a neighboring domain.” Authority means that, for this exact chapter, the work is foundational or repeatedly relied on when scholars make, compare, or evaluate economic explanations. This distinction needs to be written into the prompt in plain language.

## Required treatment of upstream evidence tags

The next prompt should explicitly tell the model that evidence tags can overclaim support. The model should be instructed not to accept a facet as covered simply because a facet label appears in the tag list. It should read the excerpt and decide whether the excerpt actually supports that facet in a way that matters for this chapter.

This is especially important because the live run showed broad papers receiving tags such as `trade_and_market_integration`, `agricultural_productivity_landuse`, or `monetary_and_coinage_evidence` on the basis of broad adjacency rather than clearly relevant argumentation. The reranker has to become more skeptical than the upstream stage, not equally trusting.

## Recommended revised prompt structure

The next pointwise prompt should roughly follow this structure:

1. A prose system prompt explaining the overall pipeline role and the need for strict, chapter-specific judgment.
2. A prose preamble in the user prompt explaining that the model is seeing a final-stage candidate from a high-recall pipeline.
3. The original `chapter_title`.
4. The full `chapter_spec_text`.
5. The compact chapter contract summary.
6. A prose explanation of lane meaning.
7. A prose explanation of pool meaning.
8. A prose explanation of candidate metadata fields.
9. A prose explanation of evidence tags and how to interpret them.
10. The structured candidate metadata.
11. The structured evidence tags.
12. A prose explanation of the rubric dimensions and what evidence each dimension should use.
13. A short calibration paragraph explaining what high, medium, and low scores mean.
14. The strict JSON output schema.

This keeps the rich data package while making the semantics much clearer.

## What should happen next

The next implementation pass should not be a small tweak. It should be a focused Phase I revision built around the changes above.

The most important implementation goals are:

- rewrite the pointwise prompt into a more explanatory, paragraph-driven judging brief
- include the original chapter title and full chapter specification text
- explain every major input block and how it should be used
- raise `max_output_tokens` enough to stop incomplete responses
- stop treating `call_failed` pointwise caches as valid semantic results
- preserve the pairwise step, because it is not the current failure source

Only after those changes are in place should the rerank output be evaluated again.
