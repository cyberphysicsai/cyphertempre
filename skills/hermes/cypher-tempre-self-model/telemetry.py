#!/usr/bin/env python3
"""
Telemetry — the loop's notarized side-effects: the training data the chain was
already generating, finally written down.

Every pass of the per-turn loop makes judgment calls that vanish the moment the
turn ends: which past blocks retrieval OFFERED (and with what feature scores),
which of them the model actually FETCHED, which fetched rings genuinely grounded
the sealed answer (USE), and which remembered claims were later FALSIFIED against
live source. Those outcomes are exactly the supervision the v3 learners need —
positive pairs, mined hard negatives, credit assignment, negative resonance. This
module captures them as a side effect of operating; no annotation step exists,
because the loop itself is the annotator.

DESIGN RULES (mirroring the chain/index division of labor):
  - DERIVED, NOT SEALED PER-EVENT. Events append to `chain/telemetry.jsonl` —
    operational data beside the chain, never inside it. The chain record stays
    lean; `timechain verify` is unaffected by this file's presence or loss.
  - NOTARIZED IN BATCHES. `digest` seals a `telemetry-digest` ring carrying the
    SHA-256 of the log segment plus per-type counts, making the log tamper-evident
    without bloating the chain. Digests may overlap after a lost state file; that
    is harmless — coverage is what matters, not exclusivity.
  - NEVER BREAKS COGNITION. `emit` is best-effort: an unwritable log must not
    fail a retrieve or a seal. Failures return None.
  - PRIVACY FIRST. Raw queries are never logged — only a query hash and redacted
    label keywords/entities (reusing continuum's secret masking when available).
  - RESPECTS DORMANCY. While the self-model is paused (`chain/PAUSED`), the
    machinery is asleep and nothing is recorded.
  - EVERY EVENT IS SPLITTABLE. Each event stamps the chain head (index + hash),
    the embedder fingerprint, and the scorer version at the moment it happened,
    so temporal-split / like-for-like training and evaluation come for free.

Event types (schema 1) — Phase A emits the first four; the rest are reserved for
the replay / dream phases so the schema is stable from day one:
  offer            retrieval offered candidates with feature scores (choice set)
  fetch            the model pulled specific blocks from the index (its judgment)
  use              a seal attempt: decision, declared used rings, grounding
  falsify          a remembered claim failed verify-source (negative resonance)
  replay-accept    confirm-pass certified an antecedent equivalent   [reserved]
  replay-reject    looked similar, was not — a mined hard negative   [reserved]
  missed-positive  consolidation found an antecedent retrieval missed [reserved]
  route            low-confidence input routed to the model labeler  [reserved]

Kill switch: set CT_TELEMETRY=off (or 0/false) to disable all recording.

Stdlib only. Python 3.8+. Companion to timechain.py and recall.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from timechain import Timechain, now_iso

SCHEMA = 1

EVENT_TYPES = (
    "offer", "fetch", "use", "falsify",
    "replay-accept", "replay-reject", "missed-positive", "route",
)


def enabled() -> bool:
    return os.environ.get("CT_TELEMETRY", "").lower() not in ("off", "0", "false")


def query_hash(query: str, context: str = "") -> str:
    """Stable id for a query without persisting its text (privacy)."""
    return hashlib.sha256((query + "\x1f" + (context or "")).encode("utf-8")).hexdigest()


def redact_terms(terms):
    """Mask secret-shaped strings in label terms before they touch the log.
    Reuses continuum's canonical patterns; falls back to identity if absent."""
    try:
        from continuum import redact_secrets
    except Exception:
        return list(terms or [])
    out = []
    for t in terms or []:
        masked, n = redact_secrets(str(t))
        out.append(masked if n else str(t))
    return out


