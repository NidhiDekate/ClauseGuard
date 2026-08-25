# Splitting a document into pieces for retrieval.
#
# Two strategies are compared in evaluation/eval_retrieval.py: fixed size (dumb,
# generic) and clause-boundary aware. E1 measured them, and clause chunking won
# outright: recall@3 100% against 75%.
#
# But clause chunking only worked on documents that number their sections. A
# Terms of Service written with headings, bullets or plain paragraphs matched
# nothing, fell through to a single chunk, and every retrieval query on that
# document returned the same chunk. No error, no warning, a confident report
# built on one piece of text. The README claimed ToS support the whole time.
#
# chunk_by_clause now walks a chain of strategies and uses the first one that
# actually splits the document. chunk_document returns which one fired, so a
# caller can log it and an eval can report it.

import re

# a chunk shorter than this is a heading, a page number or a stray line rather
# than a clause. used to judge whether a strategy really worked.
MIN_USEFUL_CHARS = 40

# if one piece holds more than this share of the document, the split did not
# really split it.
MAX_SINGLE_SHARE = 0.6

# paragraph packing target. roughly the length of a real clause, and comfortably
# inside the 256-token limit of all-MiniLM-L6-v2.
PARAGRAPH_TARGET_CHARS = 700


def chunk_fixed_size(text, chunk_size=500, overlap=50):
    # the generic approach - just cut the text every N characters, with a
    # little overlap so we don't slice a sentence in half at the boundary.
    # doesn't know or care that this is a legal document.
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end].strip())
        start = end - overlap
    return [c for c in chunks if c]  # drop empty ones


def _split_on(pattern, text):
    return [p.strip() for p in re.split(pattern, text) if p.strip()]


def _numbered(text):
    """I. II. III. or 1. 2. 3. at the start of a line. Leases and most
    contracts. This was the only strategy the chunker had."""
    return _split_on(r"\n(?=(?:[IVXLCDM]+\.|[0-9]+\.)\s)", text)


def _decimal_numbered(text):
    """1.1, 2.14.B and friends. Common in commercial leases and policies,
    and NOT matched by the pattern above, which requires the number to be
    followed directly by a dot and a space."""
    return _split_on(r"\n(?=\d+(?:\.\d+)+[.)]?\s)", text)


def _lettered(text):
    """A. B. C. or (a) (b) (c). Terms of Service and statutes."""
    return _split_on(r"\n(?=(?:\([a-zA-Z]\)|[A-Z][.)])\s)", text)


def _headings(text):
    """A line that looks like a title: short, no trailing full stop, either
    ALL CAPS or Title Case, with body text under it. This is the shape most
    Terms of Service actually use."""
    lines = text.split("\n")
    starts = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not (0 < len(s) <= 80) or s.endswith((".", ",", ";", ":")):
            continue
        words = s.split()
        if not (1 <= len(words) <= 10):
            continue
        alpha = [c for c in s if c.isalpha()]
        if not alpha:
            continue
        is_caps = all(c.isupper() for c in alpha)
        is_title = sum(w[:1].isupper() for w in words) >= max(2, len(words) - 1)
        if not (is_caps or is_title):
            continue
        # a heading needs something under it
        if i + 1 < len(lines) and lines[i + 1].strip():
            starts.append(i)
    if len(starts) < 2:
        return []
    out = []
    for a, b in zip(starts, starts[1:] + [len(lines)]):
        piece = "\n".join(lines[a:b]).strip()
        if piece:
            out.append(piece)
    return out


def _paragraphs(text):
    """Blank-line separated paragraphs, packed up to a target length so a
    document of one-sentence paragraphs does not become hundreds of chunks
    that each say almost nothing."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) < 2:
        return []
    # pack toward the target, but never let packing undo the split. a short
    # document whose paragraphs all fit inside one target-sized chunk would
    # otherwise come back as a single chunk, which is the bug this whole
    # chain exists to prevent.
    target = min(PARAGRAPH_TARGET_CHARS, max(1, len(text) // 3))
    out, buf = [], ""
    for p in paras:
        if buf and len(buf) + len(p) + 2 > target:
            out.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        out.append(buf)
    return out if len(out) > 1 else paras


def _worked(chunks, text):
    """Did this strategy actually split the document?

    Two chunks is not enough on its own. A pattern that matches once near the
    top leaves one tiny piece and one piece holding the whole document, which
    is the single-chunk failure wearing a disguise.
    """
    useful = [c for c in chunks if len(c) >= MIN_USEFUL_CHARS]
    if len(useful) < 2:
        return False
    if text and max(len(c) for c in useful) / len(text) > MAX_SINGLE_SHARE:
        return False
    return True


STRATEGIES = [
    ("numbered", _numbered),
    ("decimal_numbered", _decimal_numbered),
    ("lettered", _lettered),
    ("headings", _headings),
    ("paragraphs", _paragraphs),
]


def chunk_document(text):
    """Split a document, returning (chunks, strategy_name).

    Walks the strategies in order and returns the first that genuinely splits
    the text. Falls back to fixed-size, which always splits something, so this
    never returns a single chunk for a long document.
    """
    if not text or not text.strip():
        return [], "empty"
    for name, fn in STRATEGIES:
        try:
            chunks = fn(text)
        except re.error:
            continue
        if _worked(chunks, text):
            return chunks, name
    return chunk_fixed_size(text), "fixed_size_fallback"


def chunk_by_clause(text):
    """Backwards-compatible entry point. Returns chunks only.

    Kept because five call sites expect a list of strings. New code that wants
    to know which strategy fired should call chunk_document.
    """
    return chunk_document(text)[0]
