# app.py
# streamlit ui - pick a sample or upload a document, hit analyze, get a real
# decision report back from the fastapi backend.
#
# usage: streamlit run frontend/app.py
# (make sure the backend is running first: uvicorn api.main:app --reload)

import os
from pathlib import Path

import requests
import streamlit as st

# localhost works for local dev (both running directly on your machine).
# inside docker, each service is its own container, so this gets overridden
# to the api container's service name instead - see docker-compose.yml
API_URL = os.environ.get("CLAUSEGUARD_API_URL", "http://localhost:8000/analyze")

SAMPLE_DOCS = {
    "PA lease template": "data/sample_docs/pa_lease_sample.txt",
    "FTC sample lease": "data/sample_docs/ftc_lease_sample.txt",
}

st.set_page_config(page_title="ClauseGuard", page_icon="📄")
st.title("ClauseGuard")
st.caption("Understand a lease in under a minute — every finding backed by the exact clause it came from.")

st.subheader("1. Choose a document")
choice = st.radio("Source", ["Try a sample", "Upload my own"])

if choice == "Try a sample":
    sample_name = st.selectbox("Pick a sample", list(SAMPLE_DOCS.keys()))
    if st.button("Load sample"):
        st.session_state["document_text"] = Path(SAMPLE_DOCS[sample_name]).read_text(encoding="utf-8")
else:
    uploaded = st.file_uploader("Upload a .txt lease document", type=["txt"])
    if uploaded is not None:
        st.session_state["document_text"] = uploaded.read().decode("utf-8")

if "document_text" in st.session_state:
    with st.expander("Preview document"):
        st.text(st.session_state["document_text"][:1000] + "...")

    if st.button("Analyze", type="primary"):
        with st.spinner("Analyzing document..."):
            response = requests.post(
                API_URL,
                json={"document_text": st.session_state["document_text"], "document_type": "lease"},
            )

        if response.status_code != 200:
            st.error(f"Something went wrong: {response.json().get('detail', 'unknown error')}")
        else:
            report = response.json()["decision_report"]

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

            for finding in report:
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