# tokenizer_util.py
# One place that knows how to get the embedding model's tokenizer.
#
# It lives here because two call sites need it, retriever.py and
# eval_retrieval.py, and they MUST agree: if the eval chunks differently from
# production, the eval measures a different system.
#
# It loads the tokenizer directly from transformers rather than reaching into
# the langchain wrapper. The wrapper exposed it as `.client` in one version and
# `._client` in the next, and a private attribute on someone else's object is
# not a stable interface to build on.

from functools import lru_cache

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(EMBEDDING_MODEL)


def token_counter():
    """Callable returning the word-piece token count of a string, matching what
    the embedding model will actually see. Pass to chunk_document so oversized
    clauses are split against the real 256-token limit."""
    tok = _tokenizer()
    return lambda s: len(tok.encode(s, add_special_tokens=True))
