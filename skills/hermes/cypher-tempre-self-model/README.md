# Cypher Tempre Timechain Self-Model

**Runtime label:** Hermes skill version.

This is the Hermes bundle for Cypher Tempre: a persistent, verifiable,
self-healing cognitive self-model for an AI agent. It is stdlib-only Python,
uses Hermes-discoverable frontmatter, and ships without generated memory state.

## Install

Copy this folder into Hermes's configured skills directory:

```bash
cp -R cypher-tempre-self-model /path/to/hermes/skills/
```

Refresh Hermes's skill list, then initialize a fresh chain inside the copied
bundle:

```bash
python3 timechain.py init --name Hermes
python3 selftest.py
```

See `SKILL.md` for the full per-turn protocol.
