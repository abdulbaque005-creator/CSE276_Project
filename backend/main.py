from fastapi import FastAPI, File, UploadFile, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import shutil, os, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from typing import Optional

from database import get_db, DocumentMeta, ChatHistory, User
from rag_pipeline import process_document, query_documents

import firebase_admin
from firebase_admin import auth as firebase_auth
firebase_admin.initialize_app(options={"projectId": "cse276-project"})

app = FastAPI(title="DocuMind AI API", version="2.0.0")

# ─── Auth Setup ──────────────────────────────────────────────────────────────
SECRET_KEY = "supersecretkey_change_in_production"
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_email: str = payload.get("sub")
        if user_email is None:
            raise HTTPException(status_code=401, detail="Invalid auth token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid auth token")
        
    user = db.query(User).filter(User.email == user_email).first()
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
    email: str
    password: str

class FirebaseLoginRequest(BaseModel):
    id_token: str

# ─── Auth Routes ─────────────────────────────────────────────────────────────
@app.post("/auth/register")
async def register(request: AuthRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    new_user = User(email=request.email, password_hash=get_password_hash(request.password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    token = jwt.encode({"sub": new_user.id}, SECRET_KEY, algorithm=ALGORITHM)
    return {"token": token, "email": new_user.email}

@app.post("/auth/login")
def login(request: AuthRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not user.password_hash or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    token = jwt.encode({"sub": user.email}, SECRET_KEY, algorithm=ALGORITHM)
    return {"token": token, "email": user.email}

@app.post("/auth/firebase")
def login_with_firebase(request: FirebaseLoginRequest, db: Session = Depends(get_db)):
    try:
        decoded_token = firebase_auth.verify_id_token(request.id_token)
        email = decoded_token.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Firebase token has no email")
            
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email)
            db.add(user)
            db.commit()
            db.refresh(user)
            
        token = jwt.encode({"sub": user.email}, SECRET_KEY, algorithm=ALGORITHM)
        return {"token": token, "email": user.email}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Firebase token: {str(e)}")

@app.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"email": current_user.email, "id": current_user.id}

# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "online", "version": "2.0.0"}

# ─── Upload ───────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    allowed = (".pdf", ".txt")
    if not file.filename.lower().endswith(allowed):
        raise HTTPException(status_code=400, detail="Only PDF and TXT files are supported.")

    file_path = os.path.join(UPLOAD_DIR, f"{current_user.id}_{file.filename}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        result = process_document(file_path, file.filename, user_id=current_user.id)
    except Exception as e:
        os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

    db_doc = DocumentMeta(filename=file.filename, user_id=current_user.id)
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
async def query_doc(request: QueryRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        result = query_documents(request.query, mode=request.mode or "auto", user_id=current_user.id)
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
        from rag_pipeline import vector_store
        if hasattr(vector_store, "_collection"):
            vector_store._collection.delete(where={"$and": [{"source": doc.filename}, {"user_id": current_user.id}]})
    except Exception as e:
        print(f"Error deleting from chroma: {e}")

    db.delete(doc)
    db.commit()
    return {"message": "Deleted"}

# ─── Serve Frontend ───────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
