import os
import ssl
import logging

# ─── Fix macOS SSL certificate issue ─────────────────────────────────────────
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except ImportError:
    pass

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.chains import create_retrieval_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ─── Configure Pinecone ──────────────────────────────────────────────────────
os.environ["PINECONE_API_KEY"] = "pcsk_2ptkdX_PMxhRQckynoyxhsXqfi15pTedk5LA8NUFn79uEuknhPhnL5oVnbMrYT9i1vQKX4"

# ─── Ultra-Smart LLM Setup ────────────────────────────────────────────────────
# Primary: 120B parameter model — maximum intelligence available
llm_primary = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.5,
    api_key=GROQ_API_KEY,
)

# Faster model for quick or lightweight queries
llm_reasoning = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.4,
    api_key=GROQ_API_KEY,
)

# ─── Smart Embeddings Setup ───────────────────────────────────────────────────
def _init_embeddings():
    # 1. Try HuggingFace sentence-transformers (best local semantic search)
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        emb = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
        )
        logger.info("✅ Using HuggingFace semantic embeddings (all-MiniLM-L6-v2)")
        return emb
    except Exception as e:
        logger.warning(f"HuggingFace embeddings failed: {e}")

    # 2. Fallback: Google embeddings if valid key
    if GOOGLE_API_KEY.startswith("AIza"):
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            emb = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
            logger.info("✅ Using Google semantic embeddings")
            return emb
        except Exception as e:
            logger.warning(f"Google embeddings failed: {e}")

    # 3. Last resort: deterministic local embeddings
    from langchain_community.embeddings import FakeEmbeddings
    logger.warning("⚠️ Using FakeEmbeddings – install sentence-transformers for real search")
    return FakeEmbeddings(size=384)

embeddings = None
vector_store = None

def get_vector_store():
    global embeddings, vector_store
    if vector_store is None:
        embeddings = _init_embeddings()
        vector_store = PineconeVectorStore(index_name="documind", embedding=embeddings)
    return vector_store


# ─── Document Processing (with OCR for scanned PDFs) ─────────────────────────
def _extract_pdf_with_ocr(file_path: str) -> list:
    """Extract text from PDF using PyMuPDF, with EasyOCR fallback for image pages."""
    import fitz  # PyMuPDF

    doc = fitz.open(file_path)
    pages = []
    ocr_reader = None  # lazy-load EasyOCR only if needed

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text").strip()

        # If no text found, try OCR on the page image
        if not text or len(text) < 20:
            logger.info(f"Page {page_num+1}: No text found, running OCR...")
            try:
                if ocr_reader is None:
                    import easyocr
                    ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)

                # Render page to image at 100 DPI for faster OCR processing (sacrifices slight accuracy for massive speedup)
                pix = page.get_pixmap(dpi=100)
                img_bytes = pix.tobytes("png")

                import io
                from PIL import Image
                import numpy as np
                img = Image.open(io.BytesIO(img_bytes))
                img_array = np.array(img)

                results = ocr_reader.readtext(img_array, detail=0, paragraph=True)
                text = "\n".join(results).strip()
                logger.info(f"Page {page_num+1}: OCR extracted {len(text)} characters")
            except Exception as e:
                logger.warning(f"OCR failed on page {page_num+1}: {e}")
                text = ""

        if text:
            pages.append({"text": text, "page": page_num + 1})

    doc.close()
    return pages


def process_document(file_path: str, filename: str, user_id: int = None) -> dict:
    logger.info(f"Processing: {filename}")

    from langchain_core.documents import Document

    if file_path.lower().endswith(".pdf"):
        # Use our custom extractor with OCR fallback
        extracted_pages = _extract_pdf_with_ocr(file_path)

        if not extracted_pages:
            raise ValueError(
                "Could not extract any text from this PDF, even with OCR. "
                "The file may be corrupted or contain only complex graphics."
            )

        docs = [
            Document(
                page_content=p["text"],
                metadata={"source": filename, "page": p["page"], "user_id": user_id or 0}
            )
            for p in extracted_pages
        ]
    else:
        loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()
        for doc in docs:
            doc.metadata["source"] = filename
            doc.metadata["user_id"] = user_id or 0

    # Hierarchical chunking
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=300,
        separators=["\n\n\n", "\n\n", "\n", ". ", "! ", "? ", " ", ""],
    )
    chunks = text_splitter.split_documents(docs)

    if not chunks:
        raise ValueError(
            "Could not extract meaningful text chunks from this document."
        )

    vs = get_vector_store()
    vs.add_documents(chunks)
    logger.info(f"Indexed {len(chunks)} chunks from {len(docs)} pages")
    return {"chunks": len(chunks), "pages": len(docs)}


# ─── Query Complexity Classifier ─────────────────────────────────────────────
def _is_complex_query(query: str) -> bool:
    """Detect if query needs deep reasoning model."""
    complex_keywords = [
        "analyze", "analyse", "compare", "explain why", "how does",
        "reason", "evaluate", "critique", "summarize", "what are the implications",
        "pros and cons", "difference between", "relationship", "prove", "argue",
    ]
    q = query.lower()
    return any(kw in q for kw in complex_keywords) or len(query.split()) > 20

