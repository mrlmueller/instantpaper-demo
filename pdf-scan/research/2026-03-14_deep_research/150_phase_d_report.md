# Phase D Report

## Scope

Phase D takes the normalized Phase C corpus plus the user chapter specification and produces a retrieval plan that later phases can consume safely.

Input:

- `chapter_title`
- `chapter_spec_text`
- `normalized/documents.jsonl`
- `normalized/sections.jsonl`
- `normalized/passages.jsonl`

Output:

- a source-grounded `query_plan.json`
- derived retrieval views in `retrieval/query_views.json`
- corpus support analysis in `retrieval/phase_d_corpus_support.json`
- planner prompt/response trace
- OpenAI usage + cost tracking in `api_calls.jsonl` and the Phase D summary

The design goal is not “generate clever search terms”. The design goal is: produce a plan that is auditable, grounded in the chapter text, aware of the actual current corpus, and diverse enough to support per-document section retrieval in Phase E.

## Research Basis

I used the official OpenAI docs for the planner/API design:

- Responses API: <https://platform.openai.com/docs/api-reference/responses/create>
- Structured outputs: <https://platform.openai.com/docs/guides/structured-outputs>
- Prompt engineering: <https://platform.openai.com/docs/guides/prompt-engineering>
- Reasoning models guide: <https://platform.openai.com/docs/guides/reasoning>
- Prompt caching: <https://platform.openai.com/docs/guides/prompt-caching>
- Pricing: <https://platform.openai.com/docs/pricing>
- GPT-5 mini model page: <https://platform.openai.com/docs/models/gpt-5-mini>

Key implementation decision from this research:

- use structured parsing, not free-text JSON prompting
- keep the planner small and cheap with `gpt-5-mini`
- retry once with a slightly larger token ceiling if the first structured response is truncated
- save prompt, raw response, usage, and cost per run so later tuning is inspectable

## What I Implemented

Files:

- `pdf-scan/phase_d_lab.py`
- `pdf-scan/review_phase_d.py`
- `pdf-scan/pdf-scan-v3.ipynb`

Main changes:

1. Executable Phase D lab

- moved the working Phase D logic into `phase_d_lab.py`
- kept the notebook as a bridge into the executable implementation
- preserved structured terminal/notebook output and artifact writing

2. Source-anchor inventory

- build a ranked anchor inventory from the chapter title/spec
- use clauses, title-case phrases, parenthetical terms, quoted terms, and slash expansions
- normalize and deduplicate everything before planning

3. Structured OpenAI planner

- planner uses official structured outputs through `responses.parse`
- fallback to heuristic planner remains available
- prompt explicitly requires source-grounded terms and concise, retrieval-oriented subpoints

4. Stronger normalization after model output

- every model-produced term is rechecked against the source-anchor inventory
- drift terms are pruned instead of trusted
- the final saved plan is the normalized plan, not the raw model guess

5. Corpus-aware recalibration

- Phase D now looks at the actual current Phase C corpus before finalizing must-terms
- must-terms are promoted from terms that are both source-grounded and actually supported in `sections.jsonl`
- unsupported must-terms are eliminated from the final must-term set

6. Unsupported-subpoint suppression

- after term rebalance, Phase D checks whether each subpoint has any lexical support in the current corpus
- unsupported subpoints are suppressed from retrieval view generation if enough supported subpoints remain
- suppressed subpoints are still recorded for auditability

7. Compact retrieval views

- broad fallback view was shortened aggressively
- retrieval views now prefer corpus-supported expansion terms in the noisy fallback lane
- subpoint and summary queries are capped so later retrieval does not get flooded with generic long-form text

8. Full cost tracking

- OpenAI usage/cost is tracked in the Phase D summary and the run-level API ledger
- pricing is resolved against the official pricing page and saved with a verification date

## Iteration History

### Iteration 1

Initial Phase D executable pass worked, but two practical defects remained:

- the 22-PDF `paper-dump` corpus still produced `1` unsupported subpoint
- the broad fallback retrieval view was too long and noisy

This showed that source grounding alone was not enough. Phase D also needed to react to the actual corpus it was operating on.

### Iteration 2

I added:

- corpus-supported should-term tracking
- unsupported-subpoint suppression
- compact query construction for summary/subpoint/fallback views

This removed the unsupported subpoint and brought the long fallback query back under control.

## Validation

### Benchmark Run

Run:

- `2df0764dd82972281d527709`

Key artifacts:

- `runs/2df0764dd82972281d527709/retrieval/phase_d_summary.json`
- `runs/2df0764dd82972281d527709/retrieval/phase_d_assessment.json`
- `runs/2df0764dd82972281d527709/phase_d_review/phase_d_review_summary.json`

Final result:

