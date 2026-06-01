#!/usr/bin/env python3
"""
Embedding backends for semantic recall — pluggable, wired into recall's relevance_fn.

DEFAULT (stdlib, zero-dep): `HashingEmbedder` — hashed bag-of-(word + char n-gram)
vectors with cosine similarity. It represents the WHOLE chunk (not just its top
keywords) and sharpens FUZZY / MORPHOLOGICAL matching that raw token overlap misses:
'validate' ~ 'validation' ~ 'validating', shared identifier subwords, typos.

HONEST CEILING: this is NOT true semantic embedding. It cannot bridge synonymy or
meaning ('back up a claim' will not match 'ungrounded'). For genuine semantic recall,
plug in a real model with the SAME interface via `get_embedder('st'|'openai'|'voyage')`
— those adapters need a library and/or API key (not present here by default).

Interface: every embedder has `.embed(text) -> list[float]` (L2-normalized) and there
is a module-level `cosine(a, b)`. Stdlib only for the default.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import sys

_WORD = re.compile(r"[a-z0-9_]+")


def _features(text, ngrams=(3, 4)):
    text = (text or "").lower()
    feats = []
    for w in _WORD.findall(text):
        feats.append("w:" + w)                       # whole-word feature
        s = "^" + w + "$"
        for k in ngrams:                             # char n-grams -> morphology / subword
            for i in range(len(s) - k + 1):
                feats.append("g:" + s[i:i + k])
    return feats


def _h(feat):
    return int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")


class HashingEmbedder:
    name = "hashing"

    def __init__(self, dim=256):
        self.dim = dim

    def embed(self, text):
        v = [0.0] * self.dim
        for f in _features(text):
            h = _h(f)
            v[h % self.dim] += 1.0 if (h >> 12) & 1 else -1.0   # signed hashing cuts collisions
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [round(x / norm, 5) for x in v]


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    return max(0.0, sum(x * y for x, y in zip(a, b)))   # both L2-normed -> dot == cosine


# --- real-model adapters (same .embed interface); used only if the dep/key is present ---

class _STEmbedder:
    name = "sentence-transformers"

    def __init__(self, model="all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer(model)

    def embed(self, text):
        return [float(x) for x in self.m.encode(text, normalize_embeddings=True)]


class _OpenAIEmbedder:
    name = "openai"

    def __init__(self, model="text-embedding-3-small"):
        import openai
        self.c, self.model = openai.OpenAI(), model

    def embed(self, text):
        v = self.c.embeddings.create(model=self.model, input=text).data[0].embedding
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


class _VoyageEmbedder:
    name = "voyage"

    def __init__(self, model="voyage-3"):
        import voyageai
        self.c, self.model = voyageai.Client(), model

    def embed(self, text):
        v = self.c.embed([text], model=self.model).embeddings[0]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


def get_embedder(name="hashing", **kw):
    if name == "hashing":
        return HashingEmbedder(**kw)
    if name in ("st", "sentence-transformers"):
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            raise RuntimeError("provider 'st' needs: pip install sentence-transformers")
        return _STEmbedder(**kw)
    if name == "openai":
        try:
            import openai  # noqa: F401
        except ImportError:
            raise RuntimeError("provider 'openai' needs: pip install openai  + OPENAI_API_KEY")
        return _OpenAIEmbedder(**kw)
    if name == "voyage":
        try:
            import voyageai  # noqa: F401
        except ImportError:
            raise RuntimeError("provider 'voyage' needs: pip install voyageai  + VOYAGE_API_KEY")
        return _VoyageEmbedder(**kw)
    raise ValueError(f"unknown embedder provider: {name}")


def cmd_sim(args):
    e = get_embedder(args.provider)
    print(f"cosine[{e.name}]({args.a!r}, {args.b!r}) = {cosine(e.embed(args.a), e.embed(args.b)):.4f}")


def cmd_vec(args):
    e = get_embedder(args.provider)
    v = e.embed(args.text)
    print(f"{e.name}: dim={len(v)}  first8={[round(x,3) for x in v[:8]]}")


def build_parser():
    p = argparse.ArgumentParser(description="Embedding backends for semantic recall.")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sim", help="cosine similarity between two strings")
    ps.add_argument("a"); ps.add_argument("b")
    ps.add_argument("--provider", default="hashing")
    ps.set_defaults(func=cmd_sim)
    pv = sub.add_parser("vec", help="embed a string (show dim + head)")
    pv.add_argument("text")
    pv.add_argument("--provider", default="hashing")
    pv.set_defaults(func=cmd_vec)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
