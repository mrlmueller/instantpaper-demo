# Small Gold Population Checklist

Before we continue beyond early parsing and retrieval work, collect:

## One chapter

- 1 chapter title
- 1 full chapter description
- optional subpoints if the chapter is complex

## Four PDFs

### 1. Short strong match

- around 2-10 pages
- very clearly relevant
- at least one section that should score `3`

### 2. Long strong match

- around 40+ pages
- still clearly relevant
- useful for testing long-document parsing and section ranking

### 3. Partial difficult match

- somewhat relevant
- not a perfect thematic fit
- useful for ranking calibration

### 4. Hard negative overlap

- superficially similar topic
- should mostly or fully fail the target chapter
- useful for no-match behavior

## Annotation goal

For each document:
- mark whether it has useful information at all
- label only the actually relevant sections
