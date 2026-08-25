# Second half of the clause-text restoration: the two PA clauses.
#
# These come from data/sample_docs/pa_lease_sample.txt, which IS in the repo, so
# they are restored programmatically from the source rather than pasted.
#
# XXXV is the clause that started this. The gold set stored an excerpt of the
# arrest/conviction trigger and cut out "the Landlord may terminate this
# Agreement". The classifier then wrote "this allows your landlord to evict you",
# which is correct about the lease and unsupported by what we stored, so the
# faithfulness judge marked it invented. The judge was right, the model was
# right, and the ground truth was wrong.

import json
import re
import pathlib

SRC = pathlib.Path("data/sample_docs/pa_lease_sample.txt")
TEST_SET = pathlib.Path("evaluation/datasets/test_set.json")
REFS = ("XXXV", "XLIV")


def clause_text(src, ref):
    m = re.search(rf"\n{ref}\.\s.*?(?=\n[IVXLCDM]+\.\s)", src, re.DOTALL)
    if not m:
        raise SystemExit(f"could not locate clause {ref} in {SRC}")
    return re.sub(r"\s+", " ", m.group(0)).strip()


src = SRC.read_text(encoding="utf-8")
data = json.loads(TEST_SET.read_text(encoding="utf-8"))
changes = []

for doc in data["documents"]:
    if doc["doc_id"] != "lease_pa_001":
        continue
    for c in doc["clauses"]:
        if c["clause_ref"] in REFS:
            old = len(c["text"])
            c["text"] = clause_text(src, c["clause_ref"])
            c["text_restored"] = f"full clause text restored from {SRC}"
            changes.append(f"  {c['clause_ref']}: {old} -> {len(c['text'])} chars")

prov = data.setdefault("label_provenance", {}).setdefault("clause_text_corrected", {})
prov.setdefault("changes", []).extend(changes)
prov.setdefault("date", "2026-08-25")
prov.setdefault("found_by",
    "E3 faithfulness eval: the judge marked an explanation unsupported because the consequence "
    "it described had been removed from the stored clause by an ellipsis")

TEST_SET.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
for c in changes:
    print(c)

left = [(d["doc_id"], c["clause_ref"]) for d in data["documents"]
        for c in d.get("clauses", [])
        if d.get("source") != "synthetic_example" and ("..." in c["text"] or "…" in c["text"])]
print(f"\nstill abridged: {left or 'none'}")
