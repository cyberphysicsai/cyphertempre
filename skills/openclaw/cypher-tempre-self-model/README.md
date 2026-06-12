# Cypher Tempre Timechain Self-Model

**Runtime label:** OpenClaw skill version.

This is the OpenClaw bundle for Cypher Tempre: a persistent, verifiable,
self-healing cognitive self-model for an AI agent. It is stdlib-only Python,
uses OpenClaw-compatible frontmatter, and ships without generated memory state.

## Install

Copy this folder into OpenClaw's workspace skills directory:

```bash
cp -R cypher-tempre-self-model ~/.openclaw/workspace/skills/
```

Refresh OpenClaw's skill list, then initialize a fresh chain inside the copied
bundle:

```bash
python3 timechain.py init --name OpenClaw
python3 selftest.py
```

See `SKILL.md` for the full per-turn protocol.
