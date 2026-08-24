# check_leakage.py
# the few-shot examples and the eval set must never share a clause. eight of nine
# used to, which inflated every accuracy number in this repo. this fails loudly
# if it ever happens again.
#
# usage: python evaluation/check_leakage.py

import json
import re
from pathlib import Path

EXAMPLES_PATH = Path("src/prompts/few_shot_examples/clause_classification_examples.json")
TEST_SET_PATH = Path("evaluation/datasets/test_set.json")

# how much word overlap counts as "the same clause". exact-string matching is not
# enough - a near-identical sentence from a different document leaks just as badly.
OVERLAP_THRESHOLD = 0.5


def normalise(text):
    return re.sub(r"\W+", " ", text.lower()).strip()


def words(text):
    return set(normalise(text).split())


def main():
    examples = json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
    test_set = json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))

    gold = [
        (doc["doc_id"], clause["clause_ref"], clause["text"])
        for doc in test_set["documents"]
        for clause in doc["clauses"]
    ]

    problems = []
    for i, example in enumerate(examples, start=1):
        ex_words = words(example["clause"])
        for doc_id, ref, gold_text in gold:
            gold_words = words(gold_text)
            overlap = len(ex_words & gold_words) / len(ex_words | gold_words)
            if overlap >= OVERLAP_THRESHOLD:
                problems.append((i, doc_id, ref, overlap))

    print(f"checked {len(examples)} examples against {len(gold)} gold clauses")

    if problems:
        print(f"\nLEAKAGE: {len(problems)} example(s) overlap the eval set\n")
        for i, doc_id, ref, overlap in problems:
            print(f"  example {i} matches {doc_id} / {ref} (overlap {overlap:.2f})")
        raise SystemExit(1)

    print("no leakage found")


if __name__ == "__main__":
    main()