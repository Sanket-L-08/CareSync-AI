import hashlib, re
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..models import Report, User
from ..permissions import require_patient
from ..security import current_user
from ..storage import new_key, put_encrypted, get_decrypted, storage

router = APIRouter(tags=["documents"])
MAGIC = {"application/pdf": [b"%PDF-"], "image/png": [b"\x89PNG\r\n\x1a\n"], "image/jpeg": [b"\xff\xd8\xff"]}
CATEGORIES = {"report", "lab_result", "imaging", "prescription", "discharge_summary", "insurance", "other"}


@router.post("/reports", status_code=201)
async def upload(patient_id: int = Form(...), category: str = Form("report"), file: UploadFile = File(...),
                 request: Request = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "documents:write")
    if category not in CATEGORIES:
        raise HTTPException(422, "Unknown category")
    limit = get_settings().max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, "File exceeds size limit")
    ctype = next((t for t, sigs in MAGIC.items() if any(content.startswith(s) for s in sigs)), None)
    if not ctype:  # sniff real bytes, never trust the client-supplied content type
        raise HTTPException(415, "Only PDF, JPEG and PNG files are accepted")
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", (file.filename or "document"))[:200]
    key = new_key(patient_id)
    put_encrypted(key, content)
    r = Report(patient_id=patient_id, filename=name, object_key=key, content_type=ctype, size_bytes=len(content),
               sha256=hashlib.sha256(content).hexdigest(), category=category, uploaded_by=user.id)
    db.add(r); db.commit(); audit(db, user.id, "upload", "report", r.id, patient_id, request)
    return {"id": r.id, "filename": r.filename, "content_type": ctype, "size_bytes": r.size_bytes}


@router.get("/reports")
def list_reports(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_patient(db, user, patient_id, "documents:read")
    return [{"id": r.id, "filename": r.filename, "category": r.category, "content_type": r.content_type,
             "size_bytes": r.size_bytes, "uploaded_at": r.uploaded_at}
            for r in db.scalars(select(Report).where(Report.patient_id == patient_id).order_by(desc(Report.uploaded_at)))]


@router.get("/reports/{rid}/download")
def download(rid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404, "Not found")
    require_patient(db, user, r.patient_id, "documents:read")
    data = get_decrypted(r.object_key)
    if hashlib.sha256(data).hexdigest() != r.sha256:
        raise HTTPException(500, "Integrity check failed")
    audit(db, user.id, "download", "report", rid, r.patient_id, request)
    return Response(data, media_type=r.content_type, headers={
        "Content-Disposition": f'attachment; filename="{r.filename}"', "Cache-Control": "no-store"})


@router.delete("/reports/{rid}")
def delete(rid: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404, "Not found")
    require_patient(db, user, r.patient_id, "documents:write")
    if r.uploaded_by != user.id and user.role != "clinician":
        raise HTTPException(403, "Only the uploader can delete this document")
    storage().delete(r.object_key); pid = r.patient_id
    db.delete(r); db.commit(); audit(db, user.id, "delete", "report", rid, pid, request)
    return {"ok": True}
