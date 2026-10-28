from .. import models


def invalidate_source(db, source_id: int, uid: str):
    for run in db.query(models.RetrievalRun).filter_by(user_uid=uid).all():
        if any(c.get("source_id") == source_id for r in run.result.get("requirements", []) for c in r.get("citations", [])):
            run.result = {"invalidated": True, "reason": "Source evidence changed or was removed. Run project selection again."}
    ids = {row.id for row in db.query(models.EvidenceChunk).filter_by(user_uid=uid, source_id=source_id).all()}
    draft = db.get(models.WorkspaceDraft, uid)
    if draft and ids & set(draft.data.get("evidence_ids", [])):
        draft.data = dict(draft.data, evidence_ids=[], tailored_text="", resume_logical_id=None)
        draft.revision += 1