class Telemetry:
    def __init__(self, root):
        self.tc = Timechain(root)
        self.path = self.tc.dir / "telemetry.jsonl"
        self.state_path = self.tc.dir / "telemetry.digest.json"

    # ---- recording ----
    def emit(self, event_type, data, embedder_fingerprint=None, scorer_version=None):
        """Append one event. Best-effort by design: telemetry must NEVER break the
        loop it observes — on any failure it returns None and cognition proceeds."""
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown telemetry event type: {event_type!r}")
        if not enabled():
            return None
        if (self.tc.dir / "PAUSED").exists():       # dormant = the machinery sleeps
            return None
        head = self.tc._tail_ring()
        event = {
            "schema": SCHEMA,
            "event": event_type,
            "ts": now_iso(),
            "head_index": head.get("index") if head else None,
            "head_hash": head.get("ring_hash") if head else None,
            "embedder_fingerprint": embedder_fingerprint,
            "scorer_version": scorer_version,
            "data": data or {},
        }
        try:
            with self.path.open("a") as f:
                f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            return None
        return event

    # ---- reading ----
    def events(self, since_offset=0):
        """Yield (byte_offset, event) from the log; tolerates torn lines (the
        digest hash, not line-perfection, is the integrity story)."""
        if not self.path.exists():
            return
        with self.path.open("rb") as f:
            f.seek(since_offset)
            while True:
                off = f.tell()
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    yield off, json.loads(line)
                except Exception:
                    continue

    def stats(self):
        counts, total, last_ts = {}, 0, None
        for _, e in self.events():
            counts[e.get("event", "?")] = counts.get(e.get("event", "?"), 0) + 1
            total += 1
            last_ts = e.get("ts", last_ts)
        size = self.path.stat().st_size if self.path.exists() else 0
        state = self._state()
        return {"events": total, "by_type": counts, "bytes": size, "last_ts": last_ts,
                "digested_to": state.get("digested_to", 0),
                "undigested_bytes": max(0, size - state.get("digested_to", 0)),
                "last_digest_ring": state.get("ring_index"),
                "path": str(self.path)}

    # ---- notarization ----
    def _state(self):
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except Exception:
                return {}
        return {}

    def digest(self, do_seal=True):
        """Seal a `telemetry-digest` ring over the log segment appended since the
        last digest: segment SHA-256 + per-type counts. The state file is derived;
        if it is ever lost the next digest simply covers from byte 0 again."""
        state = self._state()
        start = state.get("digested_to", 0)
        size = self.path.stat().st_size if self.path.exists() else 0
        if size <= start:
            return {"sealed": False, "reason": "no new telemetry since last digest",
                    "from": start, "to": size}
        with self.path.open("rb") as f:
            f.seek(start)
            segment = f.read(size - start)
        seg_hash = hashlib.sha256(segment).hexdigest()
        counts = {}
        for _, e in self.events(since_offset=start):
            counts[e.get("event", "?")] = counts.get(e.get("event", "?"), 0) + 1
        payload = {
            "summary": (f"Telemetry digest: notarized {sum(counts.values())} loop event(s) "
                        f"[{', '.join(f'{k}:{v}' for k, v in sorted(counts.items()))}] "
                        f"covering log bytes {start}..{size}."),
            "telemetry_digest": {
                "schema": SCHEMA,
                "segment_sha256": seg_hash,
                "from_offset": start,
                "to_offset": size,
                "event_counts": counts,
            },
        }
        result = {"sealed": False, "from": start, "to": size,
                  "segment_sha256": seg_hash, "event_counts": counts}
        if do_seal:
            ring = self.tc.seal("telemetry-digest", payload)
            try:
                self.state_path.write_text(json.dumps(
                    {"digested_to": size, "ring_index": ring["index"],
                     "segment_sha256": seg_hash}))
            except OSError:
                pass                              # state is derived; digests may overlap
            result.update({"sealed": True, "ring_index": ring["index"],
                           "ring_hash": ring["ring_hash"]})
        return result

    def verify_digests(self):
        """Re-hash every digested segment against its sealed claim. Returns
        (ok, report). A mismatch means the log was edited after notarization."""
        report, ok = [], True
        if not self.path.exists():
            return True, ["no telemetry log"]
        raw = self.path.read_bytes()
        for ring in self.tc.load():
            d = ring.get("payload", {}).get("telemetry_digest")
            if not d:
                continue
            seg = raw[d["from_offset"]:d["to_offset"]]
            actual = hashlib.sha256(seg).hexdigest()
            good = actual == d["segment_sha256"]
            ok = ok and good
            report.append(f"ring {ring['index']}: bytes {d['from_offset']}..{d['to_offset']} "
                          f"{'ok' if good else 'MISMATCH — log edited after notarization'}")
        if not report:
            report.append("no digests sealed yet")
        return ok, report


