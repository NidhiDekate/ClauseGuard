# Regression tests for the chunking fallback chain.
#
# D39: chunk_by_clause matched only "I." / "1." at line start, so any document
# written with headings, bullets or plain paragraphs fell through to a single
# chunk. Silent. Every retrieval query then returned the same chunk.
#
# These run without network or API keys. Run: python -m pytest tests/test_chunking.py

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "rag"))

from chunking import chunk_document, chunk_by_clause  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "sample_docs"

DECIMAL = """COMMERCIAL LEASE

1.1 Definitions. In this lease the following words have the meanings given.
The Premises means the whole of the property described in Schedule 1.

1.2 Term. The term begins on the commencement date and continues for the
period stated in Schedule 2 unless ended earlier under clause 9.

2.1 Rent. The tenant shall pay the rent stated in Schedule 3 by equal monthly
instalments in advance on the first day of each month without deduction.

2.14 Interest on late payment. If any sum is unpaid for more than 14 days the
tenant shall pay interest at 4% above base rate from the due date.
"""

LETTERED = """TERMS OF SERVICE

(a) Acceptance. By creating an account you agree to these terms and to any
policies we publish from time to time on the service.

(b) Your content. You keep ownership of what you post. You grant us a
worldwide, royalty-free licence to host, reproduce and distribute it.

(c) Termination. We may suspend or terminate your account at any time, with
or without notice, for conduct we believe violates these terms.

(d) Limitation of liability. Our total liability to you is limited to the
amount you paid us in the twelve months before the claim arose.
"""

HEADINGS = """Terms of Use

Your Account
You are responsible for keeping your password secure. You must notify us
immediately of any unauthorised use of your account.

Content You Provide
You retain all rights in the content you submit. By submitting content you
grant us a licence to use it in connection with operating the service.

Fees and Billing
Subscriptions renew automatically. You authorise us to charge your payment
method on each renewal date until you cancel.

Governing Law
These terms are governed by the laws of the State of California without
regard to its conflict of law provisions.
"""

PARAGRAPHS = """This agreement is entered into between the company and the customer on the
date of first use of the service.

The customer agrees to pay all fees when due. Fees are non-refundable except
where required by law. The company may change its fees on thirty days notice.

The company provides the service as is and makes no warranty of any kind,
express or implied, including any warranty of fitness for a particular
purpose.

Either party may end this agreement on thirty days written notice to the
other. On termination the customer remains liable for fees already incurred.
"""

UNSTRUCTURED = ("The parties agree as follows and the customer accepts all charges however "
                "arising and whenever incurred without limitation or set off. ") * 40


def test_roman_numbered_lease_still_uses_numbered():
    text = (SAMPLES / "pa_lease_sample.txt").read_text(encoding="utf-8")
    chunks, strategy = chunk_document(text)
    assert strategy == "numbered"
    assert len(chunks) > 20


def test_arabic_numbered_lease_still_uses_numbered():
    text = (SAMPLES / "ftc_lease_sample.txt").read_text(encoding="utf-8")
    chunks, strategy = chunk_document(text)
    assert strategy == "numbered"
    assert len(chunks) > 10


def test_decimal_numbering_is_not_one_chunk():
    chunks, strategy = chunk_document(DECIMAL)
    assert strategy == "decimal_numbered"
    # 4 clauses plus the title line, which arrives as its own preamble chunk.
    # Preamble filtering is D28 and deliberately not handled here.
    assert len(chunks) >= 4
    assert sum(c.startswith(("1.1", "1.2", "2.1", "2.14")) for c in chunks) == 4


def test_lettered_terms_of_service():
    chunks, strategy = chunk_document(LETTERED)
    assert strategy == "lettered"
    assert len(chunks) >= 4


def test_headed_terms_of_service():
    chunks, strategy = chunk_document(HEADINGS)
    assert strategy == "headings"
    assert len(chunks) >= 4
    assert any("Fees and Billing" in c for c in chunks)


def test_plain_paragraphs():
    chunks, strategy = chunk_document(PARAGRAPHS)
    assert strategy in ("paragraphs", "headings")
    assert len(chunks) >= 2


def test_unstructured_text_never_returns_one_chunk():
    chunks, strategy = chunk_document(UNSTRUCTURED)
    assert strategy == "fixed_size_fallback"
    assert len(chunks) > 1


