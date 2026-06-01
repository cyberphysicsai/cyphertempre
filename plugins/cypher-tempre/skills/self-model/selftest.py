#!/usr/bin/env python3
"""
Self-test — exercise all nine mechanisms end-to-end on a throwaway chain and assert the
core invariants. Run from the skill directory:  python3 selftest.py
Exit 0 = all green. Stdlib only.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import timechain, poq, cambium, chronosynaptic, continuum, recall, consensus, immune, embed

SKILL = Path(__file__).resolve().parent
_ok = True


def check(name, cond):
    global _ok
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    _ok = _ok and bool(cond)


def main():
    root = Path(tempfile.mkdtemp(prefix="ct_selftest_"))
    shutil.copytree(SKILL / "registry", root / "registry")   # faculties for cambium/chronosynaptic
    try:
        # 1. Timechain — genesis + verify
        tc = timechain.Timechain(root)
        tc.genesis(name="selftest")
        check("timechain: genesis sealed", tc.height() == 1)

        # 2. PoQ — gate + seal a grounded thought
        verdict, ring = poq.gate_and_seal(
            tc, "I verified my selftest chain and this grounded note is consistent with it.",
            context="selftest",
            external_scores={"coherence": 220, "relevance": 225, "novelty": 180,
                             "consistency": 220, "depth": 205, "covenant": 245})
        check("poq: sealed a ring", ring is not None)
        check("timechain: chain verifies", tc.verify()[0])

        # 3. Cambium — dissonance on a foreign input
        corpus = cambium.load_corpus(SKILL)
        gap = cambium.detect_gap(corpus, "quaternion slerp gimbal kinematics actuator torque encoder")
        check("cambium: detects dissonance on foreign input", gap["dissonance"] > 100)

        # 4. Continuum — ingest + task-aware validate
        c = continuum.Continuum(root)
        c.open_task("selftest task", items_total=1)
        sealed, _ = c.ingest("doc", "alpha beta gamma\n" * 80, finding="x")
        check("continuum: ingested data-height blocks", len(sealed) >= 1)
        check("continuum: coherent", c.validate()[0])

        # 5. Recall — self-label + retrieve (lexical and embedding)
        rec = recall.Recall(root, registry_root=SKILL)
        lab = rec.label("proof of work difficulty target")
        check("recall: produces labels", "keywords" in lab and lab["keywords"])
        check("recall: retrieve runs", "blocks" in rec.retrieve("alpha beta", embed=False))
        check("recall: embedding retrieve runs", "blocks" in rec.retrieve("alpha beta", embed=True))

        # 6. Embed — morphology beats unrelated
        e = embed.get_embedder("hashing")
        rel = embed.cosine(e.embed("validate a block"), e.embed("block validation"))
        unrel = embed.cosine(e.embed("validate a block"), e.embed("fee wallet policy"))
        check("embed: morphology > unrelated", rel > unrel)

        # 7. Chronosynaptic — fork + collapse
        tree = chronosynaptic.ChronosynapticTree(root, iterations=6, forks=3, max_depth=2)
        node = tree.search("what should the agent do next", "selftest")
        result, _ = tree.collapse_and_seal(node, "what next", "selftest", do_seal=False)
        check("chronosynaptic: collapses to a path", bool(result and result["chosen"]))

        # 8. Consensus — quorum attest + verify
        qu = consensus.Quorum(root)
        qu.init(n=3, quorum=2)
        qu.attest()
        check("consensus: quorum valid", qu.verify()[0])

        # 9. Immune — scan a clean chain
        d = immune.Immune(root).detect()
        check("immune: scan runs, chain clean", d.get("compromised") is False)

        check("timechain: final verify", tc.verify()[0])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\nSELFTEST:", "PASS ✅" if _ok else "FAIL ❌")
    sys.exit(0 if _ok else 1)


if __name__ == "__main__":
    main()