def join_offers(root):
    """The canonical offer-join: walk events once, in order, attributing each
    fetch/use to the most recent offer (mirroring the loop: retrieve -> fetch ->
    seal) and each replay accept/reject to its offer by query hash. Both
    learners (decisions and representation) train from THIS join, so credit
    assignment can never drift apart between them.

    Yields per offer: {seq, query_hash, proxy, dissonance, candidates (raw),
    fetched:set, used:set, replay_pos:set, replay_neg:set}."""
    offers, by_hash = [], {}
    group, group_id = [], None        # consecutive offers sharing a fanout id
    seq = 0
    for _, e in Telemetry(root).events():
        kind, d = e.get("event"), e.get("data", {})
        if kind == "offer":
            seq += 1
            current = {"seq": seq, "query_hash": d.get("query_hash"),
                       "proxy": " ".join((d.get("query_keywords") or [])
                                         + (d.get("query_entities") or [])),
                       "dissonance": d.get("dissonance"),
                       "candidates": d.get("candidates") or [],
                       "fetched": set(), "used": set(),
                       "replay_pos": set(), "replay_neg": set()}
            offers.append(current)
            # Fan-out sub-queries form ONE choice set: a fetch/use that follows
            # the group credits every sub-offer (the union answered, not the
            # last sub-query alone).
            fo = d.get("fanout") or {}
            if fo.get("id") and fo.get("id") == group_id:
                group.append(current)
            else:
                group, group_id = [current], fo.get("id")
            if d.get("query_hash"):
                by_hash[d["query_hash"]] = current
        elif group and kind == "fetch":
            for o in group:
                o["fetched"] |= set(d.get("ids") or [])
        elif group and kind == "use":
            for o in group:
                o["used"] |= set(d.get("used_rings") or [])
        elif kind == "replay-accept":
            o = by_hash.get(d.get("query_hash"))
            if o is not None and d.get("ring_index") is not None:
                o["replay_pos"].add(d["ring_index"])
        elif kind == "replay-reject":
            o = by_hash.get(d.get("query_hash"))
            if o is not None and d.get("ring_index") is not None:
                o["replay_neg"].add(d["ring_index"])
    return offers


def record(root, event_type, data, embedder_fingerprint=None, scorer_version=None):
    """Module-level convenience for callers that don't hold a Telemetry handle."""
    return Telemetry(root).emit(event_type, data,
                                embedder_fingerprint=embedder_fingerprint,
                                scorer_version=scorer_version)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_stats(args):
    st = Telemetry(args.root).stats()
    print(f"events: {st['events']}   bytes: {st['bytes']}   last: {st['last_ts'] or '-'}")
    for k, v in sorted(st["by_type"].items()):
        print(f"  {k:<16} {v}")
    print(f"digested_to: {st['digested_to']}   undigested: {st['undigested_bytes']} bytes   "
          f"last digest ring: {st['last_digest_ring'] if st['last_digest_ring'] is not None else '-'}")
    print(f"log: {st['path']}")


def cmd_tail(args):
    events = list(Telemetry(args.root).events())
    for _, e in events[-args.n:]:
        data = json.dumps(e["data"], ensure_ascii=False)
        print(f"{e['ts']}  {e['event']:<14} head=#{e['head_index']}  "
              f"{data[:140]}{'…' if len(data) > 140 else ''}")
    if not events:
        print("(no telemetry yet)")


def cmd_digest(args):
    r = Telemetry(args.root).digest()
    if r["sealed"]:
        print(f"telemetry-digest sealed: Ring {r['ring_index']}  "
              f"bytes {r['from']}..{r['to']}  sha256 {r['segment_sha256'][:16]}..")
        for k, v in sorted(r["event_counts"].items()):
            print(f"  {k:<16} {v}")
    else:
        print(f"not sealed: {r.get('reason', 'unknown')}")


def cmd_verify(args):
    ok, report = Telemetry(args.root).verify_digests()
    for line in report:
        print(f"  {'ok ' if ok else '!! '} {line}")
    print("TELEMETRY VERIFY:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


def cmd_emit(args):
    e = Telemetry(args.root).emit(args.type, json.loads(args.data or "{}"))
    print(json.dumps(e, ensure_ascii=False) if e else "(not recorded: disabled, dormant, or unwritable)")


def build_parser():
    default_root = Path(__file__).resolve().parent
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=default_root)
    p = argparse.ArgumentParser(description="Telemetry — the loop's notarized side-effects.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("stats", parents=[common], help="event counts, log size, digest coverage")
    ps.set_defaults(func=cmd_stats)
    pt = sub.add_parser("tail", parents=[common], help="show the most recent events")
    pt.add_argument("-n", type=int, default=10)
    pt.set_defaults(func=cmd_tail)
    pd = sub.add_parser("digest", parents=[common], help="seal a telemetry-digest ring over new events")
    pd.set_defaults(func=cmd_digest)
    pv = sub.add_parser("verify", parents=[common], help="re-hash digested segments against their sealed claims")
    pv.set_defaults(func=cmd_verify)
    pe = sub.add_parser("emit", parents=[common], help="manually record an event (mainly for tests)")
    pe.add_argument("type", choices=EVENT_TYPES)
    pe.add_argument("--data", default="{}", help="JSON object for the event data")
    pe.set_defaults(func=cmd_emit)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
