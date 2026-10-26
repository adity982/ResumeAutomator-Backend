"""Run python -m evaluations.run --output evaluation-results/retrieval.json."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from types import SimpleNamespace

from app.services import embeddings, retrieval


def evaluate(dataset):
    started = time.perf_counter()
    vectors = embeddings.embed([row["text"] for row in dataset["documents"]])
    chunks = [SimpleNamespace(id=row["id"], content=row["text"], approved_statement=row["text"] if row["approved"] else "", review_status="approved" if row["approved"] else "observed", embedding=vector, embedding_version=embeddings.version()) for row, vector in zip(dataset["documents"], vectors)]
    modes = ["lexical"] if embeddings.version() == "none" else ["lexical", "dense", "hybrid"]
    results = []
    for mode in modes:
        for split in ["development", "heldout"]:
            recalls, ndcgs, abstentions, durations = [], [], [], []
            for case in [c for c in dataset["cases"] if c["split"] == split]:
                clock = time.perf_counter()
                vector = embeddings.embed([case["query"]], query=True)[0] if mode != "lexical" else None
                ranked = retrieval.rank(case["query"], chunks, vector, mode)
                requirement = retrieval.requirements(case["query"])[0]
                relevant = set(case["relevant"])
                ids = [entry["chunk"].id for entry in ranked[:3]]
                if relevant:
                    recalls.append(len(set(ids) & relevant) / len(relevant))
                    dcg = sum(1 / math.log2(index + 2) for index, item in enumerate(ids) if item in relevant)
                    ideal = sum(1 / math.log2(index + 2) for index in range(min(3, len(relevant))))
                    ndcgs.append(dcg / ideal)
                else:
                    abstentions.append(not any(retrieval.supports(requirement, entry) for entry in ranked))
                durations.append((time.perf_counter() - clock) * 1000)
            results.append({"mode": mode, "split": split, "answerable_cases": len(recalls), "unanswerable_cases": len(abstentions), "recall_at_3": round(sum(recalls) / max(len(recalls), 1), 4), "ndcg_at_3": round(sum(ndcgs) / max(len(ndcgs), 1), 4), "abstention_accuracy": round(sum(abstentions) / max(len(abstentions), 1), 4), "warm_query_p95_ms": round(sorted(durations)[max(0, math.ceil(len(durations) * .95) - 1)], 2)})
    return {"dataset": dataset["version"], "cases": len(dataset["cases"]), "embedding_version": embeddings.version(), "runtime_seconds": round(time.perf_counter() - started, 2), "external_generation_cost_usd": 0, "limitations": [dataset["limitations"], "Latency includes warm query embedding and ranking over a small in-memory corpus; this is not a production database load test.", "Citation lifecycle, ownership and unsupported-claim behavior are covered separately by API regression tests.", "No reranker is enabled; an extra model should only be added after a justified quality/latency comparison."], "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evaluation-results/retrieval.json")
    args = parser.parse_args()
    dataset = json.loads(Path(__file__).with_name("retrieval-v1.json").read_text())
    result = evaluate(dataset)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
