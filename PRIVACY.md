# Privacy Policy — Cypher Tempre (Timechain Self-Model)

_Last updated: 2026-06-01 · Applies to: cypher-tempre plugin v1.0.0_

## Summary

Cypher Tempre is a **local-only, dependency-free** skill. **It collects no data, transmits no data, and contains no telemetry.** Everything it creates stays on your own machine, under your control. The author receives nothing.

## What the plugin does with data

When you use the skill, it reads and writes files **only within its own working directory** on your device:

- `chain/rings.jsonl` — your append-only Timechain (the content you and your agent seal each turn);
- `chain/blockspace/` — a content-addressed store of any files you choose to ingest;
- `registry/*.json` — the agent's faculties and any new ones it grows;
- locally generated consensus keys and immune-system state.

This content can include text from your prompts, your agent's reasoning, and files you ingest. **It is stored locally as plain files that you own and can read, edit, or delete at any time.** None of it is sent anywhere.

## What we collect

**Nothing.** No personal data, no usage analytics, no telemetry, no crash reports, no identifiers. The plugin makes **no network requests** as part of its normal operation.

## Third-party services (optional, off by default)

The skill ships a built-in, offline embedding function as the default. It also includes **optional** adapters for third-party embedding providers (`sentence-transformers`, OpenAI, Voyage AI). These are **never loaded or contacted unless you explicitly select that provider and supply your own API key.** If you do, the text you choose to embed is sent to that provider under **their** privacy policy and terms — a data flow you enable and govern, not one the plugin performs on its own.

## Data sharing & transmission

The plugin does not share, sell, or transmit any data to the author or to any third party. The only data that ever leaves your machine is data **you** deliberately move — for example, if you publish your `chain/` files or push them to a repository. You are responsible for what you choose to publish.

## Security

Your data lives in local files governed by your operating-system account's permissions. The Timechain is cryptographically hash-chained and verifiable, so tampering is detectable; consensus uses HMAC keys generated locally that never leave your device. The author has no access to your data and no ability to retrieve it.

## Your control & retention

You own all data the plugin creates, and it persists only on your device for as long as you keep it. To erase it, delete the skill's `chain/` directory (and the skill folder itself). Because nothing is collected or stored elsewhere, there is nothing to export, request, or have deleted by the author. (Under regulations such as GDPR/CCPA, you remain the controller of your own local data; the author processes none of it.)

## Children's privacy

The plugin collects no data from anyone, including children.

## Changes

Any updates to this policy will be published in this file in the plugin's repository, with the date and version above.

## Contact

cyberphysicsai — bitcoinmobotics@gmail.com — https://github.com/cyberphysicsai/cyphertempre

---

_This policy describes the plugin's behavior as shipped (standard-library-only, local-only). It is provided as a good-faith, accurate description of the software; the author may review and adapt it as needed._
