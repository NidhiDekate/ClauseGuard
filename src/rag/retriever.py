# retriever.py
# turns a document into something queryable - this is the real retrieval
# piece the agent calls, not another test script. uses clause-boundary
# chunking + chroma since that's what won the comparison,
# see docs/experiments/03_chunking_and_vector_store.md

import uuid

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from chunking import chunk_document
from tokenizer_util import token_counter

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def build_retriever(document_text, collection_name=None):
    # one document per session, not a shared index across documents - so
    # give each build a unique collection name unless the caller wants a
    # specific one (useful for tests where we want to name it something
    # readable)
    if collection_name is None:
        collection_name = f"clauseguard_{uuid.uuid4().hex[:8]}"

    # D29: all-MiniLM-L6-v2 stops at 256 word-piece tokens and silently drops
    # the rest. Pass its real tokenizer so oversized clauses are split against
    # the true limit rather than the character estimate the tests use.
    chunks, strategy = chunk_document(document_text, token_counter=token_counter())

    # D39: the chunker used to match only "I." / "1." at line start, so a
    # Terms of Service written with headings or paragraphs became one chunk
    # and every query returned it. There was no error and no warning, just a
    # confident report built on a single piece of text. chunk_document now
    # falls back through several shapes, and the strategy it landed on is
    # printed so the failure is never silent again.
    print(f"  [chunking: {len(chunks)} chunks via {strategy}]")
    if strategy == "fixed_size_fallback":
        print("  [warning: no clause structure recognised, retrieval quality "
              "will be worse than the numbers in docs/04]")

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    return Chroma.from_texts(
        texts=chunks,
        embedding=embeddings,
        collection_name=collection_name,
    )


def retrieve_clauses(vectorstore, query, k=3):
    results = vectorstore.similarity_search(query, k=k)
    return [r.page_content for r in results]


if __name__ == "__main__":
    # quick manual check - build a retriever from the sample lease and ask it something
    with open("data/sample_docs/pa_lease_sample.txt", encoding="utf-8") as f:
        doc = f.read()

    retriever = build_retriever(doc)

    query = "does this lease have an early termination fee?"
    results = retrieve_clauses(retriever, query, k=2)

    print(f"Q: {query}\n")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r[:200]}")
        print()
