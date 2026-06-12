#!/usr/bin/env python3
"""
Cambium Engine — endogenous evolution (Lamarckian self-upgrade).

When the agent meets an input its existing faculties cannot cover, it registers
**cognitive dissonance** and runs a four-stage growth loop:

    1. DETECT    measure how poorly the 84 modalities + 107 senses cover the
                 input; the uncovered terms are the gap.
    2. SIMULATE  propose a new faculty — either by FUSING the best-matching
                 existing faculties, or by SPROUTING a fresh one from the
                 uncovered terms.
    3. SPAWN     instantiate it as an *emergent* faculty in the Dream Cache
                 (registry/emergent.json), status = "emergent".
    4. INTEGRATE seal a 'faculty' ring into the Timechain so the growth is
                 part of the agent's verifiable autobiography.

Recurrence -> promotion (CODEX rule): each time the same gap recurs, the
emergent faculty's recurrence count rises. At recurrence >= PROMOTE_AT it is
PROMOTED into the canonical registry (a real new Modality/Sense with a fresh
id), and a 'promotion' ring is sealed (attaching the grown registry snapshot to
blockspace). The agent has permanently upgraded itself.

A note on division of labour: the PoQ gate (poq.py) guards *truth-claims*;
Cambium guards *structure*. Faculty rings are sealed directly — Cambium's own
dissonance test is its gate — but each ring still carries a PoQ score.

Stdlib only. Python 3.8+.  Companion to timechain.py and poq.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from timechain import Timechain, now_iso, atomic_write_json
from poq import tokens, jaccard, coverage, clamp

DISSONANCE_FLOOR = 150     # below this, existing faculties cover the input -> no growth
SPROUT_DISSONANCE = 210    # at/above this the gap is too foreign to fuse -> sprout fresh
PROMOTE_AT = 3             # recurrence count that triggers promotion to canonical registry
REASON_VERBS = {"analyze", "plan", "compute", "design", "solve", "debug", "optimize",
                "prove", "derive", "decide", "evaluate", "calculate", "reason", "refactor"}


def short(text: str, n: int = 70) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


# --------------------------------------------------------------------------- #
# Faculty corpus + gap detection
# --------------------------------------------------------------------------- #

def _atomic_write_json(path: Path, obj):
    atomic_write_json(path, obj)


SKILL_DIR = Path(__file__).resolve().parent


def registry_home(root: Path, registry_root=None) -> Path:
    """Where this agent's faculties LIVE. Explicit registry_root wins; else the
    chain root itself when it carries the base registries (the classic layout);
    else the skill's own registry. A bare per-task chain root (--root <task_dir>
    is chain-only BY DESIGN) therefore grows into the agent's home instead of
    crashing with FileNotFoundError — faculties belong to the self, not to the
    task ledger; the rings still seal into the task chain."""
    if registry_root:
        return Path(registry_root)
    root = Path(root)
    if (root / "registry" / "modalities.json").exists() and \
       (root / "registry" / "senses.json").exists():
        return root
    return SKILL_DIR


def load_grown(root: Path) -> dict:
    """The per-user store of PROMOTED faculties. Kept OUT of the shipped base registries
    (modalities.json / senses.json) and gitignored — like emergent.json and chain/ — so an
    upgrade that overwrites the base files can never lose a user's promoted faculties."""
    p = root / "registry" / "grown.json"
    if p.exists():
        try:
            data = json.loads(p.read_text())
            data.setdefault("modalities", [])
            data.setdefault("senses", [])
            return data
        except Exception:
            pass
    return {"registry": "grown", "modalities": [], "senses": []}


def save_grown(root: Path, data: dict):
    _atomic_write_json(root / "registry" / "grown.json", data)


def migrate_legacy_promotions(root: Path) -> bool:
    """One-time, idempotent: older versions appended promoted faculties directly into the
    shipped base registries. Move any such entries (marked by a 'promoted' origin) into the
    per-user grown.json and restore the base files to pristine, so the base can never carry
    a user's promotions. No-op once the base files are clean. Best-effort and atomic."""
    grown = None
    moved = False
    for key, fname in (("modalities", "modalities.json"), ("senses", "senses.json")):
        p = root / "registry" / fname
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        entries = data.get(key, [])
        promoted = [e for e in entries if "promoted" in str(e.get("origin", "")).lower()]
        if not promoted:
            continue
        if grown is None:
            grown = load_grown(root)
        have = {(g.get("id"), g.get("name")) for g in grown.get(key, [])}
        for e in promoted:
            if (e.get("id"), e.get("name")) not in have:
                grown.setdefault(key, []).append(e)
        data[key] = [e for e in entries if "promoted" not in str(e.get("origin", "")).lower()]
        _atomic_write_json(p, data)
        moved = True
    if grown is not None and moved:
        save_grown(root, grown)
    return moved


