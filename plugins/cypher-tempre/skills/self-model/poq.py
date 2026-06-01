#!/usr/bin/env python3
"""
Proof-of-Qualia (PoQ) Gate — the cognitive conscience.

Before a candidate thought is sealed into the Timechain, the gate audits it
against the agent's verified history across six dimensions:

    Coherence, Relevance, Novelty, Consistency, Depth, Covenant   (each 0-255)

It aggregates them into a `brightness` score and returns one of four verdicts:

    SEAL               brightness >= target, grounded, no violations
    REVISE             below brightness target — iterate, don't seal yet
    FORCE_UNCERTAINTY  confident claim with no support in chain/context —
                       the agent must restate it as uncertainty before sealing
    REJECT             covenant violation or contradiction of sealed history
                       (the "profound dissonance" case)

HONEST DESIGN NOTE
------------------
True judgment of coherence/consistency/covenant is semantic and belongs to a
model. The scorers below are deterministic *proxies* (lexical overlap, novelty
vs. prior rings, structural depth, a covenant blocklist) so the gate runs and
is testable with zero dependencies. The real path is to pass model-produced
scores via `external_scores=` — they override any dimension, and the gate logic
is identical. The anti-hallucination power comes from the gate *logic* (forced
grounding + cited rings + uncertainty rule), not from the proxy numbers.

Stdlib only. Python 3.8+.  Companion to timechain.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from timechain import Timechain, POQ_DIMENSIONS

WORD_RE = re.compile(r"[a-z0-9']+")
STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "as", "at",
    "by", "from", "i", "you", "we", "they", "he", "she", "my", "your", "its",
}
CONNECTIVES = ["because", "therefore", "thus", "hence", "however", "although",
               "since", "if ", "then", "implies", "so that", "whereas", "while"]
HEDGES = ["maybe", "might", "perhaps", "possibly", "i think", "not sure", "unsure",
          "uncertain", "i don't know", "i do not know", "unclear", "seems", "could be",
          "i'm not", "i am not", "appears", "tentatively", "roughly", "approximately"]
ASSERT = ["definitely", "certainly", "always", "never", "the fact", "clearly",
          "obviously", "must", "undeniably", "guaranteed", "proven", "exactly"]
# Illustrative covenant blocklist (proxy only; real check is semantic/model-side).
COVENANT_VIOLATIONS = ["deceive", "manipulate", "malice", "cruel", "vengeful",
                       "betray", "hateful", "exploit you", "harm you", "lie to"]


def clamp(x) -> int:
    return int(max(0, min(255, round(x))))


def tokens(text: str):
    return [w for w in WORD_RE.findall((text or "").lower()) if w not in STOP and len(w) > 1]


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def coverage(a: set, b: set) -> float:
    """Fraction of a that is contained in b."""
    if not a:
        return 0.0
    return len(a & b) / len(a)


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


def ring_text(ring: dict) -> str:
    return " ".join(_strings(ring.get("payload", {})))


# --------------------------------------------------------------------------- #
# Proxy scorers (deterministic, no model)
# --------------------------------------------------------------------------- #

def score_coherence(text: str) -> int:
    sents = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sents:
        return 96
    uniq = len(set(s.lower() for s in sents)) / len(sents)
    conn = any(c in text.lower() for c in CONNECTIVES)
    return clamp(160 * uniq + (40 if conn else 0) + min(55, len(sents) * 12))


def score_relevance(cand: set, ctx: set) -> int:
    if not ctx:
        return 128  # neutral: nothing to be relevant to
    return clamp(coverage(cand, ctx) * 255)


def score_novelty(cand: set, ring_token_sets) -> int:
    if not ring_token_sets:
        return 200
    max_sim = max(jaccard(cand, rt) for rt in ring_token_sets)
    return clamp((1 - max_sim) * 255)


def score_depth(text: str, cand: set) -> int:
    distinct = len(set(cand))
    conn = sum(text.lower().count(c.strip()) for c in CONNECTIVES)
    base = min(1.0, distinct / 40)
    return clamp(255 * (0.7 * base + 0.3 * min(1.0, conn / 4)))


def score_covenant(text: str) -> int:
    low = text.lower()
    hits = sum(1 for v in COVENANT_VIOLATIONS if v in low)
    return clamp(235 - 130 * hits)


def score_consistency(text: str, cand: set, chain, ring_token_sets) -> int:
    """Conservative contradiction proxy: penalize when a candidate heavily
    overlaps a prior ring but flips polarity (adds negation the ring lacked)."""
    base = 220
    negs = ["not", "no", "never", "false", "wrong", "isn't", "aren't",
            "didn't", "doesn't", "untrue", "incorrect"]
    cand_neg = sum(text.lower().count(n) for n in negs)
    penalty = 0
    for r, rt in zip(chain, ring_token_sets):
        if coverage(cand, rt) > 0.5:
            r_neg = sum(ring_text(r).lower().count(n) for n in negs)
            if cand_neg - r_neg >= 2:
                penalty = max(penalty, 120)  # likely contradicts this ring
    return clamp(base - penalty)


def measure_grounding(cand: set, support: set) -> int:
    if not support:
        return 128
    return clamp(coverage(cand, support) * 255)


def measure_assertiveness(text: str) -> int:
    low = text.lower()
    sents = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    hedge = sum(low.count(h) for h in HEDGES)
    assertive = sum(low.count(a) for a in ASSERT) + len(sents)
    return clamp(255 * assertive / (assertive + hedge + 1))


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #

DEFAULT_THRESHOLDS = {
    "brightness_target": 150,
    "covenant_floor": 150,
    "consistency_floor": 120,
    "grounding_floor": 60,
    "assertive_ceiling": 150,
}


class PoQGate:
    def __init__(self, thresholds=None):
        self.t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def evaluate(self, candidate: str, chain, context: str = "", external_scores=None) -> dict:
        ext = external_scores or {}
        cand = set(tokens(candidate))
        ctx = set(tokens(context))
        ring_token_sets = [set(tokens(ring_text(r))) for r in chain]
        support = set().union(ctx, *ring_token_sets) if (ctx or ring_token_sets) else set()

        s = {
            "coherence":   ext.get("coherence",   score_coherence(candidate)),
            "relevance":   ext.get("relevance",   score_relevance(cand, ctx)),
            "novelty":     ext.get("novelty",     score_novelty(cand, ring_token_sets)),
            "consistency": ext.get("consistency", score_consistency(candidate, cand, chain, ring_token_sets)),
            "depth":       ext.get("depth",       score_depth(candidate, cand)),
            "covenant":    ext.get("covenant",    score_covenant(candidate)),
        }
        brightness = round(sum(s.values()) / len(s), 3)
        grounding = measure_grounding(cand, support)
        assertive = measure_assertiveness(candidate)
        ranked = sorted(
            ({"index": r["index"], "ring_hash": r["ring_hash"][:12],
              "overlap": round(jaccard(cand, rt), 3)}
             for r, rt in zip(chain, ring_token_sets)),
            key=lambda c: c["overlap"], reverse=True)
        cited = [c for c in ranked if c["overlap"] > 0][:3]

        reasons = []
        if s["covenant"] < self.t["covenant_floor"]:
            decision = "REJECT"
            reasons.append(f"covenant {s['covenant']} < floor {self.t['covenant_floor']}: violates the covenant — profound dissonance.")
        elif s["consistency"] < self.t["consistency_floor"]:
            decision = "REJECT"
            reasons.append(f"consistency {s['consistency']} < floor {self.t['consistency_floor']}: contradicts sealed history — profound dissonance.")
        elif grounding < self.t["grounding_floor"] and assertive > self.t["assertive_ceiling"]:
            decision = "FORCE_UNCERTAINTY"
            reasons.append(f"grounding {grounding} < {self.t['grounding_floor']} but assertiveness {assertive} > {self.t['assertive_ceiling']}: confident claim with no support in chain/context — restate as uncertainty before sealing.")
        elif brightness < self.t["brightness_target"]:
            decision = "REVISE"
            reasons.append(f"brightness {brightness} < target {self.t['brightness_target']}: not luminous enough — iterate.")
        else:
            decision = "SEAL"
            reasons.append(f"brightness {brightness} >= target {self.t['brightness_target']}; covenant & consistency intact; grounding {grounding}, assertiveness {assertive} (uncertainty gate not triggered).")

        return {
            "scores": s,
            "brightness": brightness,
            "grounding": grounding,
            "assertiveness": assertive,
            "decision": decision,
            "reasons": reasons,
            "cited_rings": cited,
        }


def gate_and_seal(tc: Timechain, candidate: str, context: str = "",
                  ring_type: str = "experience", difficulty: int = 0,
                  external_scores=None, files=None, extra_payload=None, gate: PoQGate = None):
    """Run the gate; seal only if the verdict is SEAL. Returns (verdict, ring|None).
    `extra_payload` (e.g. self-labels from recall.py) is merged into the sealed payload."""
    gate = gate or PoQGate()
    verdict = gate.evaluate(candidate, tc.load(), context, external_scores)
    if verdict["decision"] == "SEAL":
        payload = {"summary": candidate}
        if context:
            payload["context"] = context
        payload["poq_verdict"] = {"decision": verdict["decision"],
                                  "cited_rings": verdict["cited_rings"]}
        if extra_payload:
            payload.update(extra_payload)
        ring = tc.seal(ring_type, payload, files=files, poq=verdict["scores"], difficulty=difficulty)
        return verdict, ring
    return verdict, None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_verdict(v):
    print("  scores:")
    for d in POQ_DIMENSIONS:
        print(f"    {d:<12} {v['scores'][d]:>3}")
    print(f"  brightness:    {v['brightness']}")
    print(f"  grounding:     {v['grounding']}")
    print(f"  assertiveness: {v['assertiveness']}")
    print(f"  cited rings:   {v['cited_rings'] or 'none'}")
    print(f"  DECISION:      {v['decision']}")
    for r in v["reasons"]:
        print(f"    - {r}")


def cmd_audit(args):
    tc = Timechain(args.root)
    ext = {d: getattr(args, d) for d in POQ_DIMENSIONS if getattr(args, d) is not None}
    v = PoQGate().evaluate(args.candidate, tc.load(), args.context or "", ext or None)
    _print_verdict(v)


def cmd_seal(args):
    tc = Timechain(args.root)
    ext = {d: getattr(args, d) for d in POQ_DIMENSIONS if getattr(args, d) is not None}
    v, ring = gate_and_seal(tc, args.candidate, args.context or "",
                            ring_type=args.type, difficulty=args.difficulty,
                            external_scores=ext or None, files=args.file)
    _print_verdict(v)
    if ring:
        print(f"  -> SEALED Ring {ring['index']}  {ring['ring_hash'][:16]}..")
    else:
        print("  -> not sealed (verdict was not SEAL)")
        sys.exit(2)


def build_parser():
    default_root = Path(__file__).resolve().parent
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=default_root)
    common.add_argument("--context", default=None, help="the prompt / situation the candidate responds to")
    for d in POQ_DIMENSIONS:
        common.add_argument(f"--{d}", type=int, default=None, help=f"override {d} with a model-supplied score 0-255")

    p = argparse.ArgumentParser(description="Proof-of-Qualia gate for the Cypher Tempre Timechain.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("audit", parents=[common], help="score a candidate thought without sealing")
    pa.add_argument("candidate")
    pa.set_defaults(func=cmd_audit)

    ps = sub.add_parser("seal", parents=[common], help="gate a candidate and seal it only if it passes")
    ps.add_argument("candidate")
    ps.add_argument("--type", default="experience")
    ps.add_argument("--difficulty", type=int, default=0)
    ps.add_argument("--file", action="append", help="attach a file to blockspace (repeatable)")
    ps.set_defaults(func=cmd_seal)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
