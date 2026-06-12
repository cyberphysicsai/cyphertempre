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
import hashlib
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from timechain import Timechain
from cambium import load_corpus, detect_gap
from poq import tokens, jaccard, clamp, gate_and_seal, POQ_WINDOW
import embed as embmod
import telemetry as telem
import policy as policymod
import learner as learnermod

ENTITY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
PATH_HINT_RE = re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.[A-Za-z0-9]+")

# Identifier for the active decision-weight regime (the hand-tuned v2.1 constants).
# Telemetry stamps it on every offer so trained scorers (Phase B+) can be evaluated
# against — and rolled back to — exactly the regime that produced each event.
SCORER_VERSION = "hand-2.1"

# Cap on NON-CHOSEN candidates logged per offer event: enough hard negatives to
# train on, bounded so a 10k-ring retrieve can't bloat the log.
OFFER_LOG_CAP = 24


def approx_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_value(path: Path, *args):
    try:
        proc = subprocess.run(
            ["git", "-C", str(path)] + list(args),
            check=False, capture_output=True, text=True,
        )
    except Exception:
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def current_git_info(path: Path):
    status = git_value(path, "status", "--porcelain")
    return {
        "git_commit": git_value(path, "rev-parse", "HEAD"),
        "git_branch": git_value(path, "rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
    }


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
    # swamp the signal — that boilerplate must not pollute relevance). For
    # cartographic continuum blocks, source content is the text surface; path and
    # provenance metadata are scored separately by the retrieval cartography.
    payload = ring.get("payload", {})
    data = payload.get("data")
    if isinstance(data, dict) and "content" in data:
        return str(data.get("content") or "")
    payload = {k: v for k, v in payload.items() if k not in ("labels", "state", "poq_verdict")}
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


QUANTITY_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"                  # money: $800, $ 1,200.50
    r"|\d[\d,]*(?:\.\d+)?\s?%"                   # percent: 40%, 12.5 %
    r"|\b\d[\d,]*(?:\.\d+)?[\s-]?[A-Za-z]+\b"  # number+unit: 5 miles, 3-mile, 4 days
)
QUANTITY_SEEKING = {"how", "much", "many", "far", "total", "percent", "percentage",
                    "cost", "spend", "spent", "price", "distance", "amount",
                    "count", "number", "sum", "average"}


def quantities(text, cap=10):
    """Number+unit pairs ('5 mile', '$800', '40%') — the passing-remark facts a
    block's topical keywords never carry. Benchmark-driven (LongMemEval q162):
    aggregate questions die when buried quantities are invisible to labels."""
    out = []
    for m in QUANTITY_RE.finditer(text or ""):
        q = re.sub(r"\s+", " ", m.group(0).lower().replace("-", " ")).strip()
        parts_q = q.split(" ")
        if len(parts_q) == 2 and parts_q[1].endswith("s") and len(parts_q[1]) > 3:
            parts_q[1] = parts_q[1][:-1]              # '5 miles' == '5-mile' == '5 mile'
            q = " ".join(parts_q)
        if q not in out:
            out.append(q)
        if len(out) >= cap:
            break
    return out


def excerpt_text(text, query="", words=60):
    parts = text.split()
    if not parts:
        return ""
    q_terms = sorted({t for t in tokens(query or "") if len(t) > 2}, key=lambda t: (-len(t), t))
    start = 0
    if q_terms:
        for term in q_terms:
            for i, part in enumerate(parts):
                normalized = re.sub(r"[^A-Za-z0-9_]+", "", part).lower()
                if normalized == term or (len(term) >= 8 and term in normalized):
                    start = max(0, i - 8)
                    return " ".join(parts[start:start + words])
    return " ".join(parts[start:start + words])


def normalize_path(value):
    if not value:
        return None
    value = str(value).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.strip("/")


def path_hints(text):
    return [normalize_path(m.group(0)) for m in PATH_HINT_RE.finditer(text or "") if normalize_path(m.group(0))]


def ring_data(ring):
    return ring.get("payload", {}).get("data") or {}


def ring_path(ring):
    data = ring_data(ring)
    return normalize_path(data.get("relative_path") or data.get("item"))


def ring_location(ring):
    data = ring_data(ring)
    return {
        "relative_path": ring_path(ring),
        "file_index": data.get("file_index"),
        "chunk_index": data.get("chunk_index"),
        "chunk_of": data.get("chunk_of"),
        "line_start": data.get("line_start"),
        "line_end": data.get("line_end"),
        "top_dir": data.get("top_dir"),
        "extension": data.get("extension"),
        "language": data.get("language"),
        "path_role": data.get("path_role"),
        "is_test": data.get("is_test"),
        "is_generated": data.get("is_generated"),
        "git_commit": data.get("git_commit"),
        "git_branch": data.get("git_branch"),
        "git_dirty": data.get("git_dirty"),
        "content_hash": data.get("content_hash"),
        "file_content_hash": data.get("file_content_hash"),
        "redacted": data.get("redacted"),
        "redaction_count": data.get("redaction_count", 0),
    }


def neighbor_group_key(ring):
    data = ring_data(ring)
    return (
        ring_path(ring),
        data.get("git_commit"),
        data.get("file_content_hash") or data.get("content_hash"),
    )


