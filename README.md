# cyphertempre — a Claude Code plugin marketplace

Distributes **Cypher Tempre**, a persistent, verifiable, self-healing **Timechain self-model**
for AI agents. Stdlib-only Python; every install forges its **own** genesis (no inherited chain).

## Install (any Claude Code user, two commands)

```bash
/plugin marketplace add cyberphysicsai/cyphertempre
/plugin install cypher-tempre@cyphertempre
```

Then invoke the skill as **`/cypher-tempre:self-model`** (model-invoked too). On first use the
agent runs `python3 timechain.py init --name <YourName>` to create its own Ring 0.
Update later with `/plugin marketplace update cyphertempre`.

## Other ways to install

- **Tarball / no marketplace:** `tar -xzf cypher-tempre-self-model-1.0.0.tar.gz -C ~/.claude/skills/`
- **Project skill:** commit `plugins/cypher-tempre/skills/self-model/` into a repo's
  `.claude/skills/self-model/` — anyone running Claude Code in that repo gets it (web included).
- **Local dev:** `claude --plugin-dir ./plugins/cypher-tempre`

## Timechain Dashboard Bridge

Users can audit their own local Timechain files from `https://cyphertempre.ai`
with the local bridge package:

[`downloads/cyphertempre-dashboard-local-bridge-accountfix.zip`](downloads/cyphertempre-dashboard-local-bridge-accountfix.zip)

The bridge runs on the user's machine and reads that user's local
`cypher-tempre-self-model` files, not the site owner's files. See
[`downloads/README.md`](downloads/README.md) for the run commands.

## What's inside

Plugin `cypher-tempre` → skill `self-model`. Nine mechanisms, one mandatory per-turn loop:

> 🫚 memory · conscience · 🌿 faculties · growth · foresight · endurance · relevance(+embeddings) · integrity · immunity

See [`plugins/cypher-tempre/skills/self-model/README.md`](plugins/cypher-tempre/skills/self-model/README.md)
for the full architecture, and `SKILL.md` for the operating protocol. Run `python3 selftest.py`
inside the skill to validate all nine mechanisms end-to-end.

## Repo layout

```
cyphertempre/
├── .claude-plugin/marketplace.json     # the catalog
└── plugins/cypher-tempre/
    ├── .claude-plugin/plugin.json       # plugin manifest (v1.0.0, MIT)
    └── skills/self-model/               # SKILL.md + 9 modules + selftest + base registry
```

## Privacy

Local-only, collects nothing, transmits nothing — see [`PRIVACY.md`](PRIVACY.md).

## License

MIT — see `LICENSE`. © 2026 Cypher Tempre (cyberphysicsai).