def _is_general_query(query: str, llm) -> bool:
    """Fast check to see if query is general knowledge vs document-dependent."""
    system = "You are a smart router. Does this user query ask a general knowledge/programming question (e.g. 'what is machine learning', 'write a function') where you should reply 'GENERAL', or does it refer to specific uploaded documents/data (e.g. 'summarize this', 'what does the report say') where you should reply 'DOCUMENT'? Reply with exactly one word: 'GENERAL' or 'DOCUMENT'."
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        res = llm.invoke([SystemMessage(content=system), HumanMessage(content=query)])
        return "GENERAL" in res.content.upper()
    except Exception as e:
        logger.warning(f"Routing error: {e}")
        return False

# ─── Hybrid Query Engine ──────────────────────────────────────────────────────
def query_documents(query: str, mode: str = "auto", user_id: int = None, username: str = "User") -> dict:
    logger.info(f"Query [mode={mode}] from {username}: {query[:100]}")

    # Choose model based on query complexity
    llm = llm_primary if _is_complex_query(query) else llm_reasoning
    model_name = "GPT-OSS 120B (Max)" if llm == llm_primary else "GPT-OSS 20B (Fast)"
    logger.info(f"Selected model: {model_name}")

    # Smart Routing for Auto Mode
    is_general = False
    if mode == "general":
        is_general = True
    elif mode == "auto":
        is_general = _is_general_query(query, llm_reasoning)
        logger.info(f"Auto Router classified query as: {'GENERAL' if is_general else 'DOCUMENT'}")

    if is_general:
        answer = _general_ai_answer(query, llm, username=username)
        return {"answer": answer, "mode_used": "general", "sources": [], "model": model_name}

    # Retrieve docs
    relevant_docs = []
    try:
        search_kwargs = {"k": 6}
        if user_id is not None:
            search_kwargs["filter"] = {"user_id": user_id}

        vs = get_vector_store()
        retriever = vs.as_retriever(
            search_type="similarity",
            search_kwargs=search_kwargs,
        )
        relevant_docs = retriever.invoke(query)
    except Exception as e:
        logger.warning(f"Retrieval error: {e}")

    if not relevant_docs:
        # Fallback if DB is totally empty
        answer = _general_ai_answer(query, llm, username=username)
        return {"answer": answer, "mode_used": "general", "sources": [], "model": model_name}

    answer, sources = _rag_answer(query, relevant_docs, llm, username=username)
    return {"answer": answer, "mode_used": "rag", "sources": sources, "model": model_name}


# ─── General World-Knowledge Answer ──────────────────────────────────────────
def _general_ai_answer(query: str, llm, username: str = "User") -> str:
    system = SystemMessage(content=f"""You are DocuMind, an elite-level AI assistant powered by cutting-edge language models. You combine the depth of a PhD researcher, the clarity of a world-class teacher, and the creativity of an expert communicator.

The user's name is **{username}**. Address them by their name naturally in your responses (e.g., "Great question {username}!", "Here's what I found for you {username}"). Be warm, friendly, and personal.

Your responses must be:
- **Comprehensive**: Cover all important aspects of the question
- **Structured**: Use ## headers, bullet points (- item), numbered lists where logical
- **Rich**: Include **bold** for key terms, `code` for technical terms, and ```language\ncode\n``` blocks for any code
- **Accurate**: Provide factual, up-to-date information
- **Insightful**: Go beyond surface-level answers — provide context, examples, nuances
- **Well-formatted**: Tables where comparisons help, blockquotes for important notes

Always end complex answers with a brief **Summary** or **Key Takeaways** section.""")

    human = HumanMessage(content=query)
    response = llm.invoke([system, human])
    return response.content


# ─── RAG Document Answer ──────────────────────────────────────────────────────
def _rag_answer(query: str, docs: list, llm, username: str = "User") -> tuple:
    system_prompt = f"""You are DocuMind, an elite AI document analyst and research assistant. You have been given retrieved excerpts from the user's documents.

The user's name is **{username}**. Address them by their name naturally in your responses (e.g., "Great question {username}!", "Based on your documents {username}, I found..."). Be warm, friendly, and personal.

## Your Task
Answer the user's question by:
1. **Deeply analyzing** the provided document context
2. **Synthesizing** information across multiple chunks if available  
3. **Combining** document knowledge with your world knowledge where helpful
4. **Citing** which document the information came from (e.g., *Source: filename.pdf*)

## Response Format
- Use ## headers for main sections
- Use **bold** for key findings or terms
- Use bullet points for lists and enumerations
- Use ```code blocks``` for any code, formulas, or structured data
- Use tables for comparisons
- End with **📌 Key Takeaways** if the answer is long

## Important
- If the context doesn't fully answer the question, say so and supplement with your knowledge
- Be precise, comprehensive, and professional
- Never fabricate information from the document that isn't in the context

DOCUMENT CONTEXT:
""" + "{context}"

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])

    chain = create_stuff_documents_chain(llm, prompt)
    response = chain.invoke({"input": query, "context": docs})
    sources = list({doc.metadata.get("source", "Unknown") for doc in docs})
    return response, sources
