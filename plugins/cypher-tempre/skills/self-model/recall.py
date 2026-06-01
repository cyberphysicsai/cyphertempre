#!/usr/bin/env python3
"""
Recall — self-labeling + relevance-realization retrieval over the Timechain.

As the chain grows past the context window, the agent cannot reread everything.
Recall lets it (1) self-label each block's contents at seal time using its own
senses and modalities, and (2) retrieve only the blocks genuinely relevant to a
new prompt — enough to inform the answer, never enough to bloat.

SELF-LABELING (at seal time, sealed INTO the block, immutable):
  Run the content through the faculty registry; the senses and modalities that
  *fire* on it become its labels, alongside salient keywords, identifier-like
  entities, a salience score, and the content's dissonance. Labels are the
  block's own handles for future relevance.

RELEVANCE REALIZATION (at recall time) — the MODEL is the judge:
  This skill is ALWAYS attached to a model, so relevance is realized by that model
  reading the compact self-labels + summaries (`index`) and recognizing — by
  understanding, not string overlap — which past blocks relate to the new prompt.
  It then `fetch`es those blocks. The labels are the scannable map of memory; the
  model is the one who sees what relates (paraphrase and all). `retrieve` below is
  ONLY a cheap pre-filter for chains so large their index will not fit in context —
  it narrows the field; it is never the arbiter of relevance.

SMOOTH, ADAPTIVE DEPTH (no bloat):
  How many blocks to pull is governed by DISSONANCE (the need signal): low
  dissonance (the query is already well-covered) -> retrieve few or none; high
  dissonance -> retrieve more, up to a relevance threshold and a token budget.
  PoQ then validates downstream whether the retrieved context was sufficient.

Faculties are loaded from this script's own dir (the skill registry). The chain
to search is given by --root, so you can recall over any task/identity chain.

Stdlib only. Python 3.8+.  Builds on timechain.py, cambium.py, poq.py.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from timechain import Timechain
from cambium import load_corpus, detect_gap
from poq import tokens, jaccard, clamp, gate_and_seal

ENTITY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


def approx_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def _strings(obj):
    out = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _strings(v)
    return out


def block_text(ring) -> str:
    # Score/label on the block's DISTINCTIVE content, not its labels or the rolling
    # task state (objective + findings repeat across continuum blocks and would
    # swamp the signal — that boilerplate must not pollute relevance).
    payload = {k: v for k, v in ring.get("payload", {}).items()
               if k not in ("labels", "state", "poq_verdict")}
    return " ".join(_strings(payload))


def entities(text, cap=12):
    ents = set()
    for w in ENTITY_RE.findall(text):
        core = w.strip(".")
        if len(core) > 2 and (("_" in core) or any(c.isupper() for c in core[1:])
                              or ("." in core) or any(c.isdigit() for c in core)):
            ents.add(core)
    return sorted(ents)[:cap]


def keywords(text, k=10):
    return [w for w, _ in Counter(tokens(text)).most_common(k)]


class Recall:
    def __init__(self, chain_root, registry_root=None, embedder=None):
        self.tc = Timechain(chain_root)
        self.corpus = load_corpus(registry_root or Path(__file__).resolve().parent)
        self.embedder = embedder
        if isinstance(self.embedder, str):
            import embed as _embmod
            self.embedder = _embmod.get_embedder(self.embedder)

    def label(self, content, context=""):
        """Self-label content: which senses/modalities fire, plus keywords,
        entities, salience, and dissonance."""
        gap = detect_gap(self.corpus, content, context)
        acts = gap["_acts"]
        senses = [{"id": f["id"], "name": f["name"]} for n, f in acts if f["kind"] == "sense"][:5]
        mods = [{"id": f["id"], "name": f["name"]} for n, f in acts if f["kind"] == "modality"][:5]
        ents = entities(content)
        kws = keywords(content)
        salience = clamp(50 + 9 * len(ents) + min(120, 3 * len(set(tokens(content)))))
        lab = {"senses": senses, "modalities": mods, "keywords": kws,
               "entities": ents, "salience": salience, "dissonance": gap["dissonance"]}
        if self.embedder is not None:          # self-embed at ingest -> instant cosine recall later
            lab["embedding"] = self.embedder.embed(content)
        return lab

    def block_labels(self, ring):
        return ring.get("payload", {}).get("labels") or self.label(block_text(ring))

    def retrieve(self, query, context="", budget_tokens=1000, max_blocks=8,
                 relevance_fn=None, embed=False):
        if embed and self.embedder is None:           # default to the stdlib embedder
            import embed as _embmod
            self.embedder = _embmod.get_embedder("hashing")
        rings = self.tc.load()
        q = self.label(query, context)                # also embeds the query if embedder is set
        qS = {s["id"] for s in q["senses"]}
        qM = {m["id"] for m in q["modalities"]}
        qK, qE = set(q["keywords"]), set(q["entities"])
        qtok = set(tokens(query + " " + context))
        dissonance = q["dissonance"]
        qv = q.get("embedding") if embed else None
        _cos = None
        if qv is not None:
            import embed as _embmod
            _cos = _embmod.cosine

        scored = []
        n = max(1, len(rings) - 1)
        for r in rings:
            if r["index"] == 0:                       # skip the genesis/identity block
                continue
            lab = self.block_labels(r)
            # CONTENT signal is the discriminator, in priority order:
            if relevance_fn is not None:              #  (1) explicit model/embedding judge
                content = 9.0 * float(relevance_fn(query, block_text(r), lab))
            elif qv is not None:                      #  (2) EMBEDDING cosine (sealed vector, else on the fly)
                bvec = lab.get("embedding") or self.embedder.embed(block_text(r))
                content = 9.0 * _cos(qv, bvec)
            else:                                     #  (3) lexical fallback (literal overlap only)
                bK, bE = set(lab.get("keywords", [])), set(lab.get("entities", []))
                btok = (bK | bE) if r.get("payload", {}).get("labels") else set(tokens(block_text(r)))
                content = 5.0 * jaccard(qE, bE) + 3.0 * jaccard(qK, bK) + 4.0 * jaccard(qtok, btok)
            if content <= 0.0:                        # no relatedness -> skip (prevents bloat)
                continue
            bS = {s["id"] for s in lab.get("senses", [])}
            bM = {m["id"] for m in lab.get("modalities", [])}
            faculty = 0.7 * len(qS & bS) + 0.7 * len(qM & bM)   # shared lenses: secondary booster
            score = content + 0.5 * faculty + 0.4 * (lab.get("salience", 0) / 255) + 0.2 * (r["index"] / n)
            scored.append((score, r, lab))
        scored.sort(key=lambda x: x[0], reverse=True)

        # appetite: dissonance is the need signal. Low need -> pull little/none.
        if dissonance < 50:
            appetite = 0
        else:
            appetite = max(1, round(max_blocks * dissonance / 255))
        top = scored[0][0] if scored else 0.0
        threshold = max(0.6, 0.5 * top)               # absolute floor + relative: no junk, no bloat

        chosen, used = [], 0
        for score, r, lab in scored:
            if len(chosen) >= appetite or score < threshold:
                break
            excerpt = " ".join(block_text(r).split()[:60])
            cost = approx_tokens(excerpt)
            if used + cost > budget_tokens:
                break
            chosen.append({
                "index": r["index"], "type": r["ring_type"], "score": round(score, 2),
                "labels": {"senses": [s["name"] for s in lab.get("senses", [])[:3]],
                           "modalities": [m["name"] for m in lab.get("modalities", [])[:3]],
                           "keywords": lab.get("keywords", [])[:6]},
                "excerpt": excerpt[:260],
            })
            used += cost
        return {"query_labels": q, "dissonance": dissonance, "appetite": appetite,
                "threshold": round(threshold, 2), "considered": len(scored),
                "returned": len(chosen), "budget": budget_tokens, "tokens_used": used,
                "blocks": chosen}

    def seal(self, ring_type, summary, context="", external_scores=None, difficulty=0, files=None):
        labels = self.label(summary, context)
        verdict, ring = gate_and_seal(self.tc, summary, context, ring_type=ring_type,
                                      difficulty=difficulty, external_scores=external_scores,
                                      files=files, extra_payload={"labels": labels})
        return verdict, ring, labels


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_labels(lab, indent="  "):
    print(f"{indent}senses    : {', '.join(s['name'] for s in lab['senses']) or '-'}")
    print(f"{indent}modalities: {', '.join(m['name'] for m in lab['modalities']) or '-'}")
    print(f"{indent}keywords  : {', '.join(lab['keywords'][:8]) or '-'}")
    print(f"{indent}entities  : {', '.join(lab['entities'][:8]) or '-'}")
    print(f"{indent}salience  : {lab['salience']}   dissonance: {lab['dissonance']}")


def cmd_label(args):
    lab = Recall(args.root, args.registry_root).label(args.text, args.context or "")
    print("self-labels:")
    _print_labels(lab)


def cmd_retrieve(args):
    rec = Recall(args.root, args.registry_root, embedder=(args.provider if args.embed else None))
    r = rec.retrieve(args.query, args.context or "", budget_tokens=args.budget,
                     max_blocks=args.max, embed=args.embed)
    if args.embed:
        print(f"[embedding recall: {rec.embedder.name}]")
    print("query self-labels:")
    _print_labels(r["query_labels"])
    print(f"\nneed: dissonance {r['dissonance']} -> appetite {r['appetite']} block(s)   "
          f"(threshold {r['threshold']}; considered {r['considered']})")
    print(f"returned {r['returned']} block(s), ~{r['tokens_used']}/{r['budget']} tokens "
          f"(label-overlap first, similarity second):")
    for b in r["blocks"]:
        print(f"  #{b['index']:>3} [{b['type']}] score {b['score']}  "
              f"senses={b['labels']['senses']} kw={b['labels']['keywords']}")
        print(f"        “{b['excerpt'][:150]}…”")
    if not r["blocks"]:
        print("  (nothing above threshold — the agent does not need past blocks for this)")


def cmd_seal(args):
    poq = {d: getattr(args, d) for d in ["coherence", "relevance", "novelty", "consistency", "depth", "covenant"]
           if getattr(args, d) is not None}
    verdict, ring, labels = Recall(args.root, args.registry_root).seal(
        args.type, args.summary, context=args.context or "",
        external_scores=poq or None, difficulty=args.difficulty)
    print(f"PoQ decision: {verdict['decision']}")
    if ring:
        print(f"sealed self-labeled Ring {ring['index']}  {ring['ring_hash'][:16]}..")
        _print_labels(labels)
    else:
        print("not sealed (verdict was not SEAL)")
        sys.exit(2)


def cmd_index(args):
    """The model-facing MAP OF MEMORY: a compact summary + labels per block. The
    model reads this and decides, by understanding, which blocks relate — then
    `fetch`es them. This is where relevance realization actually happens."""
    rec = Recall(args.root, args.registry_root)
    for r in rec.tc.load():
        if r["index"] == 0:
            continue
        lab = rec.block_labels(r)
        summary = " ".join(block_text(r).split()[: args.words])
        print(f"#{r['index']:>3} [{r['ring_type']}] need~{lab['dissonance']}  {summary[:150]}")
        print(f"      kw: {', '.join(lab['keywords'][:7]) or '-'}  | entities: {', '.join(lab['entities'][:5]) or '-'}")


def cmd_fetch(args):
    """Pull the full content of the blocks the model judged relevant (budget-bounded)."""
    rec = Recall(args.root, args.registry_root)
    rings = {r["index"]: r for r in rec.tc.load()}
    used = 0
    for i in args.ids:
        r = rings.get(i)
        if not r:
            print(f"#{i}: not found"); continue
        ex = " ".join(block_text(r).split()[: args.words])
        cost = approx_tokens(ex)
        if used + cost > args.budget:
            print(f"(budget {args.budget} tokens reached)"); break
        used += cost
        print(f"#{i} [{r['ring_type']}] {r['ring_hash'][:12]}..")
        print(f"  {ex[: args.words * 8]}\n")
    print(f"(fetched ~{used}/{args.budget} tokens)")


def build_parser():
    skill_dir = Path(__file__).resolve().parent
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=skill_dir, help="chain to search/seal into")
    common.add_argument("--registry-root", type=Path, default=None, help="faculty registry dir (default: skill dir)")

    p = argparse.ArgumentParser(description="Recall — self-labeling + relevance-realization retrieval.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("label", parents=[common], help="self-label a piece of content")
    pl.add_argument("text")
    pl.add_argument("--context", default=None)
    pl.set_defaults(func=cmd_label)

    pr = sub.add_parser("retrieve", parents=[common], help="retrieve relevant past blocks for a query")
    pr.add_argument("query")
    pr.add_argument("--context", default=None)
    pr.add_argument("--budget", type=int, default=1000, help="token budget for retrieved excerpts")
    pr.add_argument("--max", type=int, default=8, help="max blocks (appetite cap)")
    pr.add_argument("--embed", action="store_true", help="rank by embedding cosine, not lexical overlap")
    pr.add_argument("--provider", default="hashing", help="embedding backend: hashing|st|openai|voyage")
    pr.set_defaults(func=cmd_retrieve)

    ps = sub.add_parser("seal", parents=[common], help="self-label then PoQ-gate-seal a block")
    ps.add_argument("summary")
    ps.add_argument("--context", default=None)
    ps.add_argument("--type", default="experience")
    ps.add_argument("--difficulty", type=int, default=0)
    for d in ["coherence", "relevance", "novelty", "consistency", "depth", "covenant"]:
        ps.add_argument(f"--{d}", type=int, default=None)
    ps.set_defaults(func=cmd_seal)

    pi = sub.add_parser("index", parents=[common], help="model-facing map: summary+labels per block (the model judges relevance from this)")
    pi.add_argument("--words", type=int, default=22)
    pi.set_defaults(func=cmd_index)

    pf = sub.add_parser("fetch", parents=[common], help="fetch full content of the blocks the model chose as relevant")
    pf.add_argument("ids", nargs="+", type=int)
    pf.add_argument("--words", type=int, default=120)
    pf.add_argument("--budget", type=int, default=1500)
    pf.set_defaults(func=cmd_fetch)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
