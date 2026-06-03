# Changelog

## v1.0.2 — 2026-06-02

### Fixed
- **`continuum.py validate` no longer reports `COHERENT` on an empty/missing chain.** A
  0-ring chain has no invariants to violate, so `validate` returned a vacuous `COHERENT` —
  which masked a misconfigured `--root` (a wrong path silently "passed"). It now detects an
  empty tail (`_tail_ring() is None`) and returns `no chain at <path> — 0 rings (check
  --root)` with a non-zero exit. Surfaced while federating genome perspective-shards.

## v1.0.1 — 2026-06-02

### Fixed
- **`continuum.py` resume is now O(1).** `_head_state()` loaded the entire chain
  (`reversed(self.tc.load())`) just to read the last ring's state; it now reads only the
  tail ring via the `timechain._tail_ring()` head-cache (every Continuum block embeds a
  full state refresh, so the tail ring *is* the head state), with a reverse-scan fallback.
  Surfaced by a 309,481-ring genome chain: `resume` dropped from **8.77 s to 0.04 s
  (~220×)** with identical output. Seal and resume are now both O(1); `validate` stays
  O(n) (it must re-hash every ring).

### Validated
- **Whole human genome (GRCh38) cartography.** Streamed the full primary assembly
  (~3.10 Gbp) once with O(1) memory into a Continuum: 3,274 blocks at 1 Mbp windows, then
  **309,479 blocks at 10 kb windows** (~30× the prior block-count high) in 149.8 s at a
  flat ~2,050 blocks/s — O(1) seal confirmed past 300k rings. Genome-wide stats
  cross-checked against published values (GC 40.87 %, N-gaps 4.88 %, exact chromosome
  lengths, CpG O/E ≈ 0.24); chain self-validates `COHERENT`.

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
