from __future__ import annotations

import hashlib
import itertools
import re
import time
from collections import Counter

from sqlalchemy import func

from .. import models
from . import embeddings
from .ai import TECH_SKILLS, tokens


def requirements(text: str) -> list[dict]:
    parts = [s.strip(" -*•\t") for s in re.split(r"\n+|(?<=[.!?;])\s+", text) if len(s.strip()) >= 10]
    if not parts:
        parts = [text]
    return [{"id": f"r{i + 1}", "text": part[:800], "priority": "preferred" if re.search(r"\b(preferred|bonus|nice to have)\b", part, re.I) else "required", "skills": sorted(set(tokens(part)) & TECH_SKILLS)} for i, part in enumerate(parts[:12])]


def lexical_score(query: str, content: str) -> float:
    terms, document = set(tokens(query)), set(tokens(content))
    if not terms:
        return 0.0
    skill_terms = terms & TECH_SKILLS
    return (2 * len(skill_terms & document) + len((terms - TECH_SKILLS) & document)) / max(2 * len(skill_terms) + len(terms - TECH_SKILLS), 1)


def rank(query: str, chunks: list, query_vector=None, mode: str = "hybrid") -> list[dict]:
    lex = {c.id: lexical_score(query, c.content + " " + c.approved_statement) for c in chunks}
    dense = {c.id: embeddings.cosine(query_vector, c.embedding) for c in chunks if c.embedding_version == embeddings.version() and query_vector is not None}
    lexical_order = sorted((c for c in chunks if lex[c.id] > 0), key=lambda c: (-lex[c.id], c.id))[:30]
    dense_order = sorted((c for c in chunks if dense.get(c.id, 0) >= 0.45), key=lambda c: (-dense[c.id], c.id))[:30]
    scores: Counter = Counter()
    orders = [lexical_order] if mode == "lexical" else [dense_order] if mode == "dense" else [lexical_order, dense_order]
    for order in orders:
        for position, chunk in enumerate(order):
            scores[chunk.id] += 1 / (60 + position + 1)
    lookup = {c.id: c for c in chunks}
    return [{"chunk": lookup[key], "fusion_score": scores[key], "lexical": lex[key], "semantic": dense.get(key)} for key in sorted(scores, key=lambda key: (-scores[key], key))[:8]]


def active_chunks(db, uid: str):
    return db.query(models.EvidenceChunk).join(models.PortfolioSource).filter(models.EvidenceChunk.user_uid == uid, models.PortfolioSource.user_uid == uid, models.PortfolioSource.status == "ready", models.EvidenceChunk.review_status != "rejected").order_by(models.EvidenceChunk.id).all()


def supports(requirement: dict, entry: dict) -> bool:
    chunk = entry["chunk"]
    explicit_skills = set(requirement["skills"])
    observed_terms = set(tokens(chunk.content))
    sufficient = explicit_skills <= observed_terms if explicit_skills else entry["lexical"] >= 0.25 or (entry["semantic"] or 0) >= 0.68
    return sufficient and chunk.review_status == "approved" and bool(chunk.approved_statement)


def citation(chunk, sources):
    source = sources[chunk.source_id]
    return {"evidence_id": chunk.id, "source_id": source.id, "repository": source.repository, "commit_sha": source.commit_sha, "path": chunk.path, "start_line": chunk.start_line, "end_line": chunk.end_line, "url": chunk.source_url, "excerpt": chunk.content[:900], "statement": chunk.approved_statement, "review_status": chunk.review_status, "contribution": source.contribution, "relationship": source.relationship}


