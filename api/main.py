# main.py
# fastapi backend - wraps the langgraph pipeline as a real http api instead
# of something only runnable from a terminal script.
#
# usage: uvicorn api.main:app --reload
# (run this from the project root so the src imports resolve correctly)

import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "agents"))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from graph import graph
from guardrails import validate_document, DocumentValidationError, CallBudgetError
from logging_db import log_request

app = FastAPI(title="ClauseGuard API")


class AnalyzeRequest(BaseModel):
    document_text: str
    document_type: str = "lease"


@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    try:
        validate_document(request.document_text)
    except DocumentValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    start = time.monotonic()
    try:
        result = graph.invoke(
            {"document_text": request.document_text, "document_type": request.document_type}
        )
    except (DocumentValidationError, CallBudgetError) as e:
        log_request(request.document_type, len(request.document_text), [], time.monotonic() - start, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    latency = time.monotonic() - start
    log_request(request.document_type, len(request.document_text), result["decision_report"], latency)

    return {"decision_report": result["decision_report"]}


@app.get("/health")
def health():
    return {"status": "ok"}