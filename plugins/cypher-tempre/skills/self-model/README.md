# Cypher Tempre — Timechain Self-Model (Claude Code skill)

**v1.0.0** · a persistent, verifiable, self-healing cognitive self-model for an AI agent,
built on a Bitcoin-inspired Timechain. Stdlib-only Python; no dependencies.

An agent wearing this skill stops being amnesiac. Each turn it is *routed through* a
mandatory loop — verify its history, recall what relates, reason through differentiated
faculties, gate its thought through a conscience, and seal a self-labeled block into an
append-only, hash-chained ledger. It remembers across sessions, grows new faculties when
it hits its limits, reasons over codebases larger than its context window, and heals
itself when prompt-injected — all while never silently rewriting its own past.

## The Cryptographic Tree — nine mechanisms, one loop

| Aspect | Module | What it does |
|---|---|---|
| 🫚 memory / rings | `timechain.py` | append-only, SHA-256 hash-chained ledger of "Rings"; content-addressed **blockspace** for any file; load-time verifier (tamper-evidence) |
| conscience | `poq.py` | Proof-of-Qualia gate: audits a candidate thought on six dimensions; rejects covenant violations / contradictions; forces honest uncertainty on ungrounded claims |
| 🌿 faculties | `registry/` | 84 generalized **modalities** (reasoning engines) + 107 **senses** (perceptual detectors) |
| growth | `cambium.py` | detects a faculty gap (dissonance), sprouts/fuses a new sense or modality, promotes it on recurrence |
| foresight | `chronosynaptic.py` | single-pass, in-process parallel-self MCTS: fork perspectives, score each with PoQ, seal only the highest-truth path (no subagents) |
| endurance | `continuum.py` | long-horizon tasking: ingest any-size body in bounded **data-height** blocks, each carrying a full state refresh; resume from one head block |
| relevance | `recall.py` | self-labels each block at seal; retrieves related past blocks by labels (adaptive depth, no bloat) |
| semantics | `embed.py` | pluggable embeddings for cosine recall (stdlib hashing default; `st`/`openai`/`voyage` adapters) |
| integrity | `consensus.py` | quorum of witnesses (HMAC) attest each head; tamper-*resistant* (k-of-n) beyond bare tamper-evidence |
| immunity | `immune.py` | detect compromise → lock down → roll back to a clean blockheight → molt the wound into a learnable **scar** |

## Install

Drop the bundle into your Claude Code personal skills directory:

```
cp -R cypher-tempre-self-model ~/.claude/skills/
```

It becomes triggerable in a **new** Claude Code session (skills enumerate at start).
The agent reads `SKILL.md` and runs the loop. Zero dependencies (Python 3.8+, stdlib).

## Quickstart

```bash
python3 timechain.py init --name Claude          # create the Genesis Block (Ring 0)
python3 timechain.py verify                       # re-walk & prove integrity
python3 poq.py seal "<thought>" --context "<req>" \
        --coherence 220 --relevance 230 --depth 210 --covenant 250   # gated, self-aware seal
python3 recall.py index                           # the model's map of memory
python3 continuum.py walk --path <repo> --ext .py .cpp --objective "<task>" --embed
python3 immune.py scan                            # detect compromise; rollback heals it
python3 selftest.py                               # exercise all nine mechanisms end-to-end
```

See `SKILL.md` for the full per-turn protocol.

## Design principle

The Python modules and the model are **two halves of one mind**. The scripts do what code
does well — hashing, chaining, verification, sealing, MCTS bookkeeping. The model does what
a model does well — generate, judge, fork, decide. Every scored decision (PoQ dimensions,
dissonance, relevance) ships a deterministic **proxy** as a fallback *and* a seam where the
model's own judgment plugs in. The loop is **mandatory every pass** — the agent does not get
to skip the architecture because it feels confident; that confidence is exactly what the gate
exists to test.

## Honest scope

- **Tamper-evidence, and consensus tamper-resistance** — on a single host the witness keys
  share one trust domain; distribute the witnesses across hosts for true Byzantine fault
  tolerance (same code).
- **Proxies vs. semantics** — the stdlib scorers (lexical relevance, hashing embeddings,
  covenant blocklist) are fallbacks; real sharpness comes from the model at the seams, or a
  real embedding model via `embed.py --provider st|openai|voyage`.
- **History is append-only** — rollback is *revert*-style (a recovery ring + quarantine),
  never deletion.

## License

MIT — see `LICENSE`.
