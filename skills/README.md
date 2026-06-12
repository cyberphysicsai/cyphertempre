# Skills Directory

This directory contains five labeled, self-contained Cypher Tempre skill
variants. Each variant includes the same reusable stdlib Python helpers and
registries, plus a runtime-specific `SKILL.md`.

| Runtime label | Path | Notes |
|---|---|---|
| Claude skill version | `claude/cypher-tempre-self-model/` | Claude Code compatible `SKILL.md` bundle. |
| Codex skill version | `codex/cypher-tempre-self-model/` | Codex compatible bundle with `agents/openai.yaml` metadata. |
| OpenClaw skill version | `openclaw/cypher-tempre-self-model/` | OpenClaw compatible bundle with OpenClaw frontmatter and `.clawhubignore`. |
| Hermes skill version | `hermes/cypher-tempre-self-model/` | Hermes-discoverable bundle copied from the OpenClaw implementation. |
| NanoClaw skill version | `nanoclaw/cypher-tempre-self-model/` | NanoClaw-discoverable bundle copied from the OpenClaw implementation. |

## Shared file set

Each runtime bundle labels its files through the path prefix above and contains:

- `SKILL.md` - runtime-specific skill instructions.
- `README.md` - runtime-specific human overview and install note.
- `VERSION`, `LICENSE`, `CHANGELOG.md` - package metadata.
- `timechain.py`, `poq.py`, `cambium.py`, `chronosynaptic.py`, `continuum.py`, `recall.py`, `embed.py`, `consensus.py`, `immune.py`, `selftest.py` - reusable stdlib helpers.
- `registry/modalities.json`, `registry/senses.json`, `registry/emergent.json` - faculty registries.

Generated `chain/` and `tasks/` directories are ignored so shared bundles do not
ship someone else's memory ledger.

## Codebase cartography hardening

The shared `continuum.py` and `recall.py` helpers support long-horizon code audits
without pretending to create infinite context. Continuum stores source coordinates,
file/chunk hashes, path roles, branch metadata, redaction state, and task progress.
Recall can filter by path, role, language, extension, and neighbors, then
`verify-source` checks a retrieved ring against the live repo before an agent trusts it.
