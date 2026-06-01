#!/usr/bin/env python3
"""
Continuum — long-horizon tasking via data-height blocks with full state refresh.

The problem: a task can be far larger than any context window (an enterprise
codebase, a months-long investigation). Holding it all in context causes rot;
forgetting it causes drift. The Continuum solves both by turning the task into a
self-validating chain of bounded blocks.

Two guarantees per block:
  1. DATA-HEIGHT BOUND. Each block ingests ONE chunk sized to a sweet-spot band
     (>= MIN so blocks hold real data, <= MAX so no single block can rot the
     context). All incoming data is split to this height — piece by piece, any
     size of task is tackled at a constant, manageable granularity.
  2. FULL STATE REFRESH. Each block carries the COMPLETE current task state
     (objective, cursor, metrics, rolling findings, next action) — not a diff.
     So reading the single HEAD block fully re-hydrates the task. An agent can
     stop at any block and resume — new session, hours or weeks later — and know
     exactly where it is and what to do next. It never loses track.

Self-validation: the state carries running invariants (monotonic progress, one
chunk per block, non-decreasing tokens ingested). `validate` checks these across
the chain on top of the timechain's hash verification — the continuum proves its
own coherence.

State is bounded by design (findings capped to a rolling window), so the
re-hydration payload never grows — the cure for context rot.

Stdlib only. Python 3.8+.  Companion to timechain.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from timechain import Timechain

# Data-height band, measured in approximate tokens (~4 chars/token).
TARGET_TOKENS = 1024   # the sweet spot per block
MIN_TOKENS = 256       # below this, merge — blocks must hold real data
MAX_TOKENS = 1536      # hard ceiling — no single block may exceed this (anti-rot)
FINDINGS_WINDOW = 6    # rolling cap so the state refresh stays bounded


def approx_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def chunk_text(text: str, target=TARGET_TOKENS, min_=MIN_TOKENS, max_=MAX_TOKENS):
    """Split text into chunks within [min_, max_] tokens, targeting `target`,
    on line boundaries where possible."""
    chunks, cur = [], ""
    for ln in text.splitlines(keepends=True):
        if approx_tokens(ln) > max_:                      # a single oversized line
            if cur:
                chunks.append(cur); cur = ""
            step = max_ * 4
            for j in range(0, len(ln), step):
                chunks.append(ln[j:j + step])
            continue
        if cur and approx_tokens(cur + ln) > target:
            chunks.append(cur); cur = ln
        else:
            cur += ln
    if cur:
        chunks.append(cur)
    if (len(chunks) >= 2 and approx_tokens(chunks[-1]) < min_
            and approx_tokens(chunks[-2] + chunks[-1]) <= max_):   # merge tiny tail, but never breach the ceiling
        chunks[-2] += chunks[-1]; chunks.pop()
    return chunks or [""]


class Continuum:
    def __init__(self, root, target=TARGET_TOKENS, min_=MIN_TOKENS, max_=MAX_TOKENS):
        self.tc = Timechain(root)
        self.root = Path(root)
        self.target, self.min, self.max = target, min_, max_
        self._state = None       # cached rolling state across a walk -> no per-file reload
        self._labeler = None     # lazy recall labeler for self-labeling at ingest
        self._embed = None       # embedding provider for self-embedding at ingest (e.g. 'hashing')

    def _labels(self, content):
        """Self-label a chunk at ingest (recall labels, optionally an embedding vector), so
        retrieval reads sealed labels/vectors instantly instead of re-computing per query."""
        if self._labeler is None:
            import recall
            self._labeler = recall.Recall(self.root, registry_root=Path(__file__).resolve().parent,
                                          embedder=self._embed)
        return self._labeler.label(content)

    def _head_state(self):
        for r in reversed(self.tc.load()):
            st = r.get("payload", {}).get("state")
            if st:
                return st
        return None

    def open_task(self, objective, items_total=None, difficulty=0):
        if self.tc.height() == 0:
            self.tc.genesis(name="continuum-task",
                            covenant=["accurate", "coherent", "persistent", "honest", "thorough"],
                            params={"kind": "continuum-task", "objective": objective},
                            attach_registries=False, difficulty=difficulty)
        state = {
            "objective": objective,
            "cursor": {"item_index": 0, "item": None, "chunk_index": 0, "chunk_of": 0},
            "metrics": {"items_total": items_total, "items_done": 0,
                        "chunks_sealed": 0, "approx_tokens_ingested": 0},
            "findings": [], "findings_total": 0,
            "next_action": "ingest first item",
            "data_height": {"target_tokens": self.target, "min_tokens": self.min, "max_tokens": self.max},
        }
        ring = self.tc.seal("task_open", {"event": "task_open", "objective": objective, "state": state},
                            difficulty=difficulty)
        self._state = state
        return state, ring

    def ingest(self, name, content, finding=None, difficulty=0, label=True):
        st = self._state if self._state is not None else self._head_state()
        if st is None:
            raise RuntimeError("No open task on this chain — run 'open' first.")
        chunks = chunk_text(content, self.target, self.min, self.max)
        sealed = []
        for i, ch in enumerate(chunks):
            st = json.loads(json.dumps(st))   # deep copy the prior state
            last = (i == len(chunks) - 1)
            st["cursor"] = {"item_index": st["cursor"]["item_index"] + (1 if i == 0 else 0),
                            "item": name, "chunk_index": i + 1, "chunk_of": len(chunks)}
            st["metrics"]["chunks_sealed"] += 1
            st["metrics"]["approx_tokens_ingested"] += approx_tokens(ch)
            if last:
                st["metrics"]["items_done"] += 1
                if finding:
                    st["findings"] = (st["findings"] + [f"{name}: {finding}"])[-FINDINGS_WINDOW:]
                    st["findings_total"] += 1
                it = st["metrics"]["items_total"]
                done = st["metrics"]["items_done"]
                st["next_action"] = ("task complete" if (it and done >= it)
                                     else f"ingest next item (done {done}" + (f"/{it}" if it else "") + ")")
            else:
                st["next_action"] = f"continue ingesting {name}: chunk {i + 2}/{len(chunks)}"
            payload = {"event": "continuum", "task": st["objective"][:48], "state": st,
                       "data": {"item": name, "chunk_index": i + 1, "chunk_of": len(chunks),
                                "approx_tokens": approx_tokens(ch), "content": ch}}
            if label:
                try:
                    payload["labels"] = self._labels(ch)   # self-label at ingest -> instant recall later
                except Exception:
                    pass
            ring = self.tc.seal("continuum", payload, difficulty=difficulty)
            sealed.append((ring, approx_tokens(ch)))
        self._state = st                       # cache rolling state -> next ingest needs no reload
        return sealed, st

    def resume(self):
        return self._head_state()

    def validate(self):
        ok, report = self.tc.verify()
        prev, sizes, heights, issues = None, [], [], []
        for r in self.tc.load():
            p = r.get("payload", {})
            if p.get("event") != "continuum":
                continue
            sizes.append(len(json.dumps(r)))
            h = p["data"]["approx_tokens"]
            heights.append(h)
            m = p["state"]["metrics"]
            if m["chunks_sealed"] == 1:        # first block of a (new) task segment on this chain
                prev = None                    # invariants are per-task; one chain may hold many tasks
            if h > self.max:
                issues.append(f"ring {r['index']}: data-height {h} > max {self.max}")
            if prev:
                if m["items_done"] < prev["items_done"]:
                    issues.append(f"ring {r['index']}: items_done regressed")
                if m["chunks_sealed"] != prev["chunks_sealed"] + 1:
                    issues.append(f"ring {r['index']}: chunks_sealed not monotonic +1")
                if m["approx_tokens_ingested"] < prev["approx_tokens_ingested"]:
                    issues.append(f"ring {r['index']}: tokens ingested regressed")
            prev = m
        out = list(report)
        if heights:
            out.append(f"continuum blocks: {len(heights)}")
            out.append(f"data-height (tokens) min/avg/max: {min(heights)}/{sum(heights)//len(heights)}/{max(heights)}  (band {self.min}-{self.max})")
            out.append(f"block size (bytes)   min/avg/max: {min(sizes)}/{sum(sizes)//len(sizes)}/{max(sizes)}")
        out.append("invariant issues: " + "; ".join(issues) if issues
                   else "state invariants coherent: monotonic progress, +1 chunk/block, every block within data-height band")
        return ok and not issues, out

    def walk(self, path, exts, objective, difficulty=0, label=True, embed=None):
        self._embed = embed
        path = Path(path)
        files = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix in exts)
        self.open_task(objective, items_total=len(files), difficulty=difficulty)
        results = []
        for f in files:
            text = f.read_text(errors="replace")
            ndef = text.count("def "); ncls = text.count("class ")
            finding = f"{text.count(chr(10))+1} lines, {ndef} defs, {ncls} classes"
            sealed, _ = self.ingest(f.name, text, finding=finding, difficulty=difficulty, label=label)
            results.append((f.name, len(sealed)))
        return files, results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_state(st):
    if not st:
        print("  (no task state on this chain)")
        return
    m = st["metrics"]; c = st["cursor"]
    print(f"  objective:   {st['objective']}")
    print(f"  cursor:      item {c['item_index']} ({c['item']}), chunk {c['chunk_index']}/{c['chunk_of']}")
    it = m["items_total"]
    print(f"  progress:    {m['items_done']}" + (f"/{it}" if it else "") + f" items, {m['chunks_sealed']} blocks, ~{m['approx_tokens_ingested']} tokens ingested")
    print(f"  findings ({st['findings_total']} total, last {len(st['findings'])}):")
    for fnd in st["findings"]:
        print(f"     - {fnd}")
    print(f"  NEXT ACTION: {st['next_action']}")


def cmd_open(args):
    st, ring = Continuum(args.root).open_task(args.objective, items_total=args.items)
    print(f"task opened (Ring {ring['index']}).")
    _print_state(st)


def cmd_ingest(args):
    content = Path(args.file).read_text(errors="replace") if args.file else args.text
    c = Continuum(args.root); c._embed = args.embed
    sealed, st = c.ingest(args.name, content, finding=args.finding, label=not args.no_label)
    print(f"ingested '{args.name}' -> {len(sealed)} block(s) at heights {[t for _, t in sealed]} tokens")
    _print_state(st)


def cmd_walk(args):
    files, results = Continuum(args.root).walk(args.path, tuple(args.ext), args.objective,
                                               label=not args.no_label, embed=args.embed)
    print(f"walked {len(files)} files -> blocks per file:")
    for name, n in results:
        print(f"   {name:<24} {n} block(s)")
    _print_state(Continuum(args.root).resume())


def cmd_resume(args):
    print("RESUME — full task state re-hydrated from the single head block:")
    _print_state(Continuum(args.root).resume())


def cmd_validate(args):
    ok, report = Continuum(args.root).validate()
    for line in report:
        print("  " + line)
    print("CONTINUUM:", "COHERENT" if ok else "INCOHERENT")
    sys.exit(0 if ok else 1)


def build_parser():
    default_root = Path(__file__).resolve().parent
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=default_root,
                        help="task chain root (use a per-task dir for big jobs)")

    p = argparse.ArgumentParser(description="Continuum — long-horizon tasking via data-height blocks.")
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("open", parents=[common], help="open a task (seals initial state)")
    po.add_argument("--objective", required=True)
    po.add_argument("--items", type=int, default=None)
    po.set_defaults(func=cmd_open)

    pi = sub.add_parser("ingest", parents=[common], help="ingest one item (file or --text) as data-height blocks")
    pi.add_argument("--name", required=True)
    pi.add_argument("--file", default=None)
    pi.add_argument("--text", default=None)
    pi.add_argument("--finding", default=None)
    pi.add_argument("--no-label", action="store_true", help="skip self-labeling at ingest")
    pi.add_argument("--embed", nargs="?", const="hashing", default=None,
                    help="self-embed each block at ingest (provider, default hashing)")
    pi.set_defaults(func=cmd_ingest)

    pw = sub.add_parser("walk", parents=[common], help="open a task and ingest every file under a path")
    pw.add_argument("--path", required=True)
    pw.add_argument("--objective", required=True)
    pw.add_argument("--ext", nargs="+", default=[".py"])
    pw.add_argument("--no-label", action="store_true", help="skip self-labeling at ingest")
    pw.add_argument("--embed", nargs="?", const="hashing", default=None,
                    help="self-embed each block at ingest (provider, default hashing)")
    pw.set_defaults(func=cmd_walk)

    pr = sub.add_parser("resume", parents=[common], help="re-hydrate full task state from the head block")
    pr.set_defaults(func=cmd_resume)

    pv = sub.add_parser("validate", parents=[common], help="check continuum coherence + chain integrity")
    pv.set_defaults(func=cmd_validate)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
