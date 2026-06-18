import os
import uuid
import tempfile
from fastapi import APIRouter, Depends, HTTPException, Cookie, UploadFile, File, Request
from sqlalchemy.orm import Session
from typing import Optional
from backend.database.db import get_db
from backend.database.models import Document

# Try docx import
try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# Try pypdf import
try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

router = APIRouter(prefix="/api/upload", tags=["upload"])

@router.post("")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    student_id_int = int(student_id)
    filename = file.filename
    file_ext = os.path.splitext(filename)[1].lower()
    
    if file_ext not in [".pdf", ".docx", ".txt"]:
        raise HTTPException(status_code=400, detail="Only PDF, DOCX and TXT files are supported")
        
    try:
        content = ""
        # Write file content to a temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            tmp_path = tmp_file.name
            file_data = await file.read()
            tmp_file.write(file_data)
            
        # Parse text based on type
        if file_ext == ".txt":
            with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        elif file_ext == ".pdf":
            if not PDF_AVAILABLE:
                raise HTTPException(status_code=500, detail="PDF parser dependency not installed")
            reader = PdfReader(tmp_path)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    content += text + "\n"
        elif file_ext == ".docx":
            if not DOCX_AVAILABLE:
                raise HTTPException(status_code=500, detail="DOCX parser dependency not installed")
            doc = docx.Document(tmp_path)
            for para in doc.paragraphs:
                if para.text:
                    content += para.text + "\n"
                    
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
            
        if not content.strip():
            raise HTTPException(status_code=400, detail="No readable text found in the file")
            
        # Save file to permanent storage
        storage_dir = "backend/storage/documents"
        os.makedirs(storage_dir, exist_ok=True)
        permanent_path = os.path.join(storage_dir, f"{uuid.uuid4().hex}{file_ext}")
        
        with open(permanent_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        # Save to database
        db_doc = Document(
            student_id=student_id_int,
            filename=filename,
            file_path=permanent_path,
            file_type=file_ext[1:]
        )
        db.add(db_doc)
        db.commit()
        db.refresh(db_doc)
        
        # Add to RAG collection
        rag_service = request.app.state.rag_service
        if rag_service:
            rag_service.add_document(student_id_int, db_doc.id, filename, content)
        
        return {
            "status": "success",
            "document": {
                "id": db_doc.id,
                "filename": db_doc.filename,
                "file_type": db_doc.file_type
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/documents")
def get_documents(
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    documents = db.query(Document).filter(Document.student_id == int(student_id)).all()
    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "created_at": doc.created_at.isoformat()
        }
        for doc in documents
    ]