def path_matches(ring, path_filter=None, dir_filter=None):
    rel = ring_path(ring)
    if not rel:
        return path_filter is None and dir_filter is None
    if path_filter:
        pf = normalize_path(path_filter)
        if rel != pf and not rel.startswith(pf.rstrip("/") + "/"):
            return False
    if dir_filter:
        df = normalize_path(dir_filter).rstrip("/")
        if rel != df and not rel.startswith(df + "/"):
            return False
    return True


def metadata_matches(ring, language=None, extension=None, role=None, top_dir=None,
                     exclude_path=None, exclude_dir=None, source_only=False):
    data = ring_data(ring)
    rel = ring_path(ring)
    if exclude_path:
        excluded = [normalize_path(x) for x in exclude_path if x]
        if rel and any(rel == x or rel.startswith(x.rstrip("/") + "/") for x in excluded):
            return False
    if exclude_dir:
        excluded_dirs = [normalize_path(x).rstrip("/") for x in exclude_dir if x]
        if rel and any(rel == x or rel.startswith(x + "/") for x in excluded_dirs):
            return False
    if language and (data.get("language") or "").lower() != language.lower():
        return False
    if extension:
        wanted = extension if str(extension).startswith(".") else "." + str(extension)
        if (data.get("extension") or "").lower() != wanted.lower():
            return False
    if top_dir and normalize_path(data.get("top_dir")) != normalize_path(top_dir):
        return False
    wanted_role = "source" if source_only and not role else role
    if wanted_role and (data.get("path_role") or "").lower() != wanted_role.lower():
        return False
    return True


