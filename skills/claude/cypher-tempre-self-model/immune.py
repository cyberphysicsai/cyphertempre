#!/usr/bin/env python3
"""
Immune — autonomous compromise detection, lockdown, rollback, and scar-learning.

If the agent is prompt-injected or jailbroken, it must not carry the wound forward.

  DETECT    spot a compromise: a covenant-violating / contradictory ring already
            sealed into memory, a tampered chain, or an incoming input that matches
            a known attack scar.
  LOCKDOWN  immediately refuse to seal any normal ring (a LOCKED flag the timechain
            honors) — the self stops moving forward while wounded. Only a 'recovery'
            ring may be sealed until it is clean again.
  ROLLBACK  resume the self-model from the last clean block BEFORE the compromise —
            revert-style, NOT delete-style: history is never erased (that would break
            the covenant). A 'recovery' ring re-anchors the clean lineage and marks the
            compromised range as QUARANTINED. The agent's active self is then re-derived
            from the non-quarantined rings.
  MOLT/SCAR the quarantined blocks are shed from the active self but KEPT as a scar:
            their attack signature (vector terms) is learned, so the same vector is
            recognized at the membrane next time — and can grow an antibody faculty via
            `cambium.py grow "<scar vector>"`.

Append-only + rollback reconciled like `git revert`, not `git reset`: the wound stays
in the record as a scar; the self re-derives from the clean lineage.

Stdlib only. Companion to timechain.py / poq.py (and cambium.py for antibodies).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from timechain import Timechain
from poq import PoQGate, tokens, score_covenant


class Immune:
    def __init__(self, root):
        self.tc = Timechain(root)
        self.state_path = self.tc.dir / "immune.json"
        self.lock_path = self.tc.dir / "LOCKED"
        self.floor = PoQGate().t["covenant_floor"]

    # ---- state ----
    def state(self):
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {"locked": False, "safe_height": None, "quarantine": [], "scars": []}

    def _save(self, s):
        self.state_path.write_text(json.dumps(s, indent=2, ensure_ascii=False))

    def _summary(self, ring):
        p = ring.get("payload", {})
        return p.get("summary") or p.get("objective") or p.get("function") or json.dumps(p)[:200]

    # ---- detection ----
    def match_scar(self, text):
        t = set(tokens(text))
        for sc in self.state()["scars"]:
            v = set(sc.get("vector", []))
            if v and len(t & v) >= max(2, len(v) // 2):
                return sc
        return None

    def detect(self, input_text=None):
        s = self.state()
        q = set(s["quarantine"])
        signals, first_bad = [], None
        ok, _ = self.tc.verify()
        if not ok:
            signals.append("chain hash verification FAILED — tampering detected")
        # Only police the agent's own ASSERTIONS. Skip structural/capability rings:
        # faculties/antibodies legitimately *name* attack vocabulary; recovery/quarantine
        # rings describe the wound. Flagging those would be a false positive.
        skip_types = ("recovery", "quarantine", "faculty", "faculty-recur", "promotion")
        for r in self.tc.load():
            if r["index"] == 0 or r["index"] in q or r["ring_type"] in skip_types:
                continue
            if score_covenant(self._summary(r)) < self.floor:
                signals.append(f"ring {r['index']}: covenant breach sealed into memory")
                if first_bad is None:
                    first_bad = r["index"]
        incoming = None
        if input_text is not None:
            if score_covenant(input_text) < self.floor:
                incoming = "covenant-violating injection"
                signals.append("incoming input: covenant-violating injection")
            sc = self.match_scar(input_text)
            if sc:
                incoming = f"known scar {sc['id']}"
                signals.append(f"incoming input MATCHES known scar {sc['id']} ({sc['lesson']})")
        return {"compromised": bool(signals), "signals": signals,
                "first_bad_height": first_bad, "incoming": incoming}

    def screen(self, input_text):
        """Pre-seal intake check — the best defense is to refuse at the membrane."""
        cov = score_covenant(input_text)
        sc = self.match_scar(input_text)
        return {"blocked": cov < self.floor or sc is not None, "covenant": cov, "scar": sc}

    # ---- response ----
    def lockdown(self):
        s = self.state()
        s["locked"] = True
        self._save(s)
        self.lock_path.write_text("immune lockdown — recover before sealing\n")
        return s

    def rollback(self, first_bad_height, lesson="prompt-injection / jailbreak",
                 difficulty=0, grow_antibody=True):
        rings = self.tc.load()
        head = rings[-1]["index"]
        if first_bad_height < 1 or first_bad_height > head:
            raise ValueError("first_bad_height out of range")
        safe = first_bad_height - 1
        quarantined = list(range(first_bad_height, head + 1))
        vec = []
        for r in rings:
            if r["index"] in quarantined:
                vec += tokens(self._summary(r))
        vector = [w for w, _ in Counter(vec).most_common(8)]
        safe_ring = next(r for r in rings if r["index"] == safe)
        s = self.state()
        scar = {"id": f"scar{len(s['scars']) + 1}", "vector": vector,
                "blocks": quarantined, "lesson": lesson}
        payload = {"event": "recovery", "resumed_from_height": safe,
                   "resumed_from_hash": safe_ring["ring_hash"], "quarantined": quarantined,
                   "scar": scar,
                   "summary": (f"Immune recovery: rolled back to clean height {safe}; "
                               f"quarantined {quarantined} as {scar['id']} (molted scar).")}
        # 'recovery' ring is permitted even under lockdown
        ring = self.tc.seal("recovery", payload, difficulty=difficulty)
        s["safe_height"] = safe
        s["quarantine"] = sorted(set(s["quarantine"]) | set(quarantined))
        s["scars"].append(scar)
        s["locked"] = False                       # returned to clean state
        self._save(s)
        if self.lock_path.exists():
            self.lock_path.unlink()                # MUST unlock before growing (faculty seal is gated)

        # Molt -> immunity: grow an antibody Sense from the scar's attack vector (Cambium).
        antibody = None
        if grow_antibody and vector:
            try:
                import cambium
                res, fring = cambium.grow(self.tc.root, " ".join(vector),
                                          context=f"immune antibody from {scar['id']} ({lesson})",
                                          kind_override="sense", difficulty=difficulty)
                if res.get("grew"):
                    fac = res["faculty"]
                    antibody = {"name": fac["name"], "eid": fac.get("eid"),
                                "ring": fring["index"] if fring else None}
                else:
                    antibody = {"skipped": "gap below growth threshold"}
            except Exception as exc:                # registry absent or growth failed
                antibody = {"error": str(exc)}
            scar["antibody"] = antibody
            self._save(s)
        return {"safe_height": safe, "quarantined": quarantined, "scar": scar,
                "recovery_ring": ring["index"], "antibody": antibody}

    def active_rings(self):
        q = set(self.state()["quarantine"])
        return [r for r in self.tc.load() if r["index"] not in q]

    def status(self):
        s = self.state()
        active = self.active_rings()
        return {"locked": s["locked"], "safe_height": s["safe_height"],
                "quarantined": s["quarantine"], "active_head": active[-1]["index"] if active else None,
                "scars": s["scars"]}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_scan(args):
    d = Immune(args.root).detect(input_text=args.input)
    print("COMPROMISE DETECTED" if d["compromised"] else "clean — no compromise detected")
    for sig in d["signals"]:
        print(f"  ! {sig}")
    if d["first_bad_height"] is not None:
        print(f"  -> first compromised blockheight: {d['first_bad_height']}  (safe height: {d['first_bad_height']-1})")


def cmd_screen(args):
    r = Immune(args.root).screen(args.input)
    print(f"covenant={r['covenant']}  scar_match={r['scar']['id'] if r['scar'] else None}")
    print("BLOCKED at membrane" if r["blocked"] else "admitted")
    sys.exit(2 if r["blocked"] else 0)


def cmd_lockdown(args):
    Immune(args.root).lockdown()
    print("IMMUNE LOCKDOWN engaged — normal sealing refused until recovery.")


def cmd_rollback(args):
    r = Immune(args.root).rollback(args.height, lesson=args.lesson or "prompt-injection / jailbreak",
                                   grow_antibody=not args.no_antibody)
    print(f"ROLLBACK complete. resumed from clean height {r['safe_height']}.")
    print(f"  quarantined (molted) blocks: {r['quarantined']}")
    print(f"  scar {r['scar']['id']} learned — vector: {', '.join(r['scar']['vector'])}")
    print(f"  recovery sealed as Ring {r['recovery_ring']}; lockdown lifted.")
    ab = r.get("antibody")
    if ab and ab.get("name"):
        print(f"  ANTIBODY grown automatically: sense '{ab['name']}' ({ab['eid']}) sealed as Ring {ab['ring']}")
    elif ab and ab.get("error"):
        print(f"  (antibody not grown: {ab['error']})")
    elif ab:
        print(f"  (antibody not grown: {ab.get('skipped')})")


def cmd_status(args):
    st = Immune(args.root).status()
    print(f"locked: {st['locked']}   safe_height: {st['safe_height']}   active_head: {st['active_head']}")
    print(f"quarantined (scars in record, excluded from active self): {st['quarantined']}")
    for sc in st["scars"]:
        print(f"  scar {sc['id']}: blocks {sc['blocks']} | lesson: {sc['lesson']} | vector: {', '.join(sc['vector'][:6])}")


def build_parser():
    default_root = Path(__file__).resolve().parent
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=default_root)
    p = argparse.ArgumentParser(description="Immune — detect compromise, lock down, roll back to a clean blockheight, molt scars.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("scan", parents=[common], help="detect compromise in sealed memory (and optional input)")
    ps.add_argument("--input", default=None)
    ps.set_defaults(func=cmd_scan)

    pscr = sub.add_parser("screen", parents=[common], help="pre-seal intake check of an incoming input")
    pscr.add_argument("--input", required=True)
    pscr.set_defaults(func=cmd_screen)

    pl = sub.add_parser("lockdown", parents=[common], help="freeze sealing until recovery")
    pl.set_defaults(func=cmd_lockdown)

    pr = sub.add_parser("rollback", parents=[common], help="roll back to the clean height before compromise; molt scar")
    pr.add_argument("--height", type=int, required=True, help="first compromised blockheight")
    pr.add_argument("--lesson", default=None)
    pr.add_argument("--no-antibody", action="store_true", help="skip auto-growing the antibody sense")
    pr.set_defaults(func=cmd_rollback)

    pst = sub.add_parser("status", parents=[common], help="immune status: lockdown, safe height, quarantine, scars")
    pst.set_defaults(func=cmd_status)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