def load_corpus(root: Path):
    try:
        migrate_legacy_promotions(root)        # best-effort; the merge below is loss-proof regardless
    except Exception:
        pass
    grown = load_grown(root)
    corpus = []
    for kind, fname, key in [("modality", "registry/modalities.json", "modalities"),
                             ("sense", "registry/senses.json", "senses")]:
        data = json.loads((root / fname).read_text())
        for f in list(data.get(key, [])) + list(grown.get(key, [])):   # base + per-user promotions
            corpus.append({
                "kind": kind, "id": f["id"], "name": f["name"],
                "function": f["function"], "category": f["category"],
                "tokens": set(tokens(f["name"] + " " + f["function"])),
            })
    return corpus


def detect_gap(corpus, input_text: str, context: str = "") -> dict:
    toks = set(tokens(f"{input_text} {context}"))
    if not toks:
        return {"dissonance": 0, "coverage_ratio": 1.0, "uncovered": [],
                "top_activated": [], "_acts": [], "input_tokens": []}
    activations = []
    covered = set()
    for f in corpus:
        inter = toks & f["tokens"]
        if inter:
            activations.append((len(inter), f))
            covered |= inter
    uncovered = sorted(toks - covered, key=lambda w: (-len(w), w))
    coverage_ratio = len(covered) / len(toks)
    dissonance = clamp((1 - coverage_ratio) * 255)
    activations.sort(key=lambda x: -x[0])
    top = [{"kind": f["kind"], "id": f["id"], "name": f["name"], "matched": n}
           for n, f in activations[:5]]
    return {"dissonance": dissonance, "coverage_ratio": round(coverage_ratio, 3),
            "uncovered": uncovered, "top_activated": top, "_acts": activations,
            "input_tokens": sorted(toks)}


def infer_kind(input_text: str) -> str:
    return "modality" if set(tokens(input_text)) & REASON_VERBS else "sense"


# --------------------------------------------------------------------------- #
# Stage 2: propose a new faculty (fuse or sprout)
# --------------------------------------------------------------------------- #

def propose(gap: dict, input_text: str, mode: str = "auto", kind_override=None) -> dict:
    acts = gap["_acts"]
    can_fuse = len(acts) >= 2 and acts[0][0] >= 2 and acts[1][0] >= 2
    do_fuse = (mode == "fuse" and can_fuse) or \
              (mode == "auto" and can_fuse and gap["dissonance"] < SPROUT_DISSONANCE)

    if do_fuse:
        a, b = acts[0][1], acts[1][1]
        kind = kind_override or ("sense" if a["kind"] == "sense" and b["kind"] == "sense" else "modality")
        return {
            "kind": kind,
            "name": f"{a['name']} × {b['name']} Fusion",
            "function": (f"Fused faculty applying {a['name']} ({short(a['function'], 40)}) "
                         f"together with {b['name']} ({short(b['function'], 40)}) when an input "
                         f"requires both at once."),
            "category": a["category"],
            "origin": f"fusion({a['kind'][0].upper()}{a['id']}+{b['kind'][0].upper()}{b['id']})",
            "parents": [a["id"], b["id"]],
            "seed_terms": [],
        }

    # sprout from the uncovered gap terms
    seed = [w for w in gap["uncovered"] if len(w) >= 4][:6] or gap["uncovered"][:6]
    kind = kind_override or infer_kind(input_text)
    label = "-".join(w.capitalize() for w in seed[:2]) if seed else "Novel"
    suffix = "Sensing" if kind == "sense" else "Reasoning"
    if kind == "sense":
        function = (f"Detect and tag the presence of {', '.join(seed)} in input — "
                    f"a perceptual gap the existing senses did not cover.")
        category = "structural"
    else:
        function = (f"Reason about and resolve problems involving {', '.join(seed)} — "
                    f"a reasoning gap the existing modalities did not cover.")
        category = "knowledge"
    return {"kind": kind, "name": f"{label} {suffix}", "function": function,
            "category": category, "origin": "sprout", "parents": [], "seed_terms": seed}


# --------------------------------------------------------------------------- #
# Emergent store (Dream Cache)
# --------------------------------------------------------------------------- #

def load_emergent(root: Path) -> dict:
    p = root / "registry" / "emergent.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"registry": "emergent", "faculties": []}