| Metric                 |             Value |
| ---------------------- | ----------------: |
| Review category        |          `strong` |
| Planner mode           |          `openai` |
| API mode               | `responses.parse` |
| Source alignment ratio |             `1.0` |
| Must terms             |               `4` |
| Subpoints              |               `3` |
| Retrieval views        |               `7` |
| Unsupported must terms |               `0` |
| Unsupported subpoints  |               `0` |
| Estimated cost         |     `$0.00313275` |

What improved versus the earlier Phase D pass:

- unsupported subpoints removed
- overly long fallback view reduced from `82` words to `41`
- reviewer finding changed to `no material review findings`

Remaining benchmark warning:

- the planner still proposed some source-unanchored terms internally, but normalization pruned them before final plan emission

### Large-Corpus Validation on `paper-dump`

Final validated Phase D rerun:

- `2d016b977744ccd685b82001`

Important note:

- I reused the already-built Phase B/C artifacts from this 22-PDF run and reran only Phase D directly against them
- that isolates planner quality from parser changes and is the right test for this phase

Key artifacts:

- `runs/2d016b977744ccd685b82001/retrieval/phase_d_summary.json`
- `runs/2d016b977744ccd685b82001/retrieval/phase_d_assessment.json`
- `runs/2d016b977744ccd685b82001/phase_d_review/phase_d_review_summary.json`

Final result:

| Metric                 |             Value |
| ---------------------- | ----------------: |
| Review category        |          `strong` |
| Planner mode           |          `openai` |
| API mode               | `responses.parse` |
| Source alignment ratio |             `1.0` |
| Must terms             |               `7` |
| Subpoints              |               `4` |
| Retrieval views        |               `8` |
| Unsupported must terms |               `0` |
| Unsupported subpoints  |               `0` |
| Estimated cost         |     `$0.00269075` |

What improved versus the first large-corpus Phase D pass:

- review category improved from `acceptable_with_noise` to `strong`
- unsupported subpoints dropped from `1` to `0`
- long/noisy retrieval view issue removed
- fallback view reduced from `82` words to `40`

Only remaining warning:

- `1` source-unanchored subpoint term was proposed by the model and pruned during normalization

## Example Final Output Shape

The final paper-dump plan now looks like this at a high level:

- must terms:
  - `Biases`
  - `uncertainty`
  - `trust`
  - `Choice Architecture`
  - `Digital Nudging`
  - `perceived risk`
  - `Consumer Electronics`

- supported subpoints:
  - psychology of decision confidence under uncertainty
  - choice architecture and digital nudging mechanisms
  - ethical boundaries: transparency and user autonomy
  - perceived risk, trust, and uncertainty reduction for complex products

Why this is better:

- it is still close to the chapter source
- it is diverse enough for later retrieval
- every must-term has lexical support in the current corpus
- every retained subpoint has lexical support in the current corpus

## Why These Changes Matter For Later Phases

Phase D is the contract between chapter intent and retrieval execution.

What the current Phase D now enables:

- safer lexical retrieval
  - Phase E can trust must-terms much more because they are both source-grounded and corpus-supported

- better view diversification
  - subpoint views now represent real supported aspects of the chapter instead of speculative branches

- less retrieval noise
  - broad fallback is now a compact recovery lane, not a giant generic semantic dump

- easier debugging
  - prompt, response, normalized plan, corpus support, review summary, and API cost are all saved

## Important Observations

1. `should_terms` are still often lexically sparse

- This is expected for bilingual or concept-heavy chapter specs.
- They should not dominate lexical ranking in Phase E.
- They are still useful as lower-weight semantic hints.

2. The model sometimes truncates the first structured response

- The retry logic handled this correctly in both benchmark and paper-dump runs.
- This is why the implementation retries with a slightly larger output budget.

3. Planner quality must be judged against the current corpus, not just the chapter source

- A term can be source-grounded and still be a bad retrieval anchor for the current PDFs.
- This is why corpus-aware rebalancing was necessary.

## Remaining Tuning Knobs

These are not blockers for moving to Phase E, but they are worth keeping in mind:

- bilingual expansion:
  - add explicit English equivalents for high-value German anchors where the source implies them but the corpus is mostly English

- section-type steering:
  - if later retrieval is too intro-heavy, increase the preference weight for `results`, `discussion`, and `body_other`

- should-term weighting:
  - Phase E should give low lexical weight to unsupported should-terms and stronger weight only in semantic lanes

- planner retry policy:
  - if truncation remains common, increase the first-call token ceiling slightly instead of relying on the retry as often

## Conclusion

Phase D is now good enough to proceed.

Evidence:

- benchmark review: `strong`
- 22-PDF paper-dump review: `strong`
- source alignment: `1.0` in both validations
- unsupported must-terms: `0`
- unsupported subpoints: `0`
- OpenAI cost stayed very low, around `0.27` to `0.31` cents per run

Recommended next step:

- move to Phase E and explicitly use the Phase D outputs as weighted retrieval lanes rather than treating every query view as equally trustworthy
