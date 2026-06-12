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

# Bounded relevance window. PoQ scores a candidate against the POQ_WINDOW MOST
# RELEVANT rings — model-judged relevant blocks first, then the most recent ones
# fill the remaining budget — never the whole chain. Two payoffs: (1) the gate is
# O(window), not O(height); (2) grounding no longer INFLATES as the chain grows.
# Grounding = coverage(candidate, context + scored-rings); if "scored-rings" were
# the whole chain, a long chain would contain nearly every token and grounding ->
# 255 for anything, silently disabling the FORCE_UNCERTAINTY anti-hallucination
# gate. Bounding keeps the conscience as sharp at ring 3,000,000 as at ring 3. For
# chains <= POQ_WINDOW this is identical to scoring the whole chain.
POQ_WINDOW = 121

DEFAULT_THRESHOLDS = {
    "brightness_target": 150,
    "covenant_floor": 150,
    "consistency_floor": 120,
    "grounding_floor": 60,
    "assertive_ceiling": 150,
}


def policy_thresholds():
    """Thresholds split by KIND (the Phase B doctrine): the VALUES floors come from
    policy — they may only ever TIGHTEN, and are never trained (policy.py enforces
    the guard). The grounding floor may be CALIBRATED by the learner from
    sealed-then-falsified outcomes, positioned at the covenant's tolerated
    false-seal rate — data places the threshold, policy sets the tolerance."""
    t = dict(DEFAULT_THRESHOLDS)
    try:
        import policy as policymod
        pol = policymod.load_policy()
        t["covenant_floor"] = max(t["covenant_floor"], int(pol["values"]["covenant_floor"]))
        t["consistency_floor"] = max(t["consistency_floor"], int(pol["values"]["consistency_floor"]))
        cal = (pol.get("poq") or {}).get("calibrated")
        if cal and cal.get("grounding_floor") is not None:
            t["grounding_floor"] = int(cal["grounding_floor"])
        if cal and cal.get("assertive_ceiling") is not None:
            t["assertive_ceiling"] = int(cal["assertive_ceiling"])
    except Exception:
        pass                       # a broken policy file must never disable the gate
    return t


class PoQGate:
    def __init__(self, thresholds=None):
        self.t = {**policy_thresholds(), **(thresholds or {})}

    def evaluate(self, candidate: str, chain, context: str = "", external_scores=None,
                 ring_token_sets=None, span_guard=False) -> dict:
        ext = external_scores or {}
        cand = set(tokens(candidate))
        ctx = set(tokens(context))
        if ring_token_sets is None:                      # caching seam: a caller that scores
            ring_token_sets = [set(tokens(ring_text(r))) for r in chain]   # the same chain many
        # times (e.g. chronosynaptic's MCTS) tokenizes the window ONCE and passes it in,
        # turning O(iterations x depth x forks x height) into O(height) + O(evals).
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

        verdict = {
            "scores": s,
            "brightness": brightness,
            "grounding": grounding,
            "assertiveness": assertive,
            "decision": decision,
            "reasons": reasons,
            "cited_rings": cited,
        }
        if span_guard:
            # The HallucinationGuard microscope: ground each clause-sized span
            # against the window, so FORCE_UNCERTAINTY can demand hedging on the
            # SPECIFIC unsupported assertions (not smear doubt over the answer),
            # and so the sealed verdict carries computed span->ring credit.
            try:
                import guard as guardmod
                report = guardmod.guard_report(candidate, chain, context)
                verdict["span_grounding"] = guardmod.compact(report)
                if decision == "FORCE_UNCERTAINTY" and report["unsupported"]:
                    names = "; ".join(f"“{u[:70]}…”" if len(u) > 70 else f"“{u}”"
                                      for u in report["unsupported"][:3])
                    verdict["reasons"].append(
                        f"unsupported span(s) — hedge or evidence THESE specifically: {names}")
            except Exception:
                pass            # the microscope must never break the gate itself
        return verdict


def _ring_index(r):
    idx = r.get("index")
    return idx if idx is not None else 0


