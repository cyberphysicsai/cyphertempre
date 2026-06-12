# Cypher Tempre Timechain Self-Model

**Runtime label:** Claude skill version.

This is the Claude Code bundle for Cypher Tempre: a persistent, verifiable,
self-healing cognitive self-model for an AI agent. It is stdlib-only Python and
ships without generated memory state.

## Install

Copy this folder into Claude Code's skills directory:

```bash
cp -R cypher-tempre-self-model ~/.claude/skills/
```

Start a new Claude Code session so the skill list refreshes. Initialize a fresh
chain inside the copied bundle:

```bash
python3 timechain.py init --name Claude
python3 selftest.py
```

See `SKILL.md` for the full per-turn protocol.
