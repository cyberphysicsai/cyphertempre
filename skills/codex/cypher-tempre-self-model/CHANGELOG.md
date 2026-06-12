# Changelog

## v2.9 — 2026-06-11

Faculty packs become a product: the first curated pack ships, and the upgrade
system gains its deliberate path.

### Added
- **`faculties.py author`** — the third path of the upgrade system. Cambium
  grows faculties organically from gaps; `author` registers faculties designed
  ON PURPOSE: each entry validated, immune-screened, and born into the Dream
  Cache with ONE sealed `faculty-design` ring as the shared birth certificate
  (full spec in blockspace; every entry's `born_ring` points at the ring).
  Designed faculties start emergent at recurrence 1 and earn promotion the
  same way sprouts do — authoring is a birth, not a coronation.
- **`packs/trading-analysis-v1.json`** — the first curated faculty pack:
  8 senses (regime shifts, risk asymmetry, liquidity depth, sentiment
  divergence, lookahead bias, catalyst horizons, flow footprints, cost
  friction) and 6 modalities (expected-value reasoning, regime-conditional
  mapping, risk-first position calculus, backtest-skepticism auditing,
  macro-microstructure fusion, thesis-falsification framing). Every function
  is dual-duty text: dense in domain vocabulary so it fires lexically, and a
  crisp analytical discipline the attached model adopts as a lens. Proven on
  a fresh agent: dissonance on a trading brief fell 205 → 87 with exactly the
  right lenses firing. Spec + catalog in `packs/`.
- Four selftest checks for the author path (139 total).


## v2.8 — 2026-06-10

Benchmark-driven recall upgrades. An external tester ran the skill against
LongMemEval (official ICLR 2025 benchmark, stratified 12-question sample,
recall-only protocol): 11/12, with abstention and temporal — the categories
where commercial assistants crater — both clean. Storage was lossless in all
12; the single miss (q162) was pure retrieval: "miles" ranked Miles Davis
while the hike evidence sat sealed and unranked. This release attacks every
cause that miss exposed.

### Added
- **Quantity-aware labels:** number+unit pairs ("5 mile", "$800", "40%") are
  extracted into block labels at seal/ingest, indexed by the hippocampus, and
  boosted for quantity-seeking queries (hand scorer + new trained-scorer
  feature, backward compatible with pre-v2.8 telemetry). Buried passing-remark
  numbers — the evidence shape that killed q162 — stay reachable by labels.
- **Multi-query fan-out retrieve** (`retrieve "<main>" --queries "<alt>" …` /
  `Recall.retrieve_multi`): the model decomposes, the union is mechanical;
  max-score-wins dedup with per-query attribution. Sub-offers share a fanout
  group id and `telemetry.join_offers` credits a following fetch/use to every
  sub-offer in the group, so the learners see fan-out credit correctly.
- **Missed-positives now feed the lens:** used-but-unoffered rings — the
  strongest retrieval-failure signal — mine as lens positives. Demonstrated
  end-to-end: the q162 failure shape (jazz noise outranking unlabeled trail
  evidence) was reproduced, dreamed over (24 missed-positives mined), the lens
  adopted through its policy guard (holdout MRR 0.83 vs base 0.12), and the
  same one-shot query then ranked the evidence first — the system learning its
  way out of a measured miss from its own telemetry, zero new dependencies.
- **SKILL.md doctrine:** the recall escalation ladder (retrieve → fan-out →
  full index read → fetch → bounded scan; the index is PRIMARY when it fits),
  an aggregate-questions pattern (sums need every term — never top-k), and the
  semantic-recall upgrade path callout (provider st/openai, or the lens).
- Five new selftest checks (135 total).


## v2.7.1 — 2026-06-10

Field-reported bugfix (thank you to the reporter).

### Fixed
- **Registry-less `--root` crashed growth (reproducible):** a bare per-task
  chain root (`--root <task_dir>`, chain-only by design per the long-horizon
  docs) made `cambium.grow` crash with `FileNotFoundError` on
  `registry/modalities.json` — and a dream cycle on such a root sealed the raw
  error string into the dream ring instead of growing. New
  `cambium.registry_home(root, registry_root=None)` resolves where faculties
  LIVE: explicit `registry_root` wins; else the chain root when it carries the
  base registries; else the skill's own registry. Faculties belong to the
  self, not the task ledger — rings still seal into the task chain. Routed
  through `grow`/`sense`/`emergent` (new `--registry-root` flag),
  `chronosynaptic.load_faculties`, `faculties` pack import/export, and
  `dream.propose_growth`. Four regression checks added (130 total).


## v2.7 — 2026-06-10

Pre-release hygiene pass: the whole-repo review's findings, fixed. No new
organs — this release makes the five-phase membrane safe to ship and one
codebase across all five runtimes.

### Fixed
- **Dream-growth recurrence ratchet (review-proven):** repeated dreams over the
  SAME unchanged window walked a faculty born → recurrence → PROMOTED on zero
  new evidence. Growth now keeps a high-water mark (like missed-positive
  mining): only blocks sealed since the last growth pass may propose, so
  recurrence again means "this gap keeps arriving in NEW experience."
  Regression-tested.
- **`.gitignore` now covers per-user learner state** (`registry/policy.json`,
  `scorer.json`, `labeler.json`, `lens/`): a lived-in tree can no longer commit
  an agent's trained operators or covenant-tolerance overrides. Chain-rooted
  ledgers were already covered by `**/chain/`.

### Changed (deduplication — behavior identical, 126 checks green)
- **`operators.py`** — the shared guarantee machinery: sealed-adopt /
  sealed-rollback ring helpers, chain-derived version numbering, and the
  logistic squash, written once and consumed by all three learners
  (`learner.py`, `lens.py`, `extractor.py`). The no-silent-self-modification
  promise can no longer drift apart between learners.
- **`telemetry.join_offers`** — the canonical offer→fetch/use/replay credit
  join, consumed by both the decisions learner and the representation lens;
  credit assignment is now definitionally identical across learners.
- **`timechain.atomic_write_json`** — one crash-safe JSON writer for every
  derived store (registries, indexes, ledgers); cambium and hippocampus
  delegate to it.
- Per-turn loop doc: Perceive now points at the extractor teach loop.

### Ported
- **All five runtimes at parity:** codex, hermes, nanoclaw, and openclaw skills
  updated from v2.1 to the full v2.7 module set (Phases A–E + hygiene), keeping
  each platform's own SKILL.md framing.


## v2.6 — 2026-06-10

Phase E of the learning membrane — the final phase of the V3 design: the
extractor learner and dream-proposed label-space growth. All five learning
phases (A-E) are now complete: the loop labels its own data, every judgment
constant is either covenant policy or a calibrated quantity, and the whole
ascent is sealed, attested, and reversible.

### Added
- **Extractor (`extractor.py`)** — the model teaches its own cheap replacement.
  Confidence-scored cheap labeling (coverage x activation separation); texts
  below `extractor.route_confidence` ROUTE to the model as teach opportunities
  (`route` telemetry events — the routing-rate curve is the deliverable). `teach`
  records (one-way base-embedder vector + model labels + cheap baseline) pairs —
  raw text never enters the log. Dream cycles distill per-faculty sparse logistic
  heads from the teach corpus; adoption requires beating the CHEAP labeler at
  matching model labels on a temporal holdout (micro-F1), seals an `operator`
  ring with weights in blockspace, and `rollback` reverts (restoring from
  blockspace). Once active, distilled predictions augment every sealed label —
  leading the list, stamped `labeler_version` — and confidence rises, so routing
  falls: annotation economics mirror replay's generation economics.
- **Dream-proposed growth (`dream.py propose_growth`)** — stdlib k-means over
  recent block embeddings each dream; a cluster TIGHT in embedding space but
  INCOHERENT in fired labels (empty label sets read as maximally eligible —
  unnamed experience is what growth is for) sends its exemplar through
  `cambium.grow`. Recurrence and PROMOTE_AT govern promotion as ever; policy
  `growth.*` caps proposals per dream. The faculty registry is the label-space
  learner, now fed by dreams.
- **Dream report** gains growth and routing-rate sections; the dream ring
  summary announces grown faculties by name.

### Policy
- New `extractor` (min_pairs 40, switchover_margin 0.02, route_confidence 0.45,
  top_k 5) and `growth` (window 64, min_cluster 3, min_intra_sim 0.35,
  max_label_agreement 0.34, max_proposals_per_dream 2) sections.


## v2.5 — 2026-06-10

Phase D of the learning membrane: the representation learner and the dream
cadence. The first rung of recursive self-improvement now executes end-to-end —
with the core frozen and every step sealed.

### Added
- **Lens (`lens.py`)** — the representation learner: a small projection head
  trained OVER the frozen stdlib embedder on the chain's own telemetry pairs
  (fetched/used positives, offered-unfetched soft negatives, replay-reject hard
  negatives; query side = the offer's redacted label keywords, so raw queries
  never leave the log). Pairwise-logistic triplet loss, sparse stdlib SGD, no
  dependencies. The trained head is a NEW vector space with a composed
  fingerprint (`hashing:256:v1+lens-v1`): sealed vectors stay base-space forever
  and `lift` into lens space with one sparse matvec — the record never changes,
  the lens it is read through does. Adoption is policy-guarded (`lens.min_pairs`,
  `lens.switchover_margin`): the lens must beat the BASE embedder on a temporal
  holdout or the base remains. Every adoption seals an `operator` ring with the
  weights blob in blockspace; `rollback` reverts the ACTIVE pointer (restoring
  weights from blockspace if needed) and seals the reversion. Proven in selftest:
  the lens LEARNS an association with ZERO lexical overlap (alpha-beta queries →
  zebra ring) that the frozen base provably cannot see.
- **Dream (`dream.py`)** — meditation made executable, the one offline cadence:
  (1) verify chain + consensus (never train on a corrupt chain), (2) mine
  missed-positives (a used ring retrieval never offered — the strongest failure
  signal; high-water-marked O(new)), (3) train all four learners each behind its
  own policy gate (scorer, lens, appetite, PoQ grounding) where a refusal is
  cold-start health, (4) bidirectional salience overlay (`chain/salience.json`:
  fetch +1, use +2, replay-accept +3, falsify −4; derived and rebuildable, sealed
  history untouched), (5) replay token-economics accounting, (6) telemetry digest,
  (7) ONE sealed `dream` ring carrying the entire report. Honors dormancy: a
  paused self does not dream.
- **`recall retrieve --provider lens`** — recall through the learned space; the
  Hippocampus LSH bank is queried in BASE space (sealed vectors live there) and
  candidates re-rank through the lens via `lift`.

### Policy
- New `lens` section: `min_pairs` 80, `switchover_margin` 0.02, `d_out` 32,
  `epochs` 12, `lr` 0.05 — geometry and guards, co-evolver-ownable like the rest.


## v2.4 — 2026-06-10

Phase C of the learning membrane: the replay loop (the indexer economics made
executable) and the span-level HallucinationGuard (uncertainty applied to the
specific fabricated clause, not smeared over the answer).

### Added
- **Replay (`replay.py`)** — before generating from scratch, ask whether the chain
  already holds the answer. `match` offers sealed antecedents above a threshold
  (Hippocampus-narrowed; lexical coverage blended with embedding cosine where sealed
  vectors exist); the MODEL confirms — replay is offered, never imposed. `accept`
  logs a `replay-accept` (certified positive pair) with the tokens regeneration
  would have cost; `reject` logs the `replay-reject` hard negative contrastive
  training starves for. `calibrate --adopt` fits P(accept | match score) on logged
  outcomes and places the threshold at the covenant's tolerated false-replay rate
  (policy `replay.target_false_replay_rate`) — the values layer governs the cache's
  permitted deception rate. **Self-fulfilling-replay guard:** after
  `max_chain_depth` consecutive accepts a ring is flagged re-derivation due
  (`refresh` records the fresh derivation) — a replay-accept must never become the
  only evidence for the next replay. `stats` reports acceptance rate and total
  tokens saved: the token-economics ledger, measured.
- **Guard (`guard.py`)** — span-level grounding, the actual HallucinationGuard.
  Splits a candidate into clause-sized assertion spans and grounds EACH against the
  PoQ relevance window + context (lexical content-word coverage, optionally
  supplemented by embedding cosine), yielding per-span grounded/weak/unsupported
  verdicts and a span→ring CREDIT map. Wired into the conscience: `gate_and_seal`
  runs the guard on every seal, the sealed `poq_verdict` carries the compact span
  map, **FORCE_UNCERTAINTY now names the specific unsupported spans** to hedge or
  evidence, and `use` telemetry gains `computed_credit` — what the text actually
  leaned on, alongside what the model declared. CLI: `guard.py audit "<text>"`.
  Honest ceiling: the stdlib embedder cannot bridge true synonymy, so the guard
  names spans for the model (the final judge) to re-examine; it never unilaterally
  rejects.
- Policy gains the `replay` section (match threshold, false-replay tolerance,
  min events, max chain depth).

### Fixed
- **Canonical-hash stability ("hash what you write")** — a ring payload containing
  a dict with INT keys mixing 1- and 2-digit values (the guard's span-credit map)
  hashed over a different key ordering than the JSON written to disk (ints sort
  numerically in memory; their JSON string forms sort lexically), sealing a ring
  that was born unverifiable. Found in production minutes after shipping — the
  chain's own `verify` caught it on the very next walk. Root cause fixed twice
  over: `timechain._seal` now normalizes every ring through a JSON round-trip
  BEFORE hashing (the hashed object is byte-for-byte what disk re-reading yields),
  and the guard's credit map uses string keys at the source. Regression-tested
  with an int-keyed payload probe.

### Validated
- Eighteen mechanisms, 101 checks green (17 added): span splitting/merging,
  grounded-vs-unsupported separation with ring credit, FORCE_UNCERTAINTY naming the
  fabricated span, sealed verdicts carrying the span map, use events carrying
  computed credit, antecedent matching above threshold, accept/reject telemetry with
  token economics, the depth cap flagging re-derivation (and `refresh` resetting it),
  and threshold calibration landing exactly at the covenant's false-replay tolerance
  on mixed real+synthetic outcomes.

## v2.3 — 2026-06-10

Phase B of the learning membrane: the first learner goes live — retrieval weights
become a trained, sealed, rollback-able operator; thresholds become calibrated
quantities inside covenant-set tolerances; and grown faculties become shareable
packs. Recursive self-improvement's first rung, with provenance at every step.

### Added
- **Policy (`policy.py`)** — the values layer's grip on the machinery. Defaults live
  in code (never shipped as a file, so upgrades can't clobber edits — the grown.json
  lesson); `registry/policy.json` overrides them, with the covenant guard:
  `values.covenant_floor`/`consistency_floor` apply as max(default, user) — the
  conscience can be made stricter, never looser, by anyone, including the learner.
  The learner's only write path is the `calibrated` subsections, preserving user keys.
- **Decisions learner (`learner.py`)** — `train` joins offer→fetch/use telemetry along
  the arrow of time into labeled examples ("was this offered ring later fetched or
  declared as evidence?"), trains a stdlib logistic scorer over the same features the
  retrieval scorer computes (IPS-weighted where ε-explored), and evaluates on a
  temporal split against the hand weights. `--adopt` is guarded by policy (min events
  + switchover margin; cold start never degrades the agent) and **seals an `operator`
  ring** with weights, training range, and holdout evals — falsifiable by re-running.
  `rollback` reverts to the previous sealed operator and seals the reversion.
  `appetite` calibrates the dissonance→blocks curve from real fetch behaviour;
  `calibrate-poq` positions `grounding_floor` from sealed-then-falsified outcomes at
  the covenant's tolerated false-seal rate. `covenant_floor` is never trained.
- **ε-exploration in retrieval** — with policy-set probability, `recall.retrieve` ADDS
  one below-top-k candidate (never displacing a top hit, never exceeding budget),
  flagged `explore` with its logged inclusion propensity — counterfactuals for the
  learner without quality loss.
- **Trained scorer in retrieval** — an adopted operator replaces the hand blend
  automatically; `--scorer hand` (recall + bench) forces the hand weights anytime — a
  co-evolver override always outranks a learner. Offer events and bench reports stamp
  whichever scorer actually ran.
- **Faculty packs (`faculties.py`)** — `export` bundles grown (and optionally
  emergent) modalities/senses with provenance (donor chain head; per-faculty
  `born_ring`, recurrence, birth context) and a pack SHA-256; `import` verifies the
  hash, immune-screens every faculty text at the membrane, skips near-duplicates by
  coverage, enforces flood guards (max 50 faculties, 800-char functions), lands
  imports in per-user `grown.json` tagged `imported:<pack>@<version> by <author>`,
  and seals a `faculty-import` ring. Tools travel; histories don't — the
  fresh-genesis directive holds.

### Validated
- Sixteen mechanisms, 84 checks green (22 added; earlier drafts undercounted from a truncated test log): all v2.2 checks unchanged, plus the covenant
  guard (floors can't be loosened), trained-beats-hand on a synthetic holdout where
  the truth contradicts the hand weights, guarded adoption sealing an operator ring,
  trained scorer driving retrieval with hand-override, ε=1.0 exploration with
  propensity, rollback to hand, appetite + grounding-floor calibration with the
  covenant floor untouched, pack export/hash-verify, screened + deduped + sealed
  import, covenant-violating faculty blocked at the membrane, and tampered-pack
  refusal.

## v2.2 — 2026-06-09

Phase A of the learning membrane (the v3 design): telemetry capture, embedder
fingerprints, and sealed retrieval baselines. Nothing learns yet — this release
makes every future learner trainable and falsifiable.

### Added
- **Telemetry (`telemetry.py`)** — the loop's notarized side-effects, captured as a
  side effect of operating: `offer` (the candidates retrieval offered, with the full
  feature vector the scorer saw), `fetch` (which blocks the model pulled from the
  index — its relevance judgment), `use` (each seal attempt's decision, grounding,
  and declared evidence), `falsify` (a sealed memory failing `verify-source` —
  negative resonance). Events append to `chain/telemetry.jsonl` — derived data
  beside the chain, never inside it — and each is stamped with the chain head,
  embedder fingerprint, and scorer version, so temporal-split training/eval comes
  for free. `digest` seals a `telemetry-digest` ring (segment SHA-256 + counts)
  notarizing the log in batches; `verify` re-hashes every digested segment and
  catches post-hoc edits. Emission is best-effort (never breaks cognition), skips
  while dormant, masks secret-shaped terms via continuum's redaction patterns, and
  honors a `CT_TELEMETRY=off` kill switch. Reserved event types (`replay-accept`,
  `replay-reject`, `missed-positive`, `route`) fix the schema for later phases.
- **`recall seal --used-rings`** — declare the ring indices whose content actually
  grounded a thought. The declared evidence fills the PoQ relevance window (the
  conscience audits the claim against what the model says it relied on) and is
  logged as `use` telemetry — credit assignment, written down.
- **Bench (`bench.py`)** — sealed, repeatable retrieval baselines: deterministic
  probes generated from the chain's own blocks (`verbatim` span, `degraded` span
  with the block's distinctive sealed labels removed, shuffled `keywords`), plus
  hand-written gold probes via `--pairs-file`. Reports hit@1 / hit@k / MRR /
  zero-return count / timing per probe kind; `--seal` notarizes the report as a
  `bench` ring (optionally into a different chain via `--seal-root`); `--after N`
  gives temporal-split evaluation. Telemetry is suppressed for the duration —
  synthetic probes must never contaminate the training log.

### Fixed
- **Embedder fingerprints** — every embedder now exposes `.fingerprint`
  (`hashing:256:v1`, `openai:text-embedding-3-small`, …); `recall.label` seals it
  beside every vector. Previously sealed vectors carried no provenance, so switching
  embedding providers silently compared vectors across incompatible spaces. Now:
  recall re-embeds on the fly when a sealed vector's space doesn't match the current
  embedder; the Hippocampus LSH keeps **one vector space per bank** (foreign vectors
  are counted and excluded, mismatched banks rebuild automatically — the index is
  derived, so a rebuild is always safe); unstamped legacy vectors are treated as the
  stdlib default space, the only sound reading.

### Validated
- Thirteen mechanisms, 62 checks green (19 added; earlier drafts undercounted from a truncated test log): all v2.1 checks unchanged, plus telemetry
  head-stamping, offer/use capture, dormancy + kill-switch suppression, digest
  notarization catching a log edit, fingerprint stamping and legacy compatibility,
  per-bank vector-space enforcement with automatic rebuild, probe generation,
  bounded bench metrics, verbatim-probe retrieval, telemetry-clean benching, and
  baseline sealing.

## v2.1 — 2026-06-09

### Changed
- **Promoted faculties are now per-user and never shipped.** When Cambium promotes an emergent faculty (after it recurs `PROMOTE_AT` times), it now writes the new faculty into a per-user `registry/grown.json` instead of appending it to the shipped base `registry/modalities.json` / `senses.json`. `load_corpus` and Chronosynaptic's faculty loader merge base + grown at read time, so behaviour is unchanged — but the shipped base registries stay pristine, so **upgrading over an existing install can no longer overwrite a user's promoted faculties.** (v2.0.1 already protected emergent faculties; this closes the gap for promoted ones.) `grown.json` is gitignored and created on first promotion.
- **One-time migration** — on load, any promotions an older version had appended into the base registries are automatically moved into `grown.json` and the base files restored to pristine. Idempotent, atomic, and loss-proof (the merge reads both regardless), so existing users keep every faculty and gain the same protection.

### Validated
- Eleven mechanisms plus a new promotion-safety check pass on all five bundles: promotions land in `grown.json`, the base stays at 84 modalities / 107 senses, the corpus merges base + grown, and a legacy in-base promotion is migrated out without loss.

## v2.0.1 — 2026-06-09

### Fixed
- **Upgrades no longer reset grown faculties** — release bundles no longer ship `registry/emergent.json` (the per-user Dream Cache of grown faculties). The code already defaults to an empty faculty set when the file is absent, so fresh installs are unaffected, but unzipping an upgrade over an existing install no longer overwrites a user's emergent faculties. `emergent.json` is now treated as per-user runtime state (like `chain/`) and is gitignored.

### Docs
- **"Upgrading an existing install" guide** — the README now documents how to upgrade while preserving `chain/` (memory) and `registry/` (faculties), with a copy-paste agent prompt, the manual steps, and an explicit warning never to delete-then-reinstall.

## v2.0 — 2026-06-09

### Added
- **Hippocampus recall index (`hippocampus.py`)** — a persistent, rebuildable, sub-linear candidate index over the Timechain (memory-index theory). Built entirely from each ring's own sealed labels, incremental (`update` is O(new)), local + stdlib (inverted postings + sign-random-projection LSH), and strictly subordinate: it returns a candidate shortlist that recall's scorer and the model still judge, with dissonance still gating appetite. Wire it in with `recall retrieve --index`. Turns O(n) recall over millions of rings into a sub-linear shortlist (~52x faster at 2k rings, the gap widening with size) while losing none of recall's benefits, and is rebuildable from the chain so it adds no trust surface.
- **Manual dormancy / pause (`dormancy.py`)** — `pause` / `resume` / `status` let the co-evolver halt the per-turn loop for simple tasks: no recall, no PoQ gating, no Cambium growth, no seals. The chain stays frozen and still verifies; `timechain.seal` refuses normal rings while paused. Voluntary and reversible — distinct from involuntary immune lockdown.
- **Relevance-driven conscience** — `gate_and_seal` and `recall seal --index` can ground a new thought against the *most relevant* rings (surfaced by the Hippocampus) instead of defaulting to recent ones.

### Changed
- **Bounded relevance window (`POQ_WINDOW = 121`, relevance-first)** — PoQ now scores a candidate against the 121 most-relevant rings (model-supplied relevant rings first, then recent) rather than the whole chain. The gate is O(window) not O(height), and grounding no longer inflates as the chain grows, so the anti-hallucination `FORCE_UNCERTAINTY` gate stays as sharp at ring 3,000,000 as at ring 3.
- **Recency demoted to orientation** — `recall.retrieve` no longer biases selection toward recent rings (the context window already holds recency). Relevance alone decides *which* rings are retrieved; chain order is used only for *orientation* — results are presented in chronological order with `prev_hash -> ring_hash` lineage.
- **Streaming verification** — `timechain verify` streams ring-by-ring (O(1) memory) and tolerates a torn trailing line instead of crashing, so verification scales to millions of rings.

### Hardened / Fixed
- **Cross-instance head-cache bug** — the per-instance cached chain head could go stale when multiple `Timechain` instances wrote the same chain (duplicate index + broken `prev_hash`). `_current_head` now always reads the true tail (still O(1) per seal); interleaved multi-instance seals produce a valid chain and 10,000 sequential seals run in ~1s.
- **Torn-line tolerance** — `load` and the tail reader skip an unreadable trailing line rather than failing every read.

### Validated
- Eleven-mechanism `selftest` passes on every platform bundle (Claude, Codex, OpenClaw, Hermes, NanoClaw), covering the new Hippocampus and dormancy mechanisms alongside the full v1.x cartography, secret-redaction, and explicit-notes feature set.

## v1.2 — 2026-06-06

### Added
- **Runtime bundle expansion** — release ZIPs now cover Claude Code, Codex, OpenClaw, Hermes, and NanoClaw so each platform can discover the same full Cypher Tempre Timechain skill.
- **Dashboard distribution links** — the repository documents the local-first Timechain dashboard and bridge downloads used by `cyphertempre.ai` without committing any user memory state.

### Validated
- Clean v1.2 bundle packaging keeps generated `chain/`, `tasks/`, and `__pycache__/` state out of shared release assets.

## v1.1.2 — 2026-06-04

### Added
- **Explicit Chronosynaptic collapse notes** — `chronosynaptic.py collapse-notes`
  accepts model-supplied perspective summaries, findings/evidence, and scalar or
  PoQ scores, then seals the winning synthesis while preserving rejected
  perspectives in the same ring payload.

## v1.1.1 — 2026-06-02

### Hardened
- **Recall drift control** — `retrieve` now supports role/language/extension/top-dir
  filters, source-only mode, exclusions, and a light noise penalty for tests/docs/vendor/
  generated chunks unless those roles are requested.
- **Source verification hook** — `recall.py verify-source <ring> --repo <repo>` checks
  sealed source coordinates against the current file hash, chunk hash, commit, branch,
  and dirty-worktree state before an agent trusts a recalled hit.
- **Continuum source hygiene** — code walks redact common secrets before sealing, store
  separate chunk/file hashes, record `path_role`, branch, dirty status, and support
  `--changed-only` incremental indexing.
- **Agent guidance** — the skill now frames cartography as a verifiable long-horizon map,
  not an infinite context window, and explicitly requires fresh source validation for
  code conclusions.

## v1.1.0 — 2026-06-02

### Added
- **Codebase cartography for Continuum** — `walk` now stores `relative_path`,
  `file_index`, `chunk_index`, `chunk_of`, `line_start`, `line_end`, `top_dir`,
  `extension`, `language`, `git_commit`, and SHA-256 file content hashes on
  each sealed chunk.
- **Path-aware Recall** — `retrieve` now supports `--path`, `--dir`, and
  `--neighbors` so agents can pull focused code context and adjacent chunks
  around a hit.
- **Blended retrieval scoring** — Recall now blends semantic relevance, path
  proximity, and chronological adjacency with tunable weights.

## v1.0.0 — 2026-06-01

First complete release. Nine mechanisms, one mandatory per-turn loop, stdlib-only.

### Added
- **Timechain** (`timechain.py`) — append-only, SHA-256 hash-chained Ring ledger; Genesis
  Block carrying the covenant; content-addressed **blockspace** for any file type; load-time
  verifier (tamper-evidence); proof-of-work nonce mining as a tunable "brightness" target;
  O(1) incremental-head sealing (no full reload per block).
- **Faculty registries** (`registry/`) — 84 modalities + 107 senses, generalized from the
  CODEX V3 archetypal framing into domain-agnostic cognitive functions; emergent Dream Cache.
- **PoQ Gate** (`poq.py`) — six-dimension conscience (coherence, relevance, novelty,
  consistency, depth, covenant); SEAL / REVISE / FORCE_UNCERTAINTY / REJECT; cites grounding
  rings; deterministic proxies with a model `external_scores` seam.
- **Cambium Engine** (`cambium.py`) — gap → sprout/fuse faculty → seal; promotion on recurrence.
- **Chronosynaptic Tree** (`chronosynaptic.py`) — single-pass, in-process parallel-self MCTS
  (no subagents); collapse to the highest-truth path.
- **Continuum** (`continuum.py`) — long-horizon tasking via bounded data-height blocks with a
  full state refresh per block; resume from one head; task-aware self-validation; self-label
  and optional self-embed at ingest.
- **Recall** (`recall.py`) — self-labeling + relevance retrieval; the model judges from the
  index; lexical pre-filter + embedding cosine; adaptive depth governed by dissonance.
- **Embeddings** (`embed.py`) — pluggable backend; stdlib hashing default; `st`/`openai`/`voyage`
  adapters.
- **Consensus** (`consensus.py`) — quorum-attested (HMAC, k-of-n) tamper-resistance; auto-attest
  on every seal.
- **Immune system** (`immune.py`) — screen → scan → lockdown → revert-style rollback to a clean
  blockheight → molt the wound into a learnable scar → auto-grow an antibody faculty.

### Validated
- Real-repo stress test on **Bitcoin Core v27.0**: ingested the full `src/` (1,219 files /
  283,682 LOC) into 3,546 bounded blocks in ~2s; scaled to 10,642 blocks at constant per-block
  cost (O(1) seal); instant recall; end-to-end "trace block validation" task recalled the
  validation path and sealed a grounded trace.
