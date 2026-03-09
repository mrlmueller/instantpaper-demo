# Research Notes — Prompting

Status: active working notes.

## What mattered most from the external prompt research

### 1. Strong prompts are ordered contracts, not long piles of rules

OpenAI's prompting guidance is consistent on a few high-value themes:
- give clear and specific instructions
- state the task in the order you want the model to optimize it
- break complex tasks into simpler subtasks
- show the desired output shape explicitly
- test prompt changes against representative data, not anecdotes

Practical implication for this pipeline:
- each stage should begin with an explicit priority order
- the priority order must match retrieval reality
- for this project, "preserve the chapter's true object and retrieval target" must come before "be generic across domains" or "be concise"

Current local mismatch:
- the planner prompt is full of hygiene rules, but the objective hierarchy is too weak
- this lets the model satisfy format and genericity constraints while discarding the chapter's most distinctive retrieval anchor

### 2. System prompt and user prompt should do different jobs

Best division of labor:
- system prompt:
  - role
  - stable invariants
  - optimization priority order
  - grounding rules
  - anti-drift rules that apply to every request
- user prompt:
  - chapter-specific inputs
  - per-run budget
  - provider-specific output fields
  - current query plan / evidence bundle
  - any task-specific must-haves for this run

Current local mismatch:
- too many stage-specific formatting rules live in the user prompt without a strong stable objective contract in the system prompt
- this makes the model reliable at formatting but less reliable at preserving the right semantics

### 3. Positive obligations beat long lists of bans

OpenAI's prompting material explicitly advises saying what the model should do, not only what it should avoid.

Pipeline implication:
- replace broad negative rules like "no generic research words" with conditional rules:
  - generic standalone words are bad
  - domain-critical phrases that happen to include generic words are often essential
- example:
  - banning `review` is good when it produces vague anchors like `review`
  - banning `online reviews` is bad when the whole chapter is about online reviews

### 4. Reasoning models usually want simpler prompts than people expect

The reasoning-best-practices guidance points in a useful direction:
- keep prompts direct
- avoid unnecessary meta-instructions
- do not stuff the prompt with redundant "think carefully" language
- give cleanly delimited inputs and explicit success criteria

Pipeline implication:
- the stage prompts should be shorter in prose but sharper in priorities
- internal distinctions such as:
  - chapter object / corpus
  - construct / question
  - data source / proxy
  - method
  - exclusions
  should be explicit
- but the model does not need a large amount of motivational or stylistic wording around them

### 5. Structured outputs reduce syntax risk, but only for the schema surface

OpenAI's structured outputs material strongly supports strict JSON schema for shape control.

Important nuance:
- schema reliability does not solve semantic drift
- it guarantees shape much better than meaning
- so prompts should ask the model for semantic decisions, while code should own brittle syntax where possible

Pipeline implication:
- Phase C currently asks the model to generate many provider-specific syntax details directly inside `query_string`
- that is a bad split of responsibilities when deterministic code can assemble valid queries from semantic groups

## Prompt design rules derived for this pipeline

### Rule A: every stage must preserve the chapter object explicitly

For retrieval, the most important information is often not the method but the object:
- online reviews
- app store reviews
- patient narratives
- earnings call transcripts
- case reports
- administrative claims

These phrases often look "generic" to a generic prompt, but they are the retrieval target.

Future-self note:
- if a prompt ever causes the model to replace a concrete corpus/object with a broader abstraction, treat that as a prompt failure even if the JSON is valid

### Rule B: prompts must separate object, construct, and method

These are different retrieval roles:
- object:
  - what literature is about
- construct:
  - what the chapter is trying to understand, measure, or explain
- method:
  - how papers analyze it

Failure pattern in the current pipeline:
- methods drift upward into anchors and high-weight facets
- object specificity drops
- rerank then over-rewards generic method papers

### Rule C: if a term can be read as "too generic", evaluate phrase-level meaning, not token-level meaning

Bad rule:
- ban the token `review`

Better rule:
- ban vague anchors like `review`, `analysis`, `study`
- allow phrases where the full phrase is a domain object:
  - `online reviews`
  - `customer reviews`
  - `peer review` if the chapter is actually about peer review

### Rule D: query builders need anti-drift tests inside the prompt

The builder prompt should force the model to ask:
- does this query still retrieve papers about the chapter object, or only about the method?
- would a generic survey in NLP/LLMs/economics match this query even if it ignores the chapter object?
- if yes, the query is too broad

### Rule E: rerank prompts must rank chapter usefulness, not generic importance

The current rerank prompt says relevance matters, but not sharply enough.

Better rubric:
- generic importance without chapter-object evidence should not score highly
- a method paper can be helpful, but it is not automatically a strong chapter match
- `authority` should mean "foundational for this chapter's topic", not "highly cited in an adjacent field"

## What should live in system prompts vs user prompts

### System prompt contents for this project

Stable, cross-run:
- role
- objective hierarchy
- grounding policy
- anti-drift policy
- constraints that should never change between chapters

Examples:
- preserve chapter object before broadening
- use only supplied evidence
- do not infer unsupported content
- if constraints conflict, prefer on-topic specificity over generic breadth

### User prompt contents for this project

Run-specific:
- chapter title
- chapter spec
- query plan JSON or evidence bundle
- provider budget
- language requirements
- exact output schema description
- stage-specific instructions

Examples:
- per-provider query budget
- which languages to cover
- which fields to populate
- which facets are weight>=4 in this run

## Prompt anti-patterns seen in the local pipeline

### Planner anti-patterns

- broad generic-word bans without phrase-level exceptions
- insufficient distinction between chapter object and method
- no explicit cap on method-only anchors
- no semantic self-check like "would this plan still retrieve papers about the chapter object?"

### Query-builder anti-patterns

- too much provider syntax burden on the model
- budgeting by facet count without enough weighting toward object-preserving queries
- no required query family devoted purely to the chapter object plus construct
- provider rules partially out of date relative to current docs

### Rerank anti-patterns

- not enough chapter-target context in the prompt
- too much trust in upstream `coverage_tags`
- insufficient penalties for generic method surveys
- `insufficient_info` is allowed, but not pushed hard enough

## Working prompt heuristics to apply in the report

1. Start each system prompt with a clear role and ordered priorities.
2. Put the chapter object/corpus/domain in the first priority slot.
3. Convert generic bans into conditional phrase-aware rules.
4. Tell the model which kinds of drift are unacceptable.
5. Keep syntax instructions narrow and deterministic.
6. Where syntax is brittle, prefer semantic group generation plus deterministic assembly.
7. For rerank, define what a low score means and make high scores rare.
8. Use evals and judged pools to tune prompts; do not trust one good run.

## Notes to future self

- Re-check provider docs whenever query syntax starts failing. The OpenAlex docs changed enough that some current prompt assumptions are already stale.
- If a prompt revision improves JSON cleanliness but hurts object retention, reject it.
- Use examples only where the model keeps making the same semantic mistake. Do not add examples preemptively to every stage.
- The main failure mode here is not syntax. It is semantic drift from object-specific retrieval to generic method retrieval.
