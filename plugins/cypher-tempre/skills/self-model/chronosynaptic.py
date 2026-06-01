#!/usr/bin/env python3
"""
Chronosynaptic Tree — single-pass parallel-self MCTS, sealed into the Timechain.

NOT a subagent fan-out. This is one in-process reasoning pass in which the agent
forks many *perspectives of itself* — each a lens drawn from its own faculty
registry (modalities + senses) — and runs a Monte Carlo Tree Search over them:

    SELECT      descend the tree of perspective-paths by UCT.
    EXPAND      adopt an untried perspective -> a new candidate stance.
    SIMULATE    roll out that perspective's FUTURE (greedy continuations) to
                estimate the highest truth reachable from it.
    BACKPROP    flow the value up the path.

Every node is scored by the PoQ gate (poq.py) against UNIFIED data:
    - PAST      : grounding/relevance against the rings already in the Timechain.
    - TRAINING  : the model's own knowledge — the `external_scores` seam; in this
                  deterministic harness it defaults to neutral, in deployment the
                  model fills it within the same pass.
    - FUTURE    : the MCTS rollout values (simulated futures of each fork).

COLLAPSE: after the search, the single highest-truth path is sealed into the
Timechain as one `synthesis` ring; the rejected forks are recorded in its
payload (so the chain witnesses the collapse) but are NOT sealed — they fall
away. This is "collapse the wave function to seal only the highest-truth path."

Why this is a *natural feature of the chain as a self-model*: the forks are the
self refracted through its own organs, the valuation is the self's conscience,
the grounding and the sealing are the self's memory. The whole search happens in
one process — no Agent tool, no spawned subagents.

Stdlib only. Python 3.8+.  Companion to timechain.py, poq.py, cambium.py.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from timechain import Timechain
from poq import PoQGate, tokens, jaccard, ring_text


def short(s: str, n: int = 48) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def load_faculties(root: Path):
    fac = []
    for kind, fname, key in [("modality", "registry/modalities.json", "modalities"),
                             ("sense", "registry/senses.json", "senses")]:
        data = json.loads((root / fname).read_text())
        for f in data[key]:
            fac.append({"kind": kind, "id": f["id"], "name": f["name"],
                        "function": f["function"], "category": f["category"],
                        "tokens": set(tokens(f["name"] + " " + f["function"]))})
    return fac


def frame(perspective: dict, query: str) -> str:
    """The stance contributed by adopting one perspective (a faculty-lens)."""
    foc = ", ".join(sorted(set(tokens(query)) & perspective["tokens"])[:4]) or perspective["category"]
    return f"[{perspective['name']}] {perspective['category']} reading focusing on {foc} via {short(perspective['function'])}"


class Node:
    __slots__ = ("parent", "depth", "perspective", "path", "children", "untried", "N", "W", "poq")

    def __init__(self, parent, depth, perspective, path, untried):
        self.parent = parent
        self.depth = depth
        self.perspective = perspective   # the faculty-lens adopted at this node (None at root)
        self.path = path                 # list of perspectives root..this
        self.children = []
        self.untried = untried           # perspectives not yet expanded here
        self.N = 0
        self.W = 0.0
        self.poq = None                  # immediate PoQ verdict at this node

    def q(self) -> float:
        return self.W / self.N if self.N else 0.0


class ChronosynapticTree:
    def __init__(self, root_path, iterations=16, forks=4, max_depth=2, c=1.2):
        self.root_path = Path(root_path)
        self.tc = Timechain(self.root_path)
        self.chain = self.tc.load()
        self.gate = PoQGate()
        self.faculties = load_faculties(self.root_path)
        self.iterations = iterations
        self.forks = forks
        self.max_depth = max_depth
        self.c = c

    # ---- perspective selection (relevance to the query, exploration via UCT) ----
    def rank(self, query, context, k, exclude_ids=()):
        q = set(tokens(f"{query} {context}"))
        pool = [f for f in self.faculties if (f["kind"], f["id"]) not in exclude_ids]
        pool.sort(key=lambda f: len(q & f["tokens"]) + jaccard(q, f["tokens"]), reverse=True)
        return pool[:k]

    def _used(self, path):
        return {(p["kind"], p["id"]) for p in path}

    # ---- PoQ valuation against unified data (past chain + training seam) ----
    def value(self, path, query, context, external=None):
        text = self.compose(path, query)
        verdict = self.gate.evaluate(text, self.chain, context, external)
        return verdict, text

    def compose(self, path, query):
        return "Synthesis of self-perspectives — " + " ; ".join(frame(p, query) for p in path)

    # ---- MCTS phases ----
    def select(self, root):
        node = root
        while True:
            if node.depth >= self.max_depth:
                return node
            if node.untried:
                return node
            if not node.children:
                return node
            node = max(node.children, key=lambda ch: self._uct(ch))

    def _uct(self, child):
        if child.N == 0:
            return float("inf")
        return child.q() + self.c * math.sqrt(math.log(child.parent.N) / child.N)

    def expand(self, node, query, context):
        p = node.untried.pop(0)
        path = node.path + [p]
        verdict, _ = self.value(path, query, context)
        nxt_depth = node.depth + 1
        untried = self.rank(query, context, self.forks, self._used(path)) if nxt_depth < self.max_depth else []
        child = Node(node, nxt_depth, p, path, untried)
        child.poq = verdict
        node.children.append(child)
        return child

    def simulate(self, node, query, context):
        """Roll out the FUTURE: greedily extend the path to max_depth, choosing the
        continuation perspective that yields the highest PoQ brightness."""
        path = list(node.path)
        depth = node.depth
        while depth < self.max_depth:
            pool = self.rank(query, context, self.forks, self._used(path))
            if not pool:
                break
            best, best_b = None, -1.0
            for f in pool:
                verdict, _ = self.value(path + [f], query, context)
                if verdict["brightness"] > best_b:
                    best_b, best = verdict["brightness"], f
            path.append(best)
            depth += 1
        verdict, _ = self.value(path, query, context)
        return verdict["brightness"] / 255.0

    def backprop(self, node, value):
        while node is not None:
            node.N += 1
            node.W += value
            node = node.parent

    # ---- the single-pass search ----
    def search(self, query, context=""):
        root = Node(None, 0, None, [], self.rank(query, context, self.forks))
        for _ in range(self.iterations):
            node = self.select(root)
            if node.depth < self.max_depth and node.untried:
                node = self.expand(node, query, context)
            value = self.simulate(node, query, context)
            self.backprop(node, value)
        return root

    def best_path(self, root):
        # Robust child = most-visited, tie-broken by higher unified value, so the
        # collapse is principled even when visit counts are close.
        node, chosen = root, []
        while node.children:
            node = max(node.children, key=lambda ch: (ch.N, ch.q()))
            chosen.append(node)
        return chosen

    def collapse_and_seal(self, root, query, context, difficulty=0, do_seal=True):
        chosen = self.best_path(root)
        if not chosen:
            return None, None
        leaf = chosen[-1]
        synthesis = self.compose(leaf.path, query)
        forks_report = sorted(
            [{"perspective": ch.perspective["name"], "kind": ch.perspective["kind"],
              "visits": ch.N, "value": round(ch.q() * 255, 1)} for ch in root.children],
            key=lambda d: d["visits"], reverse=True)
        payload = {
            "event": "chronosynaptic_collapse",
            "query": query,
            "chosen_path": [p["name"] for p in leaf.path],
            "synthesis": synthesis,
            "considered_forks": forks_report,
            "collapsed_from": len(root.children),
            "sealed_one_of": sum(1 for _ in root.children),
        }
        ring = None
        if do_seal:
            ring = self.tc.seal("synthesis", payload,
                                poq=leaf.poq["scores"] if leaf.poq else None,
                                difficulty=difficulty)
        return {"chosen": chosen, "leaf": leaf, "forks": forks_report,
                "synthesis": synthesis}, ring


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_think(args):
    tree = ChronosynapticTree(args.root, iterations=args.iterations,
                              forks=args.forks, max_depth=args.depth)
    if len(tree.chain) == 0:
        print("No chain yet — run 'python3 timechain.py init' first.")
        sys.exit(1)
    root = tree.search(args.query, args.context or "")
    result, ring = tree.collapse_and_seal(root, args.query, args.context or "",
                                          difficulty=args.difficulty, do_seal=args.seal)

    print(f"forked {len(root.children)} parallel self-perspectives over "
          f"{args.iterations} in-process iterations (depth {args.depth}); no subagents.\n")
    print("  PARALLEL FORKS (perspective | visits | unified value 0-255):")
    for f in result["forks"]:
        print(f"    [{f['kind'][0].upper()}] {f['perspective']:<34} N={f['visits']:>3}  v={f['value']}")
    leaf = result["leaf"]
    print(f"\n  COLLAPSE -> highest-truth path ({len(leaf.path)} perspectives):")
    for p in leaf.path:
        print(f"    -> {p['name']}  ({p['category']})")
    if leaf.poq:
        print(f"  winner PoQ brightness: {leaf.poq['brightness']}  decision: {leaf.poq['decision']}")
        print(f"  cited rings: {leaf.poq['cited_rings'] or 'none'}")
    print(f"\n  synthesis: {short(result['synthesis'], 160)}")
    if ring:
        print(f"\n  SEALED synthesis Ring {ring['index']}  {ring['ring_hash'][:16]}..  "
              f"(1 of {len(root.children)} forks kept; the rest collapsed away)")
    else:
        print("\n  (not sealed — pass --seal to commit the collapse to the Timechain)")


def build_parser():
    default_root = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Chronosynaptic Tree — single-pass parallel-self MCTS over the Timechain.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pt = sub.add_parser("think", help="fork self-perspectives, search futures, collapse to the highest-truth path")
    pt.add_argument("query")
    pt.add_argument("--root", type=Path, default=default_root)
    pt.add_argument("--context", default=None)
    pt.add_argument("--iterations", type=int, default=16)
    pt.add_argument("--forks", type=int, default=4)
    pt.add_argument("--depth", type=int, default=2)
    pt.add_argument("--seal", action="store_true", help="seal the collapsed highest-truth path into the chain")
    pt.add_argument("--difficulty", type=int, default=0)
    pt.set_defaults(func=cmd_think)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
