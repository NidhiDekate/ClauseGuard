# streamlit_app.py
# entry point for streamlit community cloud specifically. calls the
# langgraph pipeline directly rather than over http to a separate fastapi
# service, because streamlit cloud only runs one process - it "handles
# containerization" itself and doesn't support a second service alongside it.
#
# the real fastapi + streamlit split (api/main.py + frontend/app.py) is
# still the actual architecture, still fully documented, still what you'd
# run in local dev or any real multi-service deployment. this file exists
# specifically because free-tier single-process hosting is a real, common
# constraint - not a downgrade of the design, just a different packaging
# of the same pipeline for this one hosting target.
#
# to run locally exactly as streamlit cloud will run it:
#   streamlit run streamlit_app.py

import sys
import time
from pathlib import Path

import os

import streamlit as st

# Streamlit Cloud puts secrets in st.secrets. Everything under src/ reads
# os.environ, because that is what .env gives you in local dev. Copy one into
# the other before anything imports a model, so there is exactly one place keys
# come from and the deployed app behaves like the local one.
#
# Local runs have no secrets.toml and st.secrets raises rather than returning
# empty, so this is wrapped. .env is already loaded by then.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

sys.path.append(str(Path(__file__).resolve().parent / "src" / "agents"))

from graph import graph
sys.path.append(str(Path(__file__).resolve().parent / "src"))
from llm import reset_circuit_breaker, FALLBACKS
from guardrails import validate_document, DocumentValidationError, CallBudgetError
from logging_db import log_request

SAMPLE_DOCS = {
    "PA lease template": "data/sample_docs/pa_lease_sample.txt",
    "FTC sample lease": "data/sample_docs/ftc_lease_sample.txt",
}

st.set_page_config(page_title="ClauseGuard", page_icon="📄")
st.title("ClauseGuard")
st.caption("Understand a lease in under a minute — every finding backed by the exact clause it came from.")
st.caption("⚠️ Educational AI engineering project. Not legal advice.")

st.subheader("1. Choose a document")
choice = st.radio("Source", ["Try a sample", "Upload my own"])

if choice == "Try a sample":
    sample_name = st.selectbox("Pick a sample", list(SAMPLE_DOCS.keys()))
    # load on selection change, not only on the button. changing the dropdown and
    # pressing Analyze used to silently re-analyse whichever document was loaded
    # last, which produced two identical reports for two different leases.
    if st.session_state.get("loaded_sample") != sample_name or st.button("Load sample"):
        st.session_state["document_text"] = Path(SAMPLE_DOCS[sample_name]).read_text(encoding="utf-8")
        st.session_state["loaded_sample"] = sample_name
else:
    uploaded = st.file_uploader("Upload a .txt lease document", type=["txt"])
    if uploaded is not None:
        st.session_state["document_text"] = uploaded.read().decode("utf-8")

if "document_text" in st.session_state:
    with st.expander("Preview document"):
        st.text(st.session_state["document_text"][:1000] + "...")

    if st.button("Analyze", type="primary"):
        doc_text = st.session_state["document_text"]

        try:
            validate_document(doc_text)
        except DocumentValidationError as e:
            st.error(str(e))
            st.stop()

        with st.spinner("Analyzing document... real model calls happening, takes about a minute"):
            start = time.monotonic()
            reset_circuit_breaker()
            try:
                result = graph.invoke({"document_text": doc_text, "document_type": "lease"})
            except (DocumentValidationError, CallBudgetError) as e:
                st.error(str(e))
                st.stop()
            elapsed = time.monotonic() - start

        report = result["decision_report"]

        # this entry point never logged anything. api/main.py did, but this is
        # the file streamlit community cloud actually runs, so the live app was
        # recording nothing at all. note the db is ephemeral on streamlit cloud
        # (fresh filesystem every restart) - this is useful locally and under
        # docker, where data/ is a volume.
        log_request("lease", len(doc_text), report, elapsed)

        st.caption(f"Analyzed in {elapsed:.1f}s")

        # Say it out loud when a node did not run on the model it was meant to.
        # The Reviewer is supposed to be a second opinion from a different
        # vendor; if it quietly ran on the same model as the classifier, the
        # check is weaker than the documentation claims and the reader deserves
        # to know before they trust the result.
        if FALLBACKS:
            swapped = {f"{f['wanted']} to {f['used']}" for f in FALLBACKS}
            st.warning(
                "Ran on a backup model. "
                + "; ".join(sorted(swapped))
                + ". The primary provider failed, so results may differ from a "
                "normal run, and the Reviewer may have used the same model as "
                "the classifier rather than an independent one."
            )

        concerning = [f for f in report if f.get("label") == "concerning"]
        neutral = [f for f in report if f.get("label") == "neutral"]
        favorable = [f for f in report if f.get("label") == "favorable"]
        not_addressed = [f for f in report if f["status"] == "not_addressed"]

        st.subheader("2. Decision report")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Concerning", len(concerning))
        col2.metric("Neutral", len(neutral))
        col3.metric("Favorable", len(favorable))
        col4.metric("Not addressed", len(not_addressed))
        errors = [f for f in report if f["status"] == "error"]
        if errors:
            st.error(f"{len(errors)} of {len(report)} categories could not be analysed. "
                     f"Those are not findings about your document.")

        for finding in report:
            if finding["status"] == "error":
                st.warning(
                    f"**{finding['category']}** — analysis failed, so nothing can be said "
                    f"about this either way")
                with st.expander("What went wrong"):
                    st.code(finding.get("detail", "unknown"))
                continue

            if finding["status"] == "not_addressed":
                st.info(f"**{finding['category']}** — not addressed in this document")
                continue

            label = finding["label"]
            icon = {"concerning": "🔴", "neutral": "⚪", "favorable": "🟢"}.get(label, "⚫")
            with st.expander(f"{icon} {finding['category']} — {label.upper()}"):
                st.write(finding["reason"])
                if "fee_exposure_10_days_late" in finding:
                    st.write(f"**Estimated exposure at 10 days late:** ${finding['fee_exposure_10_days_late']}")
                st.caption(f"Source: {finding['clause']}")