def test_no_document_shape_yields_a_single_chunk():
    """The D39 regression itself, stated as one assertion over every shape."""
    for name, text in [("decimal", DECIMAL), ("lettered", LETTERED),
                       ("headings", HEADINGS), ("paragraphs", PARAGRAPHS),
                       ("unstructured", UNSTRUCTURED)]:
        chunks = chunk_by_clause(text)
        assert len(chunks) > 1, f"{name} collapsed to {len(chunks)} chunk(s)"


def test_empty_document():
    assert chunk_document("") == ([], "empty")
    assert chunk_document("   \n  ") == ([], "empty")


# --- D28: non-clause material --------------------------------------------

def test_title_and_preamble_are_dropped():
    text = (SAMPLES / "ftc_lease_sample.txt").read_text(encoding="utf-8")
    kept, _ = chunk_document(text)
    dropped, _ = chunk_document(text, drop_non_clause=False)
    assert len(kept) < len(dropped) or all(not c.startswith("SAMPLE RENTAL") for c in kept)
    # the specific chunk that caused the Reviewer false match
    assert not any(c.startswith("SAMPLE RENTAL AGREEMENT") for c in kept)


def test_a_clause_is_never_dropped():
    """Dropping a real clause is far worse than keeping a preamble, so the
    filter must never touch anything carrying a clause reference."""
    for name in ("pa_lease_sample.txt", "ftc_lease_sample.txt"):
        text = (SAMPLES / name).read_text(encoding="utf-8")
        kept, _ = chunk_document(text)
        refs = {c.split(".")[0] for c in kept if c[:1].isalnum()}
        assert len(refs) > 5, name


def test_signature_block_detected():
    from chunking import _looks_like_signature_block
    assert _looks_like_signature_block(
        "IN WITNESS WHEREOF the parties have executed this lease.\n"
        "Signature: ____________________  Date: ______________")
    assert not _looks_like_signature_block(
        "The Landlord shall provide heat and hot water at all times.")


# --- D29 / D35: oversized chunks -----------------------------------------

def test_no_chunk_exceeds_the_embedding_limit():
    from chunking import MAX_CHUNK_CHARS
    for name in ("pa_lease_sample.txt", "ftc_lease_sample.txt"):
        text = (SAMPLES / name).read_text(encoding="utf-8")
        chunks, _ = chunk_document(text)
        oversize = [c for c in chunks if len(c) > MAX_CHUNK_CHARS]
        assert not oversize, f"{name}: {len(oversize)} chunk(s) over the limit"


def test_split_pieces_keep_the_clause_reference():
    # a realistic document: several normal clauses plus one oversized one.
    # two clauses where one holds 98% of the text is the disguised-failure
    # shape _worked rejects on purpose, so it would not exercise this path.
    filler = "\n".join(
        f"{n}. CLAUSE {n}. " + "The parties agree to the terms stated in this section. " * 3
        for n in range(1, 8))
    long_clause = "XXXV. DEFAULT. " + ("The Tenant shall be in default if any rent "
                                       "remains unpaid for ten days after due. ") * 20
    chunks, _ = chunk_document(filler + "\n" + long_clause)
    parts = [c for c in chunks if c.startswith("XXXV")]
    assert len(parts) > 1, "the oversized clause was not split"
    assert all(c.startswith("XXXV") for c in parts), "a split piece lost its reference"


def test_token_counter_is_used_when_supplied():
    """Production passes the real tokenizer. A deliberately harsh counter
    should force more splits than the character fallback."""
    text = (SAMPLES / "ftc_lease_sample.txt").read_text(encoding="utf-8")
    default, _ = chunk_document(text)
    harsh, _ = chunk_document(text, token_counter=lambda s: len(s) // 2)
    assert len(harsh) > len(default)


def test_warns_when_no_token_counter_on_template_text():
    """The character fallback under-splits fill-in-the-blank templates because
    underscore runs tokenize at roughly one token per character. That must be
    loud, not silent, since silent truncation is exactly what D29 was."""
    import pytest
    text = (SAMPLES / "pa_lease_sample.txt").read_text(encoding="utf-8")
    with pytest.warns(RuntimeWarning, match="token_counter"):
        chunk_document(text)


def test_no_warning_when_counter_supplied():
    import warnings as w
    text = (SAMPLES / "pa_lease_sample.txt").read_text(encoding="utf-8")
    with w.catch_warnings():
        w.simplefilter("error")
        chunk_document(text, token_counter=lambda s: len(s) // 4)