def recommend(db, uid: str, job, max_projects: int = 2, mode: str = "hybrid") -> dict:
    started = time.perf_counter()
    chunks = active_chunks(db, uid)
    sources = {s.id: s for s in db.query(models.PortfolioSource).filter_by(user_uid=uid, status="ready").all()}
    reqs = requirements(job.description)
    vectors = embeddings.embed([r["text"] for r in reqs], query=True) if chunks else [None] * len(reqs)
    matches, coverage = [], {}
    for requirement, vector in zip(reqs, vectors):
        # pgvector performs an exact, tenant-scoped similarity query in PostgreSQL.
        # SQLite uses the same cosine semantics over the bounded personal corpus.
        candidates = chunks
        if db.bind.dialect.name == "postgresql" and vector is not None:
            dense_ids = [row.id for row in db.query(models.EvidenceChunk).join(models.PortfolioSource).filter(models.EvidenceChunk.user_uid == uid, models.PortfolioSource.user_uid == uid, models.PortfolioSource.status == "ready", models.EvidenceChunk.review_status != "rejected", models.EvidenceChunk.embedding_version == embeddings.version(), models.EvidenceChunk.embedding.is_not(None)).order_by(models.EvidenceChunk.embedding.cosine_distance(vector)).limit(30).all()]
            search = func.websearch_to_tsquery("english", requirement["text"])
            lexical_ids = [row.id for row in db.query(models.EvidenceChunk).join(models.PortfolioSource).filter(models.EvidenceChunk.user_uid == uid, models.PortfolioSource.user_uid == uid, models.PortfolioSource.status == "ready", models.EvidenceChunk.review_status != "rejected").order_by(func.ts_rank_cd(func.to_tsvector("english", models.EvidenceChunk.content), search).desc()).limit(30).all()]
            candidates = [c for c in chunks if c.id in set(dense_ids + lexical_ids)]
        ranked = rank(requirement["text"], candidates, vector, mode)
        supported = []
        for entry in ranked:
            chunk = entry["chunk"]
            # Only a reviewed, user-authored statement can become a personal claim.
            if supports(requirement, entry):
                supported.append(entry)
                coverage.setdefault(chunk.source_id, set()).add(requirement["id"])
        matches.append({**requirement, "status": "supported" if supported else "partial" if ranked and ranked[0]["lexical"] >= 0.12 else "missing", "citations": [dict(citation(e["chunk"], sources), lexical_score=round(e["lexical"], 4), semantic_similarity=round(e["semantic"], 4) if e["semantic"] is not None else None) for e in (supported or ranked[:1])[:3]]})
    source_ids = sorted(coverage)
    weights = {r["id"]: 1 if r["priority"] == "preferred" else 2 for r in reqs}
    combinations = [combination for size in range(1, min(max_projects, len(source_ids)) + 1) for combination in itertools.combinations(source_ids, size)]
    def objective(combination):
        covered = set().union(*(coverage[s] for s in combination))
        return sum(weights[r] for r in covered), -len(combination)
    chosen = max(combinations, key=objective) if combinations else ()
    bullets, used = [], set()
    for match in matches:
        for evidence in match["citations"] if match["status"] == "supported" else []:
            if evidence["source_id"] in chosen and evidence["evidence_id"] not in used:
                bullets.append({"text": evidence["statement"], "requirement_id": match["id"], "citation": evidence})
                used.add(evidence["evidence_id"])
    fingerprint = hashlib.sha256((job.content_hash + str([(c.id, c.content_hash, c.review_status, c.approved_statement, c.embedding_version) for c in chunks]) + embeddings.version() + str(max_projects) + mode).encode()).hexdigest()
    return {"job_id": job.id, "requirements": matches, "projects": [{"source_id": sid, "repository": sources[sid].repository, "reason": f"Supports {len(coverage[sid])} reviewed requirements; selected to complement the other projects.", "requirement_ids": sorted(coverage[sid])} for sid in chosen], "excluded_projects": [{"source_id": sid, "repository": source.repository, "reason": "No additional reviewed requirement coverage within the project limit."} for sid, source in sources.items() if sid not in chosen], "bullets": bullets[:6], "warnings": ["Repository observations are not proof of personal authorship.", "Suggested bullets reproduce your reviewed statements; they are not independently verified."] + (["Semantic embeddings are disabled. Results use the lexical baseline."] if embeddings.version() == "none" else []), "method": "hybrid-rrf-extractive-v1" if embeddings.version() != "none" and mode == "hybrid" else f"{mode}-extractive-v1", "embedding_version": embeddings.version(), "input_fingerprint": fingerprint, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "external_generation_cost_usd": 0}
