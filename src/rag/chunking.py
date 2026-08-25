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
import warnings

# a chunk shorter than this is a heading, a page number or a stray line rather
# than a clause. used to judge whether a strategy really worked.
MIN_USEFUL_CHARS = 40

# if one piece holds more than this share of the document, the split did not
# really split it.
MAX_SINGLE_SHARE = 0.6

# paragraph packing target. roughly the length of a real clause, and comfortably
# inside the 256-token limit of all-MiniLM-L6-v2.
PARAGRAPH_TARGET_CHARS = 700

# D29/D35: all-MiniLM-L6-v2 stops at 256 word-piece tokens and silently drops
# the rest. The PA lease's longest chunk was 1,839 characters, roughly 400-460
# tokens, and it is clause XXXV, DEFAULT. One of the most consequential clauses
# in the document was embedded from its first half only, with no error.
#
# Splitting on a token budget needs the real tokenizer, which lives with the
# embedding model. chunk_document takes an optional token_counter so production
# measures exactly and the tests stay free of network and model downloads.
MAX_CHUNK_TOKENS = 256

# Fallback when no counter is supplied. Measured on the two sample documents
# with the real tokenizer (evaluation/check_chunk_tokens.py):
#
#   FTC lease, ordinary prose      3.74 chars per token  -> 256 tokens ~ 958 chars
#   PA lease, blank template        1.19 chars per token  -> 256 tokens ~ 305 chars
#
# The PA figure is not legal English being dense. It is runs of underscores in
# a fill-in-the-blank template, which word-piece tokenizers shred into roughly
# one token per character. No single character limit is safe for both shapes:
# 958 truncates the template, 305 would cut ordinary clauses into thirds.
#
# So this constant is a coarse guard for prose, not a substitute for measuring.
# 700 chars is about 200 tokens of ordinary text, leaving margin. Any code path
# that actually embeds MUST pass token_counter; retriever.py and
# eval_retrieval.py both do, and chunk_document warns when it is missing on
# text where the estimate is unreliable.
MAX_CHUNK_CHARS = 700

# D28: titles, preambles and signature blocks become chunks and compete in
# retrieval. The false match that motivated the Reviewer is one of them: the
# FTC preamble matched to "landlord right of entry". A chunking problem was
# being fixed downstream by an LLM judge; filtering it here costs no API calls.
SIGNATURE_MARKERS = (
    "in witness whereof", "signature", "signed:", "date:", "printed name",
    "landlord:", "tenant:", "by:",
)


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


def _leading_ref(chunk):
    """The clause reference a chunk starts with, if any. Used to keep the
    reference on the front of every piece when an oversized clause is split,
    so golden-set matching and the report still line up."""
    m = re.match(r"^((?:[IVXLCDM]+|\d+(?:\.\d+)*)[.)])\s", chunk)
    return m.group(1) if m else None


def _looks_like_signature_block(chunk):
    low = chunk.lower()
    if chunk.count("_") >= 10:
        return True
    hits = sum(m in low for m in SIGNATURE_MARKERS)
    return hits >= 2 and len(chunk) < 600


def _is_non_clause(chunk, index, first_referenced):
    """Preamble, title or signature block rather than a term of the contract.

    Deliberately narrow. Dropping a real clause is far worse than keeping a
    preamble, so this only fires on material that carries no clause reference
    AND sits outside the numbered body of the document.
    """
    if _leading_ref(chunk):
        return False
    if _looks_like_signature_block(chunk):
        return True
    # short, unreferenced, and before the first real clause: a title or preamble
    if first_referenced is not None and index < first_referenced and len(chunk) < 600:
        return True
    return False


def _sentences(text):
    parts = re.split(r"(?<=[.;:])\s+(?=[A-Z(\"'])", text)
    return [p.strip() for p in parts if p.strip()]


def _split_oversized(chunk, too_long):
    """Break a chunk that exceeds the embedding limit on sentence boundaries.

    Every piece keeps the clause reference on the front, so a split clause is
    still findable by reference and still reads correctly in the report.
    """
    if not too_long(chunk):
        return [chunk]
    ref = _leading_ref(chunk)
    prefix = f"{ref} " if ref else ""
    out, buf = [], ""
    for sentence in _sentences(chunk):
        candidate = f"{buf} {sentence}".strip() if buf else sentence
        if buf and too_long(prefix + candidate if out else candidate):
            out.append(buf if not out else prefix + buf)
            buf = sentence
        else:
            buf = candidate
    if buf:
        out.append(buf if not out else prefix + buf)
    # a single sentence longer than the limit cannot be split further on
    # sentence boundaries. fall back to hard slicing rather than returning
    # something that will be silently truncated.
    final = []
    for piece in out:
        if too_long(piece) and len(piece) > MAX_CHUNK_CHARS:
            final.extend(chunk_fixed_size(piece, chunk_size=MAX_CHUNK_CHARS, overlap=40))
        else:
            final.append(piece)
    return final or [chunk]


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


def chunk_document(text, token_counter=None, drop_non_clause=True):
    """Split a document, returning (chunks, strategy_name).

    Walks the strategies in order and returns the first that genuinely splits
    the text. Falls back to fixed-size, which always splits something, so this
    never returns a single chunk for a long document.

    token_counter: optional callable returning the token count of a string.
    Pass the embedding model's tokenizer in production so oversized clauses are
    split against the real 256-token limit rather than a character estimate.
    """
    if not text or not text.strip():
        return [], "empty"

    if token_counter is not None:
        def too_long(s):
            return token_counter(s) > MAX_CHUNK_TOKENS
    else:
        # underscore and dash runs tokenize at roughly one token per character,
        # so the character estimate is badly wrong on fill-in-the-blank
        # templates. Say so rather than truncating quietly, which is the whole
        # failure mode D29 was.
        filler = sum(text.count(c) for c in "_-.")
        if filler / max(1, len(text)) > 0.05:
            warnings.warn(
                "chunk_document called without token_counter on text with heavy "
                "underscore or dash runs; the character estimate under-splits "
                "here and chunks may be silently truncated at embedding time",
                RuntimeWarning, stacklevel=2)

        def too_long(s):
            return len(s) > MAX_CHUNK_CHARS

    chunks, strategy = None, None
    for name, fn in STRATEGIES:
        try:
            candidate = fn(text)
        except re.error:
            continue
        if _worked(candidate, text):
            chunks, strategy = candidate, name
            break
    if chunks is None:
        chunks, strategy = chunk_fixed_size(text), "fixed_size_fallback"

    if drop_non_clause and strategy != "fixed_size_fallback":
        refs = [i for i, c in enumerate(chunks) if _leading_ref(c)]
        first = refs[0] if refs else None
        chunks = [c for i, c in enumerate(chunks)
                  if not _is_non_clause(c, i, first)] or chunks

    out = []
    for c in chunks:
        out.extend(_split_oversized(c, too_long))
    return out, strategy


def chunk_by_clause(text, token_counter=None):
    """Backwards-compatible entry point. Returns chunks only.

    Kept because five call sites expect a list of strings. New code that wants
    to know which strategy fired should call chunk_document.
    """
    return chunk_document(text, token_counter=token_counter)[0]
