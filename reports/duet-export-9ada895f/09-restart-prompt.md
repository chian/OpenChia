# Starter prompt for the new Duet (paste with `/paste`)

Below is a condensed restart brief assembled from the approved rev‑34 contract, your recorded
goal answer, and the latest decision ledgers. Paste the fenced block into the new Duet as your
first message, then feed it the detailed artifacts from `04-context/` on request (the Duet cannot
read local files; paste `content` sections as needed).

```
GOAL (exact, previously host-recorded):
Determine, by measured read-only experiment against the BV-BRC RAGstack asm-next tenant, which
retrieval and generation parameter combination and which episodic question-answering structure
produce the best answers within each ASM paper collection measured separately, with the benchmark
weighted toward multi-paper synthesis, leaving behind a per-collection winning configuration and
the per-question evidence justifying it.

SOURCES: landing page https://www.bv-brc.org/ragstack/ ; tenant asm-next ; API docs
https://www.bv-brc.org/ragstack/asm-next/api/docs ; example question pipeline
https://github.com/chian/nano-graphrag/tree/main/question_pipeline .
Access token is in ~/.patric_token — never read it into this conversation; the run's single
allowlisted HTTP client opens it.

DECISIONS ALREADY MADE (keep unless you argue otherwise):
- Three ASM collections, measured separately, never unioned. Run one at a time, largest first.
- Unit: one per-collection study end to end; inside it, one trial changes one setting at a time.
- Evidence: a corpus-generated benchmark of up to 40 questions with multi-paper gold evidence,
  frozen before scoring; a setting's effect counts only if it beats the noise floor from repeated
  baseline runs; headline score from a 25% holdout that never steers the search; every citation
  checked against its source chunk.
- Judge: the Episode's own model with one frozen prompt; it never helps produce the answers it
  grades. ASM paper text may go to the Episode's own model (Anthropic) for question writing and
  judging — approved.
- Cost: sweep settings on the cheapest tenant model; confirm each collection's winner on the
  strongest; report configuration and model effects separately.
- Budget: ceiling 1,500 calls per collection; weekly budget is unknown. If it runs out: stop,
  write a checkpoint, keep complete results for finished collections, resume after the Monday
  reset as a new approved run that first re-checks the baseline and model versions.
- Stopping per collection: tuning score 0.9, or a plateau across settings, or 1,500 calls. Whole
  run stops immediately on budget exhaustion or an error spike.
- Credit = coverage-weighted: per collection 0.5 for a verified result + 0.25 × share of
  parameter settings actually tested + 0.25 × share of structures actually tested. Fixed
  denominators exclude rerank sub-settings if rerank loses, exclude use_graph where graph results
  can't be attributed to the collection, and exclude structures that are add-ons to another
  structure. Cut-short work is reported as untested, never as no-effect.
- Parameter axes: retrieval_mode, top_k, rerank (+ rerank_candidates, reranker), context_window,
  use_graph, template, query_rewrite. Axes struck at reconnaissance (e.g. only one template
  served) leave the denominator with recorded evidence.
- Access: code execution and file writes only. All HTTP through one client that permits
  read-only endpoints only, self-tested first; leak scan at the end.
- Output: a run-scoped directory under /Users/me/Development/OpenChia with every record listed in
  a manifest with a hash per file; per collection: winning configuration as a runnable JSON
  profile plus per-question evidence.

PREVIOUS DESIGN (for reference, not binding): root → recon_harness, recon_inventory,
study_r1..r3 (each: setup → phase_a → phase_b → closeout), root_consolidate, root_verify.
It failed in the old host on a depth-bound bug, not on its content.

Please propose the Episode workflow for this. Ask me only about things not settled above.
```
