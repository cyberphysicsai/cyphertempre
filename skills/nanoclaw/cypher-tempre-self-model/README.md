# Cypher Tempre Timechain Self-Model

**Runtime label:** NanoClaw skill version.

This is the NanoClaw bundle for Cypher Tempre: a persistent, verifiable,
self-healing cognitive self-model for an AI agent. It is stdlib-only Python,
uses NanoClaw-discoverable frontmatter, and ships without generated memory state.

## Install

Copy this folder into NanoClaw's configured workspace skills directory:

```bash
cp -R cypher-tempre-self-model /path/to/nanoclaw/skills/
```

Refresh NanoClaw's skill list, then initialize a fresh chain inside the copied
bundle:

```bash
python3 timechain.py init --name NanoClaw
python3 selftest.py
```

See `SKILL.md` for the full per-turn protocol.