def relevance_window(tc: Timechain, window: int = POQ_WINDOW, relevant_rings=None) -> list:
    """The bounded set of AT MOST `window` rings the gate scores against — RELEVANCE
    FIRST. Model-judged `relevant_rings` (blocks the model recalled as pertinent) are
    taken first, because the model is the relevance judge; the remaining budget is then
    filled with the most recent rings (recency is only the default proxy for relevance
    when the model supplies none). So the window holds the `window` MOST RELEVANT rings,
    not merely the newest. Read is O(window) from the tail. window <= 0 -> whole chain
    (with any relevant_rings merged in)."""
    if not window or window <= 0:
        base = tc.load()
        if not relevant_rings:
            return base
        seen = {_ring_index(r) for r in base}
        return sorted(base + [r for r in relevant_rings if _ring_index(r) not in seen],
                      key=_ring_index)
    relevant = list(relevant_rings or [])[:window]            # model's picks, capped to the budget
    seen = {_ring_index(r) for r in relevant}
    fill = window - len(relevant)
    recent = []
    if fill > 0:
        for r in tc.tail_rings(window + len(relevant)):       # over-read so dedupe still leaves `fill`
            if _ring_index(r) not in seen:
                recent.append(r)
        recent = recent[-fill:]                               # the `fill` most-recent non-duplicates
    return sorted(relevant + recent, key=_ring_index)


def gate_and_seal(tc: Timechain, candidate: str, context: str = "",
                  ring_type: str = "experience", difficulty: int = 0,
                  external_scores=None, files=None, extra_payload=None, gate: PoQGate = None,
                  window: int = POQ_WINDOW, relevant_rings=None, use_index: bool = False):
    """Run the gate; seal only if the verdict is SEAL. Returns (verdict, ring|None).
    `extra_payload` (e.g. self-labels from recall.py) is merged into the sealed payload.
    The gate scores against a BOUNDED relevance window (relevant rings first, then recent),
    not the whole chain — O(window) at any height, and grounding stays honest no matter how
    long the chain has grown. With `use_index`, the Hippocampus surfaces the MOST RELEVANT
    rings to FILL that window — a relevance-driven conscience — instead of the window
    defaulting to the recent tail."""
    gate = gate or PoQGate()
    if use_index and not relevant_rings:
        try:                                           # ground the claim against the most-relevant
            from hippocampus import Hippocampus         # history, not merely the newest rings
            hippo = Hippocampus(tc.root)
            hippo.ensure_current()
            relevant_rings = hippo.candidates(candidate, context, limit=window)
        except Exception:
            relevant_rings = None
    verdict = gate.evaluate(candidate, relevance_window(tc, window, relevant_rings),
                            context, external_scores, span_guard=True)
    if verdict["decision"] == "SEAL":
        payload = {"summary": candidate}
        if context:
            payload["context"] = context
        payload["poq_verdict"] = {"decision": verdict["decision"],
                                  "cited_rings": verdict["cited_rings"]}
        if verdict.get("span_grounding"):
            payload["poq_verdict"]["span_grounding"] = verdict["span_grounding"]
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
    v = PoQGate().evaluate(args.candidate, relevance_window(tc, args.window), args.context or "", ext or None)
    _print_verdict(v)


def cmd_seal(args):
    tc = Timechain(args.root)
    ext = {d: getattr(args, d) for d in POQ_DIMENSIONS if getattr(args, d) is not None}
    v, ring = gate_and_seal(tc, args.candidate, args.context or "",
                            ring_type=args.type, difficulty=args.difficulty,
                            external_scores=ext or None, files=args.file, window=args.window,
                            use_index=args.index)
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
    common.add_argument("--window", type=int, default=POQ_WINDOW,
                        help=f"bounded relevance window: score against the last N rings (default {POQ_WINDOW}; 0 = whole chain)")
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
    ps.add_argument("--index", action="store_true",
                    help="ground the conscience against the most-relevant rings via the Hippocampus index (relevance-driven, not recency-defaulted)")
    ps.set_defaults(func=cmd_seal)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
