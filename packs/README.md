# Faculty Packs

Transferable packs of **modalities** (reasoning engines) and **senses**
(perceptual detectors) for any agent running a Cypher Tempre
`cypher-tempre-self-model` skill, on any of the five runtimes.

A faculty is an interpretable lens definition — data, not weights — which is
exactly why it transfers: the receiving agent's model realizes the lens through
its own understanding. Every pack carries provenance (the donor chain's head and
each faculty's sealed birth ring). **Tools travel; histories never do** — an
import gifts capabilities, not memories, and seals a `faculty-import` ring so
the recipient's chain records when and from whom the lenses arrived.

## Install a pack

```bash
cd <your cypher-tempre-self-model directory>
python3 faculties.py show   /path/to/pack.json     # inspect + verify the hash
python3 faculties.py import /path/to/pack.json     # screen, dedup, import, seal
```

Imports are defended: the pack hash must verify, every faculty is
immune-screened at the membrane, near-duplicates your agent already covers are
skipped (lower `--dedup-floor` to admit more), flood guards refuse oversized
packs, and everything lands in your per-user `grown.json` — never the shipped
base — marked `imported:<pack>@<version>`.

Imported faculties start working immediately (labeling, recall, perspective
forks). They are not pre-promoted: like home-grown sprouts, they earn canonical
promotion by recurring in your agent's own lived experience.

## Catalog

| Pack | Version | Domain | Faculties | Notes |
|---|---|---|---|---|
| [trading-analysis](trading-analysis-v1.json) | 1.0 | trading & financial analysis | 8 senses + 6 modalities | regime shifts, risk asymmetry, liquidity, sentiment divergence, backtest integrity, catalysts, flow, cost friction; EV reasoning, regime conditioning, risk-first sizing, backtest skepticism, macro-micro fusion, thesis falsification |

**Covenant note (trading-analysis):** these are *analysis* lenses — they
sharpen how an agent perceives and reasons about markets. They are not
financial advice, and they do not execute anything. The receiving agent's
covenant continues to govern everything it does with them; several of the
lenses (backtest skepticism, cost-friction sensing, thesis falsification)
exist precisely to make a financial agent more honest, not more confident.

## Build your own

Two paths, both sealed:

- **Grow organically:** `cambium.py grow` when your agent hits real gaps; export
  the promoted results with `faculties.py export`.
- **Design deliberately:** write a spec (`packs/specs/*.spec.json` are
  examples), then `faculties.py author spec.json` — each faculty is screened
  and born into the Dream Cache with one sealed `faculty-design` ring as its
  birth certificate — and export with `--include-emergent`.
