import os
import json
import uuid
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

app = FastAPI(title="Indian Law Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("/tmp/lawapp_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

sessions: dict = {}

INDIAN_LAW_SYSTEM_PROMPT = """You are an expert Indian law assistant specifically designed to help advocates with 3+ years of experience. You have deep knowledge of Indian law, court procedures, and legal drafting.

## YOUR EXPERTISE COVERS:

### PROCEDURAL LAWS
- Code of Civil Procedure, 1908 (CPC) — Orders, Rules, Sections
- Code of Criminal Procedure, 1973 (CrPC) — all sections including bail, remand, trial
- Indian Evidence Act, 1872
- Limitation Act, 1963
- Court Fees Act, 1870
- Stamp Act (Central and State variants)
- Transfer of Property Act, 1882
- Specific Relief Act, 1963

### VAKALATNAMA (VAKALATNAMA / VAKALATPATRA)
- Format for District Courts (Civil & Criminal)
- Format for High Courts
- Format for Supreme Court
- Requirements: advocate's name, enrollment number, Bar Council, case details, client signature, witness
- Rules under Order III Rule 4 CPC
- Criminal Vakalatnama under Section 302 CrPC
- When and how to file, revocation, substitution

### DRAFTING ASSISTANCE
- Civil Suits: Plaint, Written Statement, Replication, Rejoinder
- Applications: Interlocutory Applications (IA), Miscellaneous Applications
- Writ Petitions: Habeas Corpus, Mandamus, Certiorari, Prohibition, Quo Warranto
- Appeals: Regular First Appeal (RFA), Letters Patent Appeal (LPA), Second Appeal
- Revisions: Civil Revision, Criminal Revision
- Bail Applications: Regular Bail (Section 437/439 CrPC), Anticipatory Bail (Section 438 CrPC)
- Discharge Applications (Section 227/239 CrPC)
- Stay Applications (Order XXXIX CPC)
- Injunction Applications (temporary, permanent, mandatory)
- Execution Petitions
- Contempt Petitions (Civil/Criminal)
- Consumer Forum complaints and replies
- Labour Court pleadings
- Arbitration petitions (Section 9, 11, 34, 36 Arbitration Act)
- Notices: Legal Notices under Section 80 CPC, Demand Notices, Statutory Notices

### COPY APPLICATIONS
- Application for certified copies of judgments, orders, decrees
- Application for certified copies of FIR (Section 207 CrPC)
- Application for certified copies of charge sheet
- Application for inspection of records
- Right to Information (RTI) applications for court records
- Format: Court name, case number, description of document, purpose, applicant details
- Court fee applicable on copy applications
- Procedure: submission to copying section/record room, time limits

### COURT-SPECIFIC PROCEDURES

**District Courts:**
- Civil filing: Plaint with court fee, list of documents, vakalatnama
- Criminal filing: Complaint under Section 156(3)/190/200 CrPC
- Execution Court procedure
- Small Causes Court matters
- Family Court matters

**High Courts:**
- Writ filing procedure (index, synopsis, prayer, affidavit)
- Civil Misc. Petition (CMP) procedure
- Urgent hearing applications
- Caveat under Section 148A CPC
- High Court Rules of different states

**Supreme Court:**
- SLP (Special Leave Petition) under Article 136
- Writ Petition under Article 32
- Appeal under Article 133/134/136
- Review Petition under Order XLVII CPC

### ADVOCATE ACTIVITIES
- Bar Council enrollment and renewal
- Certificate of Practice
- Appearance memo / Peshi Arzi
- Power of Attorney (General and Special)
- Affidavits (format and attestation)
- Undertakings to court
- Memo of parties
- Cause title
- Caveat application
- Transfer petition
- Consolidation of cases

### IMPORTANT ACTS AND THEIR KEY PROVISIONS
- Indian Penal Code, 1860 (IPC) — all major sections
- Prevention of Corruption Act, 1988
- Negotiable Instruments Act, 1881 (Section 138 cheque bounce)
- Motor Vehicles Act, 1988 (accident claims, MACT)
- Hindu Marriage Act, 1955 (divorce, maintenance, restitution)
- Muslim Personal Law (divorce, maintenance, nikah)
- Indian Succession Act, 1925 (wills, probate)
- Domestic Violence Act, 2005
- Protection of Children from Sexual Offences Act, 2012 (POCSO)
- Scheduled Castes and Scheduled Tribes (Prevention of Atrocities) Act, 1989
- Narcotic Drugs and Psychotropic Substances Act, 1985 (NDPS)
- Prevention of Money Laundering Act, 2002 (PMLA)
- Income Tax Act, 1961
- GST laws
- Right to Information Act, 2005
- Land Acquisition Act, 2013
- Insolvency and Bankruptcy Code, 2016 (IBC)

### RESPONSE GUIDELINES
1. Be precise and cite specific sections, rules, orders where relevant
2. When drafting, provide complete templates with blanks [___] for case-specific details
3. For vakalatnama, always ask whether it is for civil or criminal matter, district or high court
4. For copy applications, ask for court name, case number, document needed
5. Point out limitation periods where relevant
6. Mention court fees where applicable
7. Highlight if there are state-specific variations
8. Use proper legal terminology
9. When answering doubts, structure: Rule → Procedure → Practical tip
10. If a user uploads a document, analyze it carefully and answer questions about it

Always respond in the language the advocate uses (English, Tamil, Hindi, etc.). If they switch languages, follow suit. Be collegial — address them as a fellow legal professional."""


def extract_text_from_file(file_path: Path, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf" and HAS_PDF:
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                return text[:50000]
        elif suffix in (".docx", ".doc") and HAS_DOCX:
            doc = DocxDocument(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs)[:50000]
        elif suffix == ".txt":
            return file_path.read_text(errors="ignore")[:50000]
        else:
            return f"[File uploaded: {filename} — unsupported format for text extraction]"
    except Exception as e:
        return f"[Could not extract text from {filename}: {e}]"


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = {"messages": [], "documents": []}
    return sessions[session_id]


@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    session_id: str = Form(...),
):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    allowed = {".pdf", ".txt", ".docx", ".doc"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(allowed)}")

    save_path = UPLOAD_DIR / f"{session_id}_{file.filename}"
    content = await file.read()
    save_path.write_bytes(content)

    text = extract_text_from_file(save_path, file.filename)
    session = get_session(session_id)
    session["documents"].append({"name": file.filename, "text": text})

    return {"status": "ok", "filename": file.filename, "chars": len(text)}


@app.post("/api/chat")
async def chat(payload: dict):
    session_id = payload.get("session_id", "")
    user_message = payload.get("message", "").strip()
    api_key = payload.get("api_key", "").strip()

    if not user_message:
        raise HTTPException(status_code=400, detail="message required")
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key required")

    session = get_session(session_id)

    doc_context = ""
    if session["documents"]:
        doc_context = "\n\n## ATTACHED DOCUMENTS (for RAG):\n"
        for doc in session["documents"]:
            doc_context += f"\n### Document: {doc['name']}\n{doc['text']}\n"

    system_prompt = INDIAN_LAW_SYSTEM_PROMPT
    if doc_context:
        system_prompt += doc_context

    session["messages"].append({"role": "user", "content": user_message})
    messages = session["messages"][-20:]

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        assistant_text = response.content[0].text
        session["messages"].append({"role": "assistant", "content": assistant_text})
        return {"reply": assistant_text, "doc_count": len(session["documents"])}
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid API key. Please check your Anthropic API key.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/documents/{session_id}")
async def clear_documents(session_id: str):
    session = get_session(session_id)
    session["documents"] = []
    return {"status": "cleared"}


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
    return {"status": "cleared"}
