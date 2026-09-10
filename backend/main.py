from fastapi import FastAPI, File, UploadFile, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import shutil, os
from pydantic import BaseModel
from typing import Optional

from database import get_db, DocumentMeta, ChatHistory
from rag_pipeline import process_document, query_documents

app = FastAPI(title="DocuMind AI API", version="2.0.0")

# ─── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── Request Models ───────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str
    mode: Optional[str] = "auto"   # "auto" | "docs" | "general"

# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "online", "version": "2.0.0"}

# ─── Upload ───────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    allowed = (".pdf", ".txt")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(status_code=400, detail="Only PDF and TXT files are supported.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        result = process_document(file_path, file.filename)
    except Exception as e:
        os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

    db_doc = DocumentMeta(filename=file.filename)
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    return {
        "message": "Document processed successfully!",
        "filename": file.filename,
        "chunks": result["chunks"],
        "pages": result["pages"],
        "document_id": db_doc.id,
    }

# ─── Query ────────────────────────────────────────────────────────────────────
@app.post("/query")
async def query_doc(request: QueryRequest, db: Session = Depends(get_db)):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        result = query_documents(request.query, mode=request.mode or "auto")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

    chat_entry = ChatHistory(question=request.query, answer=result["answer"])
    db.add(chat_entry)
    db.commit()
    db.refresh(chat_entry)

    return {
        "answer": result["answer"],
        "mode_used": result["mode_used"],
        "sources": result.get("sources", []),
        "model": result.get("model", "Llama 3.3 70B"),
        "history_id": chat_entry.id,
    }

# ─── History & Documents ──────────────────────────────────────────────────────
@app.get("/history")
async def get_history(db: Session = Depends(get_db)):
    return db.query(ChatHistory).order_by(ChatHistory.created_at.desc()).limit(50).all()

@app.get("/documents")
async def get_documents(db: Session = Depends(get_db)):
    return db.query(DocumentMeta).order_by(DocumentMeta.uploaded_at.desc()).all()

@app.delete("/history/{history_id}")
async def delete_history(history_id: int, db: Session = Depends(get_db)):
    item = db.query(ChatHistory).filter(ChatHistory.id == history_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(item)
    db.commit()
    return {"message": "Deleted"}

@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(DocumentMeta).filter(DocumentMeta.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    file_path = os.path.join(UPLOAD_DIR, doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    # Clean up from vector store
    try:
        from rag_pipeline import vector_store
        if hasattr(vector_store, "_collection"):
            vector_store._collection.delete(where={"source": doc.filename})
    except Exception as e:
        print(f"Error deleting from chroma: {e}")

    db.delete(doc)
    db.commit()
    return {"message": "Deleted"}

# ─── Serve Frontend ───────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
