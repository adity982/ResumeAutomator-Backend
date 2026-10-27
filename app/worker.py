"""Run with python -m app.worker; durable jobs are claimed atomically, not in API memory."""
from __future__ import annotations

import datetime as dt
import logging
import time
from urllib.parse import quote

from sqlalchemy import or_

from . import models
from .config import settings
from .database import SessionLocal
from .services import embeddings
from .services.github_import import chunk_file
from .services.provenance import invalidate_source

logger = logging.getLogger("resume_automator.worker")


def run_once(session_factory=SessionLocal) -> bool:
    now = dt.datetime.now(dt.timezone.utc)
    with session_factory() as db:
        expired = db.query(models.IngestionJob).filter(models.IngestionJob.status == "running", models.IngestionJob.lease_until < now, models.IngestionJob.attempts >= 3).all()
        for item in expired:
            item.status, item.error = "failed", "The worker lease expired repeatedly. Retry the source after checking the worker."
            source = db.get(models.PortfolioSource, item.source_id)
            if source:
                source.status = "failed"
        db.commit()
        candidate = db.query(models.IngestionJob).filter(or_((models.IngestionJob.status == "queued") & or_(models.IngestionJob.lease_until.is_(None), models.IngestionJob.lease_until <= now), (models.IngestionJob.status == "running") & (models.IngestionJob.lease_until < now)), models.IngestionJob.attempts < 3).order_by(models.IngestionJob.id).first()
        if not candidate:
            return False
        job_id, old_status = candidate.id, candidate.status
        lease = now + dt.timedelta(seconds=settings.worker_lease_seconds)
        query = db.query(models.IngestionJob).filter_by(id=job_id, status=old_status, attempts=candidate.attempts)
        if old_status == "running":
            query = query.filter(models.IngestionJob.lease_until < now)
        if not query.update({"status": "running", "attempts": candidate.attempts + 1, "lease_until": lease}):
            db.rollback()
            return True
        db.commit()
        job = db.get(models.IngestionJob, job_id)
        if not job or job.status != "running":
            return True
        source = db.get(models.PortfolioSource, job.source_id)
        if not source:
            return True
        source.status = "processing"
        files = [f for f in source.files if f["path"] in job.paths]
        source_id, uid, repository, commit = source.id, source.user_uid, source.repository, source.commit_sha
        prior_sources = db.query(models.PortfolioSource).filter(models.PortfolioSource.user_uid == uid, models.PortfolioSource.repository == repository, models.PortfolioSource.relationship == source.relationship, models.PortfolioSource.contribution == source.contribution).all()
        prior_ids = [s.id for s in prior_sources]
        reusable = {(chunk.path, chunk.content_hash): {"embedding": chunk.embedding.tolist() if hasattr(chunk.embedding, "tolist") else chunk.embedding, "statement": chunk.approved_statement, "review_status": chunk.review_status} for chunk in db.query(models.EvidenceChunk).filter(models.EvidenceChunk.user_uid == uid, models.EvidenceChunk.source_id.in_(prior_ids), models.EvidenceChunk.embedding_version == embeddings.version()).all()}
        db.commit()
    try:
        chunks = [chunk for file in files for chunk in chunk_file(file["path"], file["content"])]
        changed = [chunk for chunk in chunks if (chunk["path"], chunk["content_hash"]) not in reusable]
        new_vectors = iter(embeddings.embed([c["content"] for c in changed]) if changed else [])
        with session_factory() as db:
            job = db.get(models.IngestionJob, job_id)
            if not job or job.status != "running" or job.lease_until.replace(tzinfo=dt.timezone.utc) != lease:
                return True
            source = db.get(models.PortfolioSource, source_id)
            db.query(models.EvidenceChunk).filter_by(source_id=source_id, user_uid=uid).delete()
            for chunk in chunks:
                previous = reusable.get((chunk["path"], chunk["content_hash"]))
                vector = previous["embedding"] if previous else next(new_vectors)
                url = f"https://github.com/{repository}/blob/{commit}/{quote(chunk['path'], safe='/')}#L{chunk['start_line']}-L{chunk['end_line']}"
                db.add(models.EvidenceChunk(user_uid=uid, source_id=source_id, source_url=url, embedding=vector, embedding_version=embeddings.version(), review_status=previous["review_status"] if previous else "observed", approved_statement=previous["statement"] if previous else "", **chunk))
            for old in db.query(models.PortfolioSource).filter(models.PortfolioSource.user_uid == uid, models.PortfolioSource.repository == repository, models.PortfolioSource.id != source_id, models.PortfolioSource.status == "ready").all():
                invalidate_source(db, old.id, uid)
                old.status = "superseded"
            source.status, job.status, job.error = "ready", "completed", ""
            job.lease_until = None
            db.commit()
    except Exception:
        logger.exception("ingestion_failed job_id=%s", job_id)
        with session_factory() as db:
            job = db.get(models.IngestionJob, job_id)
            if job and job.status == "running" and job.lease_until.replace(tzinfo=dt.timezone.utc) == lease:
                retry = job.attempts < 3
                job.status = "queued" if retry else "failed"
                job.error = "Import failed; an automatic retry is scheduled." if retry else "Import failed after three attempts. Check worker configuration and retry this source."
                job.lease_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=5 * 2 ** (job.attempts - 1)) if retry else None
                source = db.get(models.PortfolioSource, source_id)
                if source:
                    source.status = "queued" if retry else "failed"
                db.commit()
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from .config import settings
    settings.validate()
    embeddings.embed(["Worker startup warm-up"])
    while True:
        if not run_once():
            time.sleep(2)