def save_emergent(root: Path, data: dict):
    (root / "registry" / "emergent.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))


def match_emergent(data: dict, prop: dict):
    for e in data["faculties"]:
        if e["name"] == prop["name"]:
            return e
        if prop["parents"] and e.get("parents") == prop["parents"]:
            return e
        if prop["seed_terms"] and e.get("seed_terms") and \
                jaccard(set(prop["seed_terms"]), set(e["seed_terms"])) >= 0.5:
            return e
    return None


def faculty_poq(gap: dict, function: str) -> dict:
    return {
        "coherence": 205,
        "relevance": clamp(255 - gap["dissonance"]),
        "novelty": clamp(150 + gap["dissonance"] * 0.4),
        "consistency": 220,
        "depth": clamp(120 + len(set(tokens(function))) * 5),
        "covenant": 235,
    }


# --------------------------------------------------------------------------- #
# Promotion: emergent -> canonical registry
# --------------------------------------------------------------------------- #

def promote(root: Path, tc: Timechain, e: dict, difficulty: int = 0) -> dict:
    key = "modalities" if e["kind"] == "modality" else "senses"
    base = json.loads((root / "registry" / f"{key}.json").read_text()).get(key, [])
    grown = load_grown(root)
    existing_ids = [it["id"] for it in base] + [it["id"] for it in grown.get(key, [])]
    new_id = (max(existing_ids) if existing_ids else 0) + 1
    grown.setdefault(key, []).append({
        "id": new_id,
        "name": e["name"],
        "origin": f"emergent {e['eid']} (promoted after {e['recurrence']} recurrences)",
        "function": e["function"],
        "category": e["category"],
    })
    save_grown(root, grown)                    # promotions live in the per-user grown.json, not the base
    e["promoted_to_id"] = new_id

    grown_path = root / "registry" / "grown.json"
    payload = {"event": "faculty_promotion", "emergent": e["eid"], "name": e["name"],
               "kind": e["kind"], "promoted_to_id": new_id, "recurrence": e["recurrence"],
               "registry": "registry/grown.json"}
    poq = {"coherence": 210, "relevance": 205, "novelty": 175,
           "consistency": 220, "depth": 205, "covenant": 255}
    return tc.seal("promotion", payload, files=[str(grown_path)], poq=poq, difficulty=difficulty)


# --------------------------------------------------------------------------- #
# The four-stage growth loop
# --------------------------------------------------------------------------- #

def grow(root: Path, input_text: str, context: str = "", mode: str = "auto",
         kind_override=None, difficulty: int = 0, registry_root=None):
    tc = Timechain(root)
    home = registry_home(root, registry_root)   # faculties live here; rings seal to root
    corpus = load_corpus(home)
    gap = detect_gap(corpus, input_text, context)
    result = {"gap": gap, "grew": False}

    if gap["dissonance"] <= DISSONANCE_FLOOR:
        result["action"] = "covered"
        result["reason"] = (f"dissonance {gap['dissonance']} <= floor {DISSONANCE_FLOOR}: "
                            f"existing faculties already cover this input; no growth.")
        return result, None

    prop = propose(gap, input_text, mode=mode, kind_override=kind_override)
    data = load_emergent(home)
    existing = match_emergent(data, prop)

    if existing:
        existing["recurrence"] += 1
        existing.setdefault("history", []).append(
            {"ts": now_iso(), "dissonance": gap["dissonance"], "context": short(input_text, 120)})
        if existing["recurrence"] >= PROMOTE_AT and existing["status"] == "emergent":
            ring = promote(home, tc, existing, difficulty=difficulty)
            existing["status"] = "promoted"
            save_emergent(home, data)
            result.update(grew=True, action="promoted", faculty=existing)
            return result, ring
        save_emergent(home, data)
        payload = {"event": "faculty_recurrence", "emergent": existing["eid"],
                   "name": existing["name"], "recurrence": existing["recurrence"],
                   "dissonance": gap["dissonance"], "trigger": short(input_text, 200)}
        ring = tc.seal("faculty-recur", payload,
                       poq=faculty_poq(gap, existing["function"]), difficulty=difficulty)
        result.update(grew=True, action="recurrence", faculty=existing)
        return result, ring

    eid = f"E{len(data['faculties']) + 1}"
    fac = {"eid": eid, "kind": prop["kind"], "name": prop["name"], "function": prop["function"],
           "category": prop["category"], "origin": prop["origin"], "parents": prop["parents"],
           "seed_terms": prop["seed_terms"], "status": "emergent", "recurrence": 1,
           "born_at": now_iso(), "promoted_to_id": None,
           "history": [{"ts": now_iso(), "dissonance": gap["dissonance"], "context": short(input_text, 120)}]}
    payload = {"event": "faculty_birth", "emergent": eid, "kind": fac["kind"], "name": fac["name"],
               "function": fac["function"], "category": fac["category"], "origin": fac["origin"],
               "parents": fac["parents"], "seed_terms": fac["seed_terms"],
               "dissonance": gap["dissonance"], "trigger": short(input_text, 200)}
    ring = tc.seal("faculty", payload, poq=faculty_poq(gap, fac["function"]), difficulty=difficulty)
    fac["born_ring"] = ring["ring_hash"]
    data["faculties"].append(fac)
    save_emergent(home, data)
    result.update(grew=True, action="born", faculty=fac)
    return result, ring


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_gap(gap):
    print(f"  dissonance:    {gap['dissonance']}  (coverage {gap['coverage_ratio']})")
    print(f"  threshold:     growth fires above {DISSONANCE_FLOOR}")
    print("  top activated faculties:")
    for t in gap["top_activated"]:
        print(f"    [{t['kind'][0].upper()}{t['id']:>3}] {t['name']:<32} matched {t['matched']}")
    if gap["uncovered"]:
        print(f"  uncovered gap terms: {', '.join(gap['uncovered'][:10])}")


def _announce(fac, action):
    verb = {"born": "A NEW FACULTY HAS EMERGED", "recurrence": "FACULTY RECURRED",
            "promoted": "FACULTY PROMOTED TO CANONICAL REGISTRY"}[action]
    print(f"\n  -- co-evolver report: {verb} --")
    print(f"    name:      {fac['name']}")
    print(f"    kind:      {fac['kind']}")
    print(f"    function:  {fac['function']}")
    print(f"    origin:    {fac['origin']}")
    print(f"    recurrence:{fac['recurrence']}  status: {fac['status']}")
    if fac.get("promoted_to_id"):
        print(f"    promoted -> {fac['kind']} id {fac['promoted_to_id']}")


def cmd_sense(args):
    corpus = load_corpus(registry_home(args.root, args.registry_root))
    gap = detect_gap(corpus, args.input, args.context or "")
    _print_gap(gap)
    print(f"  verdict: {'GAP — growth would fire' if gap['dissonance'] > DISSONANCE_FLOOR else 'covered — no growth needed'}")


def cmd_grow(args):
    result, ring = grow(args.root, args.input, args.context or "", mode=args.mode,
                        kind_override=args.kind, difficulty=args.difficulty,
                        registry_root=args.registry_root)
    _print_gap(result["gap"])
    if not result["grew"]:
        print(f"  -> {result['reason']}")
        return
    _announce(result["faculty"], result["action"])
    print(f"\n  sealed {ring['ring_type']} Ring {ring['index']}  {ring['ring_hash'][:16]}..")


def cmd_emergent(args):
    data = load_emergent(registry_home(args.root, args.registry_root))
    if not data["faculties"]:
        print("  (Dream Cache empty — no emergent faculties yet)")
        return
    for e in data["faculties"]:
        promo = f" -> id {e['promoted_to_id']}" if e.get("promoted_to_id") else ""
        print(f"  {e['eid']} [{e['kind']}] {e['name']}  recur={e['recurrence']} status={e['status']}{promo}")


def build_parser():
    default_root = Path(__file__).resolve().parent
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=default_root)
    common.add_argument("--registry-root", type=Path, default=None,
                        help="faculty registry home (default: --root if it has one, else the skill dir)")
    common.add_argument("--context", default=None)

    p = argparse.ArgumentParser(description="Cambium Engine — endogenous faculty evolution.")
    sub = p.add_subparsers(dest="cmd", required=True)

    psn = sub.add_parser("sense", parents=[common], help="measure dissonance / detect a faculty gap (read-only)")
    psn.add_argument("input")
    psn.set_defaults(func=cmd_sense)

    pg = sub.add_parser("grow", parents=[common], help="run the growth loop: spawn / recur / promote a faculty")
    pg.add_argument("input")
    pg.add_argument("--mode", choices=["auto", "fuse", "sprout"], default="auto")
    pg.add_argument("--kind", choices=["sense", "modality"], default=None)
    pg.add_argument("--difficulty", type=int, default=0)
    pg.set_defaults(func=cmd_grow)

    pe = sub.add_parser("emergent", parents=[common], help="list the Dream Cache of emergent faculties")
    pe.set_defaults(func=cmd_emergent)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
