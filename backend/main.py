from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import shutil, os, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from typing import Optional

from database import get_db, DocumentMeta, ChatHistory, User, engine, Base
from rag_pipeline import process_document, query_documents

# Firebase removed

app = FastAPI(title="DocuMind AI API", version="2.0.0")

@app.on_event("startup")
def on_startup():
    print("Starting up: Connecting to database and creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Database connected successfully!")

# ─── Auth Setup ──────────────────────────────────────────────────────────────
SECRET_KEY = "supersecretkey_change_in_production"
ALGORITHM = "HS256"
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid auth token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid auth token")
        
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

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

class AuthRequest(BaseModel):
    username: str

# ─── Auth Routes ─────────────────────────────────────────────────────────────
@app.post("/auth/login")
def login(request: AuthRequest, db: Session = Depends(get_db)):
    if not request.username or not request.username.strip():
        raise HTTPException(status_code=400, detail="Username cannot be empty")
        
    username = request.username.strip()
    user = db.query(User).filter(User.username == username).first()
    
    # Auto-register if user doesn't exist
    if not user:
        user = User(username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    
    token = jwt.encode({"sub": user.username}, SECRET_KEY, algorithm=ALGORITHM)
    return {"token": token, "username": user.username}

@app.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "id": current_user.id}

# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "online", "version": "2.0.0"}

# ─── Upload ───────────────────────────────────────────────────────────────────
from fastapi import BackgroundTasks

def background_process(final_path: str, filename: str, user_id: int, db_doc_id: int, db: Session):
    try:
        from rag_pipeline import process_document
        process_document(final_path, filename, user_id=user_id)
        # We could update the DB doc status here if we added a status field
    except Exception as e:
        print(f"Background processing failed for {filename}: {e}")
    finally:
        # Keep the file for debugging or remove it if desired
        pass

@app.post("/upload_chunk")
async def upload_chunk(
    background_tasks: BackgroundTasks,
    chunk: UploadFile = File(...), 
    filename: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    temp_dir = os.path.join(UPLOAD_DIR, "temp", str(current_user.id))
    os.makedirs(temp_dir, exist_ok=True)
    chunk_path = os.path.join(temp_dir, f"{filename}.part{chunk_index}")
    
    with open(chunk_path, "wb") as buffer:
        shutil.copyfileobj(chunk.file, buffer)
        
    if chunk_index == total_chunks - 1:
        final_path = os.path.join(UPLOAD_DIR, f"{current_user.id}_{filename}")
        with open(final_path, "wb") as final_file:
            for i in range(total_chunks):
                part_path = os.path.join(temp_dir, f"{filename}.part{i}")
                with open(part_path, "rb") as part_file:
                    shutil.copyfileobj(part_file, final_file)
                os.remove(part_path)
                
        db_doc = DocumentMeta(filename=filename, user_id=current_user.id)
        db.add(db_doc)
        db.commit()
        db.refresh(db_doc)

        background_tasks.add_task(background_process, final_path, filename, current_user.id, db_doc.id, db)

        return {
            "message": "Document uploaded and processing in background!",
            "filename": filename,
            "chunks": "Your document is",
            "pages": "Processing",
            "document_id": db_doc.id,
        }
    return {"message": "Chunk received"}

# ─── Query ────────────────────────────────────────────────────────────────────
@app.post("/query")
async def query_doc(request: QueryRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        result = query_documents(request.query, mode=request.mode or "auto", user_id=current_user.id, username=current_user.username)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

    chat_entry = ChatHistory(question=request.query, answer=result["answer"], user_id=current_user.id)
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
async def get_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(ChatHistory).filter(ChatHistory.user_id == current_user.id).order_by(ChatHistory.created_at.desc()).limit(50).all()

@app.get("/documents")
async def get_documents(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(DocumentMeta).filter(DocumentMeta.user_id == current_user.id).order_by(DocumentMeta.uploaded_at.desc()).all()

@app.delete("/history/{history_id}")
async def delete_history(history_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(ChatHistory).filter(ChatHistory.id == history_id, ChatHistory.user_id == current_user.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(item)
    db.commit()
    return {"message": "Deleted"}

@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    doc = db.query(DocumentMeta).filter(DocumentMeta.id == doc_id, DocumentMeta.user_id == current_user.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    file_path = os.path.join(UPLOAD_DIR, f"{current_user.id}_{doc.filename}")
    if os.path.exists(file_path):
        os.remove(file_path)

    # Clean up from vector store
    try:
        from rag_pipeline import get_vector_store
        vs = get_vector_store()
        vs.delete(filter={"user_id": current_user.id, "source": doc.filename})
    except Exception as e:
        print(f"Error deleting from vector store: {e}")

    db.delete(doc)
    db.commit()
    return {"message": "Deleted"}

# ─── Serve Frontend ───────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