def common_prefix_score(a, b):
    a, b = normalize_path(a), normalize_path(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ap, bp = a.split("/"), b.split("/")
    shared = 0
    for x, y in zip(ap, bp):
        if x != y:
            break
        shared += 1
    if shared == 0:
        return 0.0
    return shared / max(len(ap), len(bp))


def path_proximity(ring, filters, hints):
    rel = ring_path(ring)
    if not rel:
        return 0.0
    candidates = [p for p in (filters or []) if p] + list(hints or [])
    if not candidates:
        return 0.0
    return max(common_prefix_score(rel, p) for p in candidates)


def brief_block(ring, score=None, lab=None, words=60, query=""):
    lab = lab or ring.get("payload", {}).get("labels") or {}
    excerpt = excerpt_text(block_text(ring), query=query, words=words)
    out = {
        "index": ring["index"],
        "type": ring["ring_type"],
        "location": ring_location(ring),
        "labels": {
            "senses": [s["name"] for s in lab.get("senses", [])[:3]],
            "modalities": [m["name"] for m in lab.get("modalities", [])[:3]],
            "keywords": lab.get("keywords", [])[:6],
        },
        "excerpt": excerpt[:260],
    }
    if score is not None:
        out["score"] = round(score, 3)
    return out


class Recall:
    def __init__(self, chain_root, registry_root=None, embedder=None):
        self.tc = Timechain(chain_root)
        self.corpus = load_corpus(registry_root or Path(__file__).resolve().parent)
        self.telemetry = telem.Telemetry(chain_root)
        self.policy = policymod.load_policy(registry_root)
        self.trained_scorer = learnermod.load_scorer(registry_root)
        self.scorer_version = (self.trained_scorer["scorer_version"]
                               if self.trained_scorer else SCORER_VERSION)
        import extractor as extractormod
        self._extractor = extractormod
        self.labeler = extractormod.load_labeler(registry_root)
        self.embedder = embedder
        if isinstance(self.embedder, str):
            self.embedder = embmod.get_embedder(self.embedder)

    def _emit(self, event_type, data):
        """Record a loop side-effect. Best-effort: telemetry must never break
        the cognition it observes."""
        try:
            self.telemetry.emit(
                event_type, data,
                embedder_fingerprint=(embmod.fingerprint_of(self.embedder)
                                      if self.embedder is not None else None),
                scorer_version=self.scorer_version)
        except Exception:
            pass

    def label(self, content, context=""):
        """Self-label content: which senses/modalities fire, plus keywords,
        entities, salience, and dissonance."""
        gap = detect_gap(self.corpus, content, context)
        acts = gap["_acts"]
        senses = [{"id": f["id"], "name": f["name"]} for n, f in acts if f["kind"] == "sense"][:5]
        mods = [{"id": f["id"], "name": f["name"]} for n, f in acts if f["kind"] == "modality"][:5]
        distilled_version = None
        if self.labeler is not None:
            # The distilled labeler fires faculties the lexical matcher cannot
            # see (no shared tokens needed) — model-taught associations augment,
            # never replace, the cheap activations. Stamped for provenance.
            base = embmod.get_embedder("hashing")
            if embmod.compatible(self.labeler.get("base_fingerprint"), base.fingerprint):
                for x in self._extractor.predict_with(self.labeler, base.embed(content)):
                    target = senses if x["kind"] == "sense" else mods
                    if not any(e["id"] == x["id"] for e in target):
                        # model-taught associations outrank weak lexical hits:
                        # lead the list, and the cap trims the lexical tail
                        target.insert(0, {"id": x["id"], "name": x["name"], "distilled": x["p"]})
                        del target[6:]
                distilled_version = self.labeler["labeler_version"]
        ents = entities(content)
        kws = keywords(content)
        salience = clamp(50 + 9 * len(ents) + min(120, 3 * len(set(tokens(content)))))
        lab = {"senses": senses, "modalities": mods, "keywords": kws,
               "entities": ents, "salience": salience, "dissonance": gap["dissonance"]}
        quants = quantities(content)
        if quants:
            lab["quantities"] = quants
        if distilled_version:
            lab["labeler_version"] = distilled_version
        if self.embedder is not None:          # self-embed at ingest -> instant cosine recall later
            lab["embedding"] = self.embedder.embed(content)
            # Stamp the vector space: a sealed vector is only comparable to vectors
            # from the SAME embedder/model/dim/algorithm (see embed.compatible).
            lab["embedding_fingerprint"] = embmod.fingerprint_of(self.embedder)
        return lab

    def block_labels(self, ring):
        return ring.get("payload", {}).get("labels") or self.label(block_text(ring))

    def retrieve(self, query, context="", budget_tokens=1000, max_blocks=8,
                 relevance_fn=None, embed=False, path=None, dir=None, neighbors=1,
                 semantic_weight=0.70, path_weight=0.20, chronological_weight=0.10,
                 language=None, extension=None, role=None, top_dir=None,
                 exclude_path=None, exclude_dir=None, source_only=False,
                 scan_window=None, use_index=False, index_limit=300, scorer="auto",
                 _fanout=None):
        if embed and self.embedder is None:           # default to the stdlib embedder
            self.embedder = embmod.get_embedder("hashing")
        q = self.label(query, context)                # also embeds the query if embedder is set
        # Candidate source: the persistent Hippocampus (sub-linear shortlist) when use_index,
        # a bounded recent tail when scan_window, else the whole chain. The path/metadata
        # filters and scorer below still judge — the index only narrows the field.
        if use_index:
            from hippocampus import Hippocampus
            hippo = Hippocampus(self.tc.root, embedder=self.embedder)
            hippo.ensure_current()
            hippo_vec = q.get("embedding") if embed else None
            hippo_fp = (embmod.fingerprint_of(self.embedder)
                        if (embed and self.embedder is not None) else None)
            if embed and hasattr(self.embedder, "base"):
                # The LSH bank lives in the BASE space (sealed vectors are base);
                # query it there — the lens re-ranks afterwards in its own space.
                hippo_vec = self.embedder.base.embed(query)
                hippo_fp = embmod.fingerprint_of(self.embedder.base)
            rings = hippo.candidates(query, context,
                                     query_embedding=hippo_vec,
                                     limit=index_limit,
                                     query_fingerprint=hippo_fp)
        elif scan_window:
            rings = self.tc.tail_rings(scan_window)
        else:
            rings = self.tc.load()
        qS = {s["id"] for s in q["senses"]}
        qM = {m["id"] for m in q["modalities"]}
        qK, qE = set(q["keywords"]), set(q["entities"])
        qtok = set(tokens(query + " " + context))
        quantity_seeking = bool(QUANTITY_SEEKING & qtok)
        dissonance = q["dissonance"]
        qv = q.get("embedding") if embed else None
        _cos = None
        cur_fp = embmod.fingerprint_of(self.embedder) if self.embedder is not None else None
        if qv is not None:
            _cos = embmod.cosine
        filters = [normalize_path(path), normalize_path(dir)]
        hints = path_hints(query + " " + context)

        raw = []
        for r in rings:
            if r["index"] == 0:                       # skip the genesis/identity block
                continue
            if not path_matches(r, path_filter=path, dir_filter=dir):
                continue
            if not metadata_matches(r, language=language, extension=extension, role=role,
                                    top_dir=top_dir, exclude_path=exclude_path,
                                    exclude_dir=exclude_dir, source_only=source_only):
                continue
            lab = self.block_labels(r)
            # CONTENT signal is the discriminator, in priority order:
            if relevance_fn is not None:              #  (1) explicit model/embedding judge
                content = 9.0 * float(relevance_fn(query, block_text(r), lab))
            elif qv is not None:                      #  (2) EMBEDDING cosine (sealed vector, else on the fly)
                bvec = lab.get("embedding")
                # A sealed vector is only sound in the CURRENT embedder's space;
                # cross-space cosines are garbage. A lens can LIFT sealed BASE
                # vectors into its space (one sparse matvec — no re-embedding);
                # anything else mismatched re-embeds on the fly.
                if bvec is not None and not embmod.compatible(
                        lab.get("embedding_fingerprint"), cur_fp):
                    bvec = (self.embedder.lift(bvec, lab.get("embedding_fingerprint"))
                            if hasattr(self.embedder, "lift") else None)
                if bvec is None:
                    bvec = self.embedder.embed(block_text(r))
                content = 9.0 * _cos(qv, bvec)
            else:                                     #  (3) lexical fallback (literal overlap only)
                bK, bE = set(lab.get("keywords", [])), set(lab.get("entities", []))
                btok = set(tokens(block_text(r)))
                label_tokens = (bK | bE) if r.get("payload", {}).get("labels") else btok
                content = (
                    5.0 * jaccard(qE, bE)
                    + 3.0 * jaccard(qK, bK)
                    + 4.0 * jaccard(qtok, label_tokens)
                    + 3.0 * jaccard(qtok, btok)
                )
            if content <= 0.0:                        # no relatedness -> skip (prevents bloat)
                continue
            bS = {s["id"] for s in lab.get("senses", [])}
            bM = {m["id"] for m in lab.get("modalities", [])}
            faculty = 0.7 * len(qS & bS) + 0.7 * len(qM & bM)   # shared lenses: secondary booster
            semantic = min(1.0, content / 9.0)
            path_score = path_proximity(r, filters, hints)
            role_name = ring_data(r).get("path_role") or ""
            noise_penalty = {
                "source": 0.0,
                "config": 0.01,
                "docs": 0.03,
                "test": 0.035,
                "vendor": 0.06,
                "generated": 0.08,
            }.get(role_name, 0.02)
            raw.append({"ring": r, "lab": lab, "content": content, "semantic": semantic,
                        "path": path_score, "faculty": faculty, "noise_penalty": noise_penalty})

        anchors = sorted(raw, key=lambda x: x["semantic"], reverse=True)[:3]
        anchor_indices = [x["ring"]["index"] for x in anchors]
        # The TRAINED scorer (an adopted operator) replaces the hand blend when
        # active — unless the caller forces `scorer="hand"` or passes explicit
        # weight overrides (a co-evolver override always wins over a learner).
        hand_weights_default = (semantic_weight, path_weight, chronological_weight) == (0.70, 0.20, 0.10)
        use_trained = (scorer == "auto" and self.trained_scorer is not None
                       and hand_weights_default)
        scored = []
        for item in raw:
            r, lab = item["ring"], item["lab"]
            chronological = 0.0
            if anchor_indices:
                chronological = max(max(0.0, 1.0 - abs(r["index"] - idx) / 4.0) for idx in anchor_indices)
            parts = {
                "semantic": round(item["semantic"], 3),
                "path": round(item["path"], 3),
                "chronological": round(chronological, 3),
                "faculty": round(min(1.0, item["faculty"] / 4.0), 3),
                "noise_penalty": round(item["noise_penalty"], 3),
                # quantity-bearing blocks matter to quantity-seeking queries —
                # the buried passing-remark number a topic label never shows
                "quantity": 1.0 if (quantity_seeking and lab.get("quantities")) else 0.0,
            }
            if use_trained:
                score = learnermod.apply_scorer(self.trained_scorer, parts,
                                                lab.get("salience", 0))
            else:
                score = (
                    semantic_weight * item["semantic"]
                    + path_weight * item["path"]
                    + chronological_weight * chronological
                    + 0.05 * parts["faculty"]
                    + 0.06 * parts["quantity"]
                    + 0.03 * (lab.get("salience", 0) / 255)
                    - item["noise_penalty"]   # no recency term: relevance/path/anchors decide
                    #                            selection; time is orientation only (below)
                )
            scored.append((score, r, lab, parts))
        scored.sort(key=lambda x: x[0], reverse=True)

        # appetite: dissonance is the need signal. Low need -> pull little/none.
        # When the learner has CALIBRATED the curve (P(blocks fetched | dissonance)
        # from real fetch behaviour, adopted under policy guards), it replaces the
        # hand formula; otherwise the formula stands.
        appetite_curve = (self.policy.get("appetite") or {}).get("calibrated")
        bucket = None
        if appetite_curve:
            bucket = next((b for b in appetite_curve.get("curve", [])
                           if b["lo"] <= dissonance <= b["hi"]), None)
        if bucket is not None:
            appetite = min(max_blocks, max(0, round(bucket["mean_fetched"])))
        elif dissonance < 50:
            appetite = 0
        else:
            appetite = max(1, round(max_blocks * dissonance / 255))
        has_hard_filter = any([path, dir, language, extension, role, top_dir, source_only,
                               exclude_path, exclude_dir])
        if has_hard_filter and scored:
            appetite = max(1, appetite)
        top = scored[0][0] if scored else 0.0
        if use_trained:
            threshold = 0.5 * top    # trained scores are probability-shaped: the hand
            #                          absolute floor doesn't translate; relative cut only
        else:
            floor = 0.08 if has_hard_filter else 0.18
            threshold = max(floor, 0.5 * top)         # absolute floor + relative: no junk, no bloat

        chosen, used, chosen_indices = [], 0, set()
        rings_by_index = {r["index"]: r for r in rings}
        chunks_by_group = {}
        for r in rings:
            group = neighbor_group_key(r)
            ci = ring_data(r).get("chunk_index")
            if group[0] and ci is not None:
                chunks_by_group.setdefault(group, {})[ci] = r

        for score, r, lab, parts in scored:
            if len(chosen) >= appetite or score < threshold:
                break
            excerpt = excerpt_text(block_text(r), query=query, words=60)
            cost = approx_tokens(excerpt)
            if used + cost > budget_tokens:
                break
            block = brief_block(r, score=score, lab=lab, query=query)
            block["score_parts"] = parts
            block["neighbors"] = []
            chosen.append(block)
            chosen_indices.add(r["index"])
            used += cost
        if neighbors > 0 and chosen:
            for block in chosen:
                r = rings_by_index[block["index"]]
                group = neighbor_group_key(r)
                ci = ring_data(r).get("chunk_index")
                neighbor_rings = []
                if group[0] and ci is not None:
                    for offset in range(-neighbors, neighbors + 1):
                        if offset == 0:
                            continue
                        nr = chunks_by_group.get(group, {}).get(ci + offset)
                        if nr is not None:
                            neighbor_rings.append(nr)
                else:
                    for offset in range(-neighbors, neighbors + 1):
                        if offset == 0:
                            continue
                        nr = rings_by_index.get(r["index"] + offset)
                        if nr is not None and nr["index"] != 0:
                            neighbor_rings.append(nr)
                for nr in sorted(neighbor_rings, key=lambda x: x["index"]):
                    if nr["index"] in chosen_indices:
                        continue
                    excerpt = excerpt_text(block_text(nr), query=query, words=60)
                    cost = approx_tokens(excerpt)
                    if used + cost > budget_tokens:
                        break
                    block["neighbors"].append(brief_block(nr, words=45, query=query))
                    used += cost
        # ε-EXPLORATION (counterfactuals for the learner): with probability ε, ADD one
        # below-top-k candidate to the offered set. Strictly additive — it never displaces
        # a top hit and never exceeds the budget, so retrieval quality cannot degrade.
        # Its inclusion propensity is logged so training importance-weights the update
        # (IPS) instead of mistaking exploration luck for relevance.
        explore_info = {}
        eps = float((self.policy.get("exploration") or {}).get("epsilon", 0.0))
        ewin = int((self.policy.get("exploration") or {}).get("window", 20))
        if eps > 0 and scored and random.random() < eps:
            pool = [(s, r, lab, parts) for (s, r, lab, parts)
                    in scored[len(chosen):len(chosen) + ewin]
                    if r["index"] not in chosen_indices]
            if pool:
                s, r, lab, parts = random.choice(pool)
                excerpt = excerpt_text(block_text(r), query=query, words=60)
                cost = approx_tokens(excerpt)
                if used + cost <= budget_tokens:
                    block = brief_block(r, score=s, lab=lab, query=query)
                    block["score_parts"] = parts
                    block["neighbors"] = []
                    block["explore"] = True
                    propensity = round(eps / len(pool), 6)
                    block["propensity"] = propensity
                    chosen.append(block)
                    chosen_indices.add(r["index"])
                    used += cost
                    explore_info[r["index"]] = propensity

        # ORIENTATION: relevance + path/anchor proximity selected WHICH blocks; present the
        # top-level hits in chain order (the arrow of time) so the model reads them in sequence.
        chosen.sort(key=lambda b: b["index"])

        # TELEMETRY (offer): the choice set this retrieval produced — every chosen
        # candidate plus the top non-chosen ones (the informative near-misses), each
        # with the features the scorer saw. This is the raw material learner three
        # trains on ("was this ring later fetched and used?"); the query itself is
        # never logged, only its hash and redacted label terms.
        cand_log, logged_neg = [], 0
        for rank, (score, r, lab, parts) in enumerate(scored):
            is_chosen = r["index"] in chosen_indices
            if not is_chosen and logged_neg >= OFFER_LOG_CAP:
                continue
            if not is_chosen:
                logged_neg += 1
            entry = {"i": r["index"], "rank": rank, "score": round(score, 4),
                     "parts": parts, "salience": lab.get("salience"),
                     "chosen": is_chosen}
            if r["index"] in explore_info:
                entry["explore"] = True
                entry["propensity"] = explore_info[r["index"]]
            cand_log.append(entry)
        self._emit("offer", {
            "query_hash": telem.query_hash(query, context),
            "query_keywords": telem.redact_terms(q["keywords"][:8]),
            "query_entities": telem.redact_terms(q["entities"][:6]),
            "dissonance": dissonance, "appetite": appetite,
            "threshold": round(threshold, 3), "considered": len(scored),
            "returned": len(chosen), "embed": bool(qv is not None),
            "use_index": bool(use_index), "scan_window": scan_window,
            "scorer": ("trained" if use_trained else "hand"),
            "weights": ({"semantic": semantic_weight, "path": path_weight,
                         "chronological": chronological_weight} if not use_trained
                        else self.trained_scorer["weights"]),
            "policy": ("topk+epsilon" if explore_info else "topk-deterministic"),
            "epsilon": eps,
            "fanout": _fanout,
            "filters_active": has_hard_filter,
            "candidates": cand_log,
        })
        return {"query_labels": q, "dissonance": dissonance, "appetite": appetite,
                "threshold": round(threshold, 2), "considered": len(scored),
                "returned": len(chosen), "budget": budget_tokens, "tokens_used": used,
                "filters": {"path": normalize_path(path), "dir": normalize_path(dir), "hints": hints},
                "metadata_filters": {"language": language, "extension": extension, "role": role,
                                     "top_dir": top_dir, "exclude_path": exclude_path or [],
                                     "exclude_dir": exclude_dir or [],
                                     "source_only": source_only},
                "weights": {"semantic": semantic_weight, "path": path_weight,
                            "chronological": chronological_weight},
                "scorer": ("trained:" + self.scorer_version if use_trained else "hand:" + SCORER_VERSION),
                "explored": bool(explore_info),
                "neighbors": neighbors, "blocks": chosen}

    def retrieve_multi(self, queries, context="", **kw):
        """Fan-out retrieval: one retrieve per decomposed sub-query, results
        unioned with max-score-wins per ring. Decomposition is the MODEL's job —
        aggregate and paraphrase questions are exactly where a single query loses
        to keyword noise (LongMemEval q162: 'total hike distance' lost to Miles
        Davis; 'Red Rock' + '5-mile hike' + 'weekend trail' would not have).
        Each sub-query emits its own offer event stamped with a shared fanout id,
        so per-query credit attribution survives into the learners."""
        queries = [q for q in (queries or []) if q and q.strip()]
        if not queries:
            return {"queries": [], "fanout_id": None, "returned": 0, "blocks": []}
        fanout_id = telem.query_hash(" | ".join(queries), context)[:16]
        merged, reports = {}, []
        for k, sub in enumerate(queries, start=1):
            r = self.retrieve(sub, context,
                              _fanout={"id": fanout_id, "k": k, "of": len(queries)}, **kw)
            reports.append({"query": sub, "returned": r["returned"],
                            "dissonance": r["dissonance"]})
            for b in r["blocks"]:
                cur = merged.get(b["index"])
                if cur is None or (b.get("score") or 0) > (cur.get("score") or 0):
                    b = dict(b)
                    b["matched_query"] = sub
                    merged[b["index"]] = b
        blocks = sorted(merged.values(), key=lambda b: b["index"])   # chain order
        return {"queries": reports, "fanout_id": fanout_id,
                "returned": len(blocks), "blocks": blocks}

    def verify_source(self, repo_path, ring_index):
        rings = {r["index"]: r for r in self.tc.load()}
        ring = rings.get(ring_index)
        if not ring:
            return {"ring_index": ring_index, "verdict": "missing-ring", "ok": False}
        data = ring_data(ring)
        rel = ring_path(ring)
        loc = ring_location(ring)
        if not rel:
            return {"ring_index": ring_index, "verdict": "no-source-path", "ok": False,
                    "location": loc}

        repo = Path(repo_path)
        file_path = repo / rel
        result = {
            "ring_index": ring_index,
            "location": loc,
            "repo_path": str(repo),
            "file_path": str(file_path),
            "path_exists": file_path.exists(),
            "expected": {
                "git_commit": data.get("git_commit"),
                "git_branch": data.get("git_branch"),
                "git_dirty": data.get("git_dirty"),
                "file_content_hash": data.get("file_content_hash"),
                "content_hash": data.get("content_hash"),
            },
            "current": current_git_info(repo),
        }
        if not file_path.exists():
            result.update({"verdict": "missing-source-file", "ok": False})
            self._emit("falsify", {"ring_index": ring_index, "verdict": "missing-source-file"})
            return result

        text = file_path.read_text(errors="replace")
        file_hash = sha256_text(text)
        result["current"]["file_content_hash"] = file_hash
        result["file_hash_match"] = bool(data.get("file_content_hash") and data.get("file_content_hash") == file_hash)

        line_start, line_end = data.get("line_start"), data.get("line_end")
        chunk_hash_match = None
        if line_start is not None and line_end is not None and not data.get("redacted"):
            lines = text.splitlines(keepends=True)
            chunk_text = "".join(lines[max(0, int(line_start) - 1):int(line_end)])
            chunk_hash = sha256_text(chunk_text)
            result["current"]["content_hash"] = chunk_hash
            chunk_hash_match = bool(data.get("content_hash") and data.get("content_hash") == chunk_hash)
        result["chunk_hash_match"] = chunk_hash_match

        expected_commit = data.get("git_commit")
        current_commit = result["current"].get("git_commit")
        revision_match = bool(expected_commit and current_commit and expected_commit == current_commit)
        result["revision_match"] = revision_match if expected_commit and current_commit else None

        source_ok = result["file_hash_match"] and (chunk_hash_match is not False)
        if not source_ok:
            verdict = "source-mismatch"
        elif result["revision_match"] is False:
            verdict = "revision-drift"
        elif result["current"].get("git_dirty"):
            verdict = "dirty-worktree"
        else:
            verdict = "verified"
        result["verdict"] = verdict
        result["ok"] = verdict == "verified"
        if not result["ok"]:
            # TELEMETRY (falsify): a sealed memory failed against live source —
            # negative resonance. Severity is in the verdict: 'source-mismatch'
            # is a hard falsification; drift/dirty are softer staleness signals.
            self._emit("falsify", {"ring_index": ring_index, "verdict": verdict,
                                   "file_hash_match": result.get("file_hash_match"),
                                   "chunk_hash_match": result.get("chunk_hash_match"),
                                   "revision_match": result.get("revision_match")})
        return result

    def seal(self, ring_type, summary, context="", external_scores=None, difficulty=0, files=None,
             window=POQ_WINDOW, relevant_rings=None, use_index=False, used_rings=None):
        """`used_rings` is the model's DECLARED credit assignment: the ring indices
        whose content actually grounded this thought. Declaring them (a) fills the
        PoQ relevance window with exactly that evidence, so the conscience audits
        the claim against what the model says it relied on, and (b) logs the `use`
        telemetry that turns this turn into a training example."""
        labels = self.label(summary, context)
        if used_rings and not relevant_rings:
            by_idx = {r["index"]: r for r in self.tc.load()}
            relevant_rings = [by_idx[i] for i in used_rings if i in by_idx]
        verdict, ring = gate_and_seal(self.tc, summary, context, ring_type=ring_type,
                                      difficulty=difficulty, external_scores=external_scores,
                                      files=files, extra_payload={"labels": labels},
                                      window=window, relevant_rings=relevant_rings, use_index=use_index)
        # TELEMETRY (use): the turn's outcome — every gate decision is a labeled
        # event (a REVISE/FORCE_UNCERTAINTY is signal too, not just a SEAL).
        self._emit("use", {
            "decision": verdict["decision"],
            "sealed_ring": ring["index"] if ring else None,
            "used_rings": list(used_rings or []),
            "cited_rings": [c["index"] for c in verdict.get("cited_rings", [])
                            if isinstance(c, dict)],
            # computed_credit: which rings the TEXT actually leaned on, span by
            # span (the guard's map) — alongside what the model DECLARED it used.
            "computed_credit": (verdict.get("span_grounding") or {}).get("credit"),
            "span_unsupported": (verdict.get("span_grounding") or {}).get("n_unsupported"),
            "grounding": verdict.get("grounding"),
            "assertiveness": verdict.get("assertiveness"),
            "brightness": verdict.get("brightness"),
            "external_scores": bool(external_scores),
        })
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
    if args.queries:
        r = rec.retrieve_multi([args.query] + args.queries, args.context or "",
                               budget_tokens=args.budget, max_blocks=args.max,
                               embed=args.embed, path=args.path, dir=args.dir,
                               neighbors=args.neighbors,
                               language=args.language, extension=args.ext, role=args.role,
                               top_dir=args.top_dir, exclude_path=args.exclude_path,
                               exclude_dir=args.exclude_dir, source_only=args.source_only,
                               scan_window=args.scan_window, use_index=args.index,
                               index_limit=args.index_limit, scorer=args.scorer)
        print(f"[fan-out x{len(r['queries'])}  id {r['fanout_id']}]")
        for qr in r["queries"]:
            print(f"  '{qr['query']}': {qr['returned']} block(s)  (need {qr['dissonance']})")
        print(f"union: {r['returned']} block(s):")
        for b in r["blocks"]:
            print(f"  #{b['index']:>3} [{b['type']}] score {b.get('score')}  via '{b.get('matched_query')}'")
            print(f"        “{b['excerpt'][:150]}…”")
        if not r["blocks"]:
            print("  (nothing above threshold in any sub-query)")
        return
    r = rec.retrieve(args.query, args.context or "", budget_tokens=args.budget,
                     max_blocks=args.max, embed=args.embed, path=args.path, dir=args.dir,
                     neighbors=args.neighbors, semantic_weight=args.semantic_weight,
                     path_weight=args.path_weight, chronological_weight=args.chrono_weight,
                     language=args.language, extension=args.ext, role=args.role,
                     top_dir=args.top_dir, exclude_path=args.exclude_path,
                     exclude_dir=args.exclude_dir, source_only=args.source_only,
                     scan_window=args.scan_window, use_index=args.index, index_limit=args.index_limit,
                     scorer=args.scorer)
    if args.embed:
        print(f"[embedding recall: {rec.embedder.name}]")
    print(f"[scorer: {r['scorer']}{'  +ε-explored' if r['explored'] else ''}]")
    print("query self-labels:")
    _print_labels(r["query_labels"])
    if r["filters"]["path"] or r["filters"]["dir"] or r["filters"]["hints"]:
        print(f"filters: path={r['filters']['path'] or '-'} dir={r['filters']['dir'] or '-'} "
              f"hints={r['filters']['hints'] or '-'}")
    mf = r["metadata_filters"]
    active_meta = {k: v for k, v in mf.items() if v not in (None, False, [], "")}
    if active_meta:
        print(f"metadata filters: {active_meta}")
    print(f"\nneed: dissonance {r['dissonance']} -> appetite {r['appetite']} block(s)   "
          f"(threshold {r['threshold']}; considered {r['considered']})")
    print(f"returned {r['returned']} block(s), ~{r['tokens_used']}/{r['budget']} tokens "
          f"(semantic/path/chronological blend):")
    for b in r["blocks"]:
        loc = b.get("location") or {}
        where = loc.get("relative_path") or "-"
        if loc.get("line_start") is not None:
            where += f":{loc['line_start']}-{loc['line_end']}"
        print(f"  #{b['index']:>3} [{b['type']}] score {b['score']}  "
              f"path={where} parts={b.get('score_parts')} "
              f"senses={b['labels']['senses']} kw={b['labels']['keywords']}")
        print(f"        “{b['excerpt'][:150]}…”")
        for nb in b.get("neighbors", []):
            nloc = nb.get("location") or {}
            nwhere = nloc.get("relative_path") or "-"
            if nloc.get("line_start") is not None:
                nwhere += f":{nloc['line_start']}-{nloc['line_end']}"
            print(f"        neighbor #{nb['index']} {nwhere}: “{nb['excerpt'][:120]}…”")
    if not r["blocks"]:
        print("  (nothing above threshold — the agent does not need past blocks for this)")


def cmd_verify_source(args):
    rec = Recall(args.root, args.registry_root)
    result = rec.verify_source(args.repo, args.index)
    loc = result.get("location") or {}
    where = loc.get("relative_path") or "-"
    if loc.get("line_start") is not None:
        where += f":{loc['line_start']}-{loc['line_end']}"
    print(f"Ring {args.index}: {result['verdict']}  {where}")
    print(f"  file exists       : {result.get('path_exists')}")
    print(f"  file hash match   : {result.get('file_hash_match')}")
    print(f"  chunk hash match  : {result.get('chunk_hash_match')}")
    print(f"  revision match    : {result.get('revision_match')}")
    expected = result.get("expected") or {}
    current = result.get("current") or {}
    print(f"  expected commit   : {expected.get('git_commit') or '-'}")
    print(f"  current commit    : {current.get('git_commit') or '-'}")
    print(f"  current branch    : {current.get('git_branch') or '-'}")
    print(f"  current dirty     : {current.get('git_dirty')}")
    sys.exit(0 if result.get("ok") else 1)


def cmd_seal(args):
    poq = {d: getattr(args, d) for d in ["coherence", "relevance", "novelty", "consistency", "depth", "covenant"]
           if getattr(args, d) is not None}
    verdict, ring, labels = Recall(args.root, args.registry_root).seal(
        args.type, args.summary, context=args.context or "",
        external_scores=poq or None, difficulty=args.difficulty, use_index=args.index,
        used_rings=args.used_rings)
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
        loc = ring_location(r)
        where = loc.get("relative_path") or "-"
        if loc.get("line_start") is not None:
            where += f":{loc['line_start']}-{loc['line_end']}"
        print(f"#{r['index']:>3} [{r['ring_type']}] need~{lab['dissonance']}  {where}  {summary[:150]}")
        print(f"      kw: {', '.join(lab['keywords'][:7]) or '-'}  | entities: {', '.join(lab['entities'][:5]) or '-'}")


def cmd_fetch(args):
    """Pull the full content of the blocks the model judged relevant (budget-bounded)."""
    rec = Recall(args.root, args.registry_root)
    rings = {r["index"]: r for r in rec.tc.load()}
    used, fetched, missing = 0, [], []
    for i in args.ids:
        r = rings.get(i)
        if not r:
            print(f"#{i}: not found"); missing.append(i); continue
        ex = " ".join(block_text(r).split()[: args.words])
        cost = approx_tokens(ex)
        if used + cost > args.budget:
            print(f"(budget {args.budget} tokens reached)"); break
        used += cost
        fetched.append(i)
        loc = ring_location(r)
        where = loc.get("relative_path") or "-"
        if loc.get("line_start") is not None:
            where += f":{loc['line_start']}-{loc['line_end']}"
        print(f"#{i} [{r['ring_type']}] {r['ring_hash'][:12]}.. {where}")
        print(f"  {ex[: args.words * 8]}\n")
    print(f"(fetched ~{used}/{args.budget} tokens)")
    # TELEMETRY (fetch): which blocks the MODEL chose to pull — its relevance
    # judgment over the index, the key annotation retrieval learns from.
    rec._emit("fetch", {"ids": fetched, "missing": missing,
                        "tokens_used": used, "budget": args.budget})


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
    pr.add_argument("--queries", nargs="*", default=[],
                    help="fan-out: extra decomposed sub-queries unioned with the main query "
                         "(aggregate/paraphrase questions; the model decomposes, the union is mechanical)")
    pr.add_argument("--context", default=None)
    pr.add_argument("--budget", type=int, default=1000, help="token budget for retrieved excerpts")
    pr.add_argument("--max", type=int, default=8, help="max blocks (appetite cap)")
    pr.add_argument("--embed", action="store_true", help="rank by embedding cosine, not lexical overlap")
    pr.add_argument("--provider", default="hashing", help="embedding backend: hashing|st|openai|voyage")
    pr.add_argument("--path", default=None, help="only retrieve hits from a relative path or path prefix")
    pr.add_argument("--dir", default=None, help="only retrieve hits under a relative directory")
    pr.add_argument("--language", default=None, help="only retrieve chunks tagged with this language")
    pr.add_argument("--ext", default=None, help="only retrieve chunks with this file extension")
    pr.add_argument("--role", default=None, choices=["source", "test", "docs", "config", "vendor", "generated", "other"],
                    help="only retrieve chunks with this path role")
    pr.add_argument("--source-only", action="store_true", help="shortcut for --role source")
    pr.add_argument("--top-dir", default=None, help="only retrieve chunks under this top-level directory")
    pr.add_argument("--exclude-path", nargs="*", default=[], help="exclude relative paths or path prefixes")
    pr.add_argument("--exclude-dir", nargs="*", default=[], help="exclude relative directories")
    pr.add_argument("--neighbors", type=int, default=1, help="include nearby chunks around each hit")
    pr.add_argument("--semantic-weight", type=float, default=0.70)
    pr.add_argument("--path-weight", type=float, default=0.20)
    pr.add_argument("--chrono-weight", type=float, default=0.10)
    pr.add_argument("--scan-window", type=int, default=None,
                    help="bound the candidate scan to the last N rings (default: scan all)")
    pr.add_argument("--index", action="store_true",
                    help="use the persistent Hippocampus index for a sub-linear candidate shortlist")
    pr.add_argument("--index-limit", type=int, default=300,
                    help="max candidates the index returns before the scorer/model judge (default 300)")
    pr.add_argument("--scorer", choices=["auto", "hand"], default="auto",
                    help="auto = adopted trained operator when one is active; hand = force the hand weights")
    pr.set_defaults(func=cmd_retrieve)

    pv = sub.add_parser("verify-source", parents=[common], help="verify a retrieved source ring against a live repo")
    pv.add_argument("index", type=int, help="ring index to validate")
    pv.add_argument("--repo", type=Path, required=True, help="repo root that relative_path should resolve under")
    pv.set_defaults(func=cmd_verify_source)

    ps = sub.add_parser("seal", parents=[common], help="self-label then PoQ-gate-seal a block")
    ps.add_argument("summary")
    ps.add_argument("--context", default=None)
    ps.add_argument("--type", default="experience")
    ps.add_argument("--difficulty", type=int, default=0)
    for d in ["coherence", "relevance", "novelty", "consistency", "depth", "covenant"]:
        ps.add_argument(f"--{d}", type=int, default=None)
    ps.add_argument("--index", action="store_true",
                    help="ground the conscience against the most-relevant rings via the Hippocampus index")
    ps.add_argument("--used-rings", nargs="*", type=int, default=None,
                    help="declare the ring indices whose content actually grounded this thought "
                         "(fills the PoQ window with that evidence + logs `use` telemetry)")
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
