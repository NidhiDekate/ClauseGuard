# Restores clause text in lease_real_002 that was stored abridged.
#
# Found by E3: the faithfulness judge marked an explanation unsupported because
# the consequence it described had been cut out of the stored clause by an
# ellipsis. Checking the source lease found four abridgements and one worse
# problem.
#
# The source document is a real signed lease containing personal information and
# is deliberately NOT in this repository. Only these five clause texts were taken
# from it. All are boilerplate policy language; none contain names, addresses,
# contact details or amounts specific to the tenants.

import json
import pathlib

RESTORE = {
 "1.7.D": ("This lease automatically renews under the same terms defined in Section 1.2 Lease "
           "Specifications with a $100.00 per month rental increase unless another lease, an "
           "addendum and/or a lease extension is executed, or written notice of non-renewal is "
           "given 120 days before expiration. The right to renew this lease is entirely at the "
           "discretion of the Landlord. It is tenant(s) responsibility to ask Landlord if lease "
           "is being renewed or not."),
 "2.12.B": ("Landlord has the right to enter the leased property at any time without advance "
            "notice. Landlord, or authorized person chosen by Landlord, has the right to inspect, "
            "show, make repairs, and do maintenance even if the Tenant is not at home."),
 "1.10": ("The total security deposit at the time of execution of this Lease Contract for all "
          "residents in the house or apartment is defined in Section 1.2, due on or before the "
          "date this Lease Contract is signed. We will hold the security deposit for the term of "
          "the tenancy and, upon termination of the tenancy, reserve the right to use the security "
          "deposit, or portions thereof, to cover any charges related to your performance of this "
          "Lease Contract, including, but not limited to, cleaning, repair of damages, unpaid "
          "rent, late fees, and returned check fees."),
 "4.1": ("No smoking or vaping inside the property. If you are found in violation of this rule, "
         "you will be charged a $500.00 fine and Landlord has the right to terminate the lease "
         "immediately. Landlord will use own discretion based off of observed condition of "
         "property to determine if smoking or vaping has occurred in property ie. smell of smoke, "
         "color of walls, etc."),
}

# 2.13 in the gold set was two unrelated clauses spliced together under a third
# clause's number:
#   first half  came from 2.1  NOTICE TO QUIT
#   second half came from 2.21 REPORTING OF PAST RENT OWED
#   2.13 itself is LEAD BASED PAINT and has nothing to do with either
# 2.1 is already in the gold set separately, so the Notice to Quit waiver was
# being counted twice. Replaced with the real 2.21.
REPLACE = {
 "2.13": {
   "clause_ref": "2.21",
   "text": ("Tenant is aware that Landlord may report any past rent, damages, utilities or other "
            "costs owed by Tenant to a credit reporting agency. Tenant understands this reporting "
            "could affect Tenant's ability to obtain credit or future housing."),
 }
}

path = pathlib.Path("evaluation/datasets/test_set.json")
data = json.loads(path.read_text(encoding="utf-8"))
changes = []

for doc in data["documents"]:
    if doc["doc_id"] != "lease_real_002":
        continue
    for clause in doc["clauses"]:
        ref = clause["clause_ref"]
        if ref in RESTORE:
            old_len = len(clause["text"])
            clause["text"] = RESTORE[ref]
            clause["text_restored"] = "full clause text restored from the source lease"
            changes.append(f"  {ref}: {old_len} -> {len(clause['text'])} chars")
        elif ref in REPLACE:
            r = REPLACE[ref]
            clause["clause_ref"] = r["clause_ref"]
            clause["text"] = r["text"]
            clause["text_restored"] = (
                "was a splice of 2.1 (Notice to Quit) and 2.21 (Reporting of Past Rent Owed) "
                "filed under 2.13 (Lead Based Paint). 2.1 is already in this set separately, so "
                "the Notice to Quit waiver was counted twice. Replaced with the real 2.21.")
            changes.append(f"  {ref} -> {r['clause_ref']}: fabricated splice replaced")

prov = data.setdefault("label_provenance", {})
prov["clause_text_corrected"] = {
  "date": "2026-08-25",
  "found_by": "E3 faithfulness eval: the judge marked an explanation unsupported because the "
              "consequence it described had been removed from the stored clause by an ellipsis",
  "note": "Source lease contains personal information and is deliberately not in this repository. "
          "Only the five clause texts below were taken from it, all boilerplate policy language.",
  "changes": changes,
}

path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

print("restored:")
for c in changes:
    print(c)

remaining = [(d["doc_id"], c["clause_ref"]) for d in data["documents"]
             for c in d.get("clauses", [])
             if d.get("source") != "synthetic_example" and ("..." in c["text"] or "…" in c["text"])]
print(f"\nclauses still containing an ellipsis: {len(remaining)}")
for r in remaining:
    print("  ", r[0], "/", r[1])

refs = [c["clause_ref"] for d in data["documents"] if d["doc_id"] == "lease_real_002"
        for c in d["clauses"]]
dupes = [r for r in set(refs) if refs.count(r) > 1]
print(f"duplicate clause_refs in lease_real_002: {dupes or 'none'}")
