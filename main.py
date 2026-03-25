from fastapi import FastAPI, UploadFile, File, HTTPException, Body, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse  # <--- NEW: For Real-Time Text
from fpdf import FPDF
import shutil
import os
import re
import time  # <--- For Cache
from sqlalchemy.orm import Session
from fastapi import Depends
from database import get_db, User, SavedResume
import urllib.parse # <--- NEW: For building live search URLs

# Import your custom logic (Now using the streaming functions, career discovery, & cold email!)
from parser import extract_text_from_pdf, improved_parse
from scraper import scrape_job_description
from ai_engine import analyze_match, stream_rewrite_resume, stream_cover_letter, stream_mock_interview, recommend_job_profiles, stream_cold_email

app = FastAPI(title="Resume Automator - Final BTech Version")

# --- STEP 1: CORS Setup ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- SERVER-SIDE CACHE ---
SCRAPE_CACHE = {}
CACHE_TTL = 600  # 10 minutes

# --- HELPER: 5-Theme PDF Generator (UPDATED for Cover Letters) ---
def create_pdf_bytes(text_input, template="standard", header_title="TAILORED RESUME"):
    """A bulletproof PDF generator with 5 professional theme supports."""
    pdf = FPDF()
    pdf.add_page()
    
    # 1. Clean the text
    safe_text = str(text_input)
    safe_text = re.sub(r'[^\x20-\x7E\n\r\t]', '', safe_text)
    
    if not safe_text.strip():
        safe_text = "Error: No valid text could be processed for the PDF."

    # 2. Apply Theme Styles dynamically
    if template == "modern":
        font_family, base_size, line_height = "helvetica", 11, 6
        text_color, header_color = (40, 44, 52), (0, 102, 204) # Charcoal text, Blue header
        align_header = "L"
    elif template == "executive":
        font_family, base_size, line_height = "times", 11, 5.5
        text_color, header_color = (20, 20, 20), (0, 0, 128) # Near-black text, Navy header
        align_header = "C"
    elif template == "minimalist":
        font_family, base_size, line_height = "helvetica", 10, 7
        text_color, header_color = (70, 70, 70), (40, 44, 52) # Soft grey text, Dark grey header
        align_header = "L"
    elif template == "creative":
        font_family, base_size, line_height = "courier", 11, 6
        text_color, header_color = (0, 0, 0), (0, 150, 136) # Black text, Teal header
        align_header = "L"
    else: 
        # standard
        font_family, base_size, line_height = "times", 11, 5.5
        text_color, header_color = (0, 0, 0), (0, 0, 0) # Pure black
        align_header = "L"

    # Add a stylized visual header based on the theme and document type
    pdf.set_font(font_family, style="B", size=14)
    pdf.set_text_color(*header_color)
    pdf.cell(0, 12, header_title, ln=True, align=align_header)

    # Set the body text styling
    pdf.set_font(font_family, size=base_size)
    pdf.set_text_color(*text_color)

    # 3. Write to PDF
    pdf.multi_cell(0, line_height, safe_text)
    
    return bytes(pdf.output())

# --- ENDPOINT 1: Resume Upload ---
@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        raw_text = extract_text_from_pdf(file_path)
        structured_data = improved_parse(raw_text)
        
        return {"status": "success", "extracted_data": structured_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 2: Job Scraper (WITH CACHING) ---
@app.post("/scrape_job")
async def get_job_details(url: str):
    current_time = time.time()
    
    # 1. Check Cache
    if url in SCRAPE_CACHE:
        cached_data = SCRAPE_CACHE[url]
        if current_time - cached_data['timestamp'] < CACHE_TTL:
            print("⚡ CACHE HIT! Returning saved job description instantly.")
            return {"status": "success", "job_data": cached_data['data'], "cached": True}
        else:
            print("🗑️ CACHE EXPIRED! Scraping fresh data.")

    # 2. Scrape Normal Way
    print("🌐 CACHE MISS! Scraping website for the first time...")
    job_details = await scrape_job_description(url)
    
    if "error" in job_details:
        return {"status": "error", "details": job_details["error"]}
        
    # 3. Save to Cache
    SCRAPE_CACHE[url] = {
        'timestamp': current_time,
        'data': job_details
    }
    
    return {"status": "success", "job_data": job_details, "cached": False}

# --- ENDPOINT 3: AI Analysis (Blocking JSON) ---
@app.post("/analyze_match")
async def analyze(payload: dict = Body(...)):
    try:
        resume_text = payload.get("resume_text")
        jd_text = payload.get("jd_text")
        analysis_results = analyze_match(resume_text, jd_text)
        return {"status": "success", "analysis": analysis_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 4: STREAMING Resume Tailoring ---
@app.post("/tailor_resume")
async def tailor(payload: dict = Body(...)):
    try:
        resume_text = payload.get("resume_text")
        jd_text = payload.get("jd_text")
        # Return the stream directly to the client!
        return StreamingResponse(stream_rewrite_resume(resume_text, jd_text), media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 5: Download PDF (UPDATED to handle Cover Letters) ---
@app.post("/download_resume")
async def download_resume(payload: dict = Body(...)):
    tailored_text = payload.get("text", "")
    template_choice = payload.get("template", "standard") 
    doc_type = payload.get("doc_type", "Resume") # NEW: Tells backend what we are printing
    
    if not tailored_text:
        raise HTTPException(status_code=400, detail="No text content found.")
    try:
        # Dynamically set the title based on the doc_type
        header_title = "TAILORED RESUME" if doc_type == "Resume" else "COVER LETTER"
        
        pdf_bytes = create_pdf_bytes(tailored_text, template=template_choice, header_title=header_title)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={doc_type.replace(' ', '_')}_{template_choice.capitalize()}.pdf",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except Exception as e:
        print(f"CRITICAL PDF ERROR: {e}") 
        raise HTTPException(status_code=500, detail="PDF generation failed.")

# --- ENDPOINT 6: STREAMING Cover Letter Generator ---
@app.post("/generate_cover_letter")
async def generate_letter(payload: dict = Body(...)):
    try:
        resume_text = payload.get("resume_text")
        jd_text = payload.get("jd_text")
        return StreamingResponse(stream_cover_letter(resume_text, jd_text), media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 7: Save Resume to Database ---
@app.post("/save_resume_history")
async def save_history(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        user_uid = payload.get("uid")
        email = payload.get("email")
        
        user = db.query(User).filter(User.uid == user_uid).first()
        if not user:
            user = User(uid=user_uid, email=email)
            db.add(user)
            db.commit()

        new_resume = SavedResume(
            user_uid=user_uid,
            job_url=payload.get("job_url", "Unknown Job"),
            match_score=payload.get("match_score", 0),
            tailored_text=payload.get("tailored_text", "")
        )
        db.add(new_resume)
        db.commit()
        
        return {"status": "success", "message": "Resume saved to database!"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 8: Get User's Saved Resumes ---
@app.get("/get_my_resumes/{user_uid}")
async def get_my_resumes(user_uid: str, db: Session = Depends(get_db)):
    try:
        resumes = db.query(SavedResume).filter(SavedResume.user_uid == user_uid).order_by(SavedResume.created_at.desc()).all()
        return {"status": "success", "history": resumes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 9: STREAMING Mock Interviewer ---
@app.post("/generate_interview")
async def generate_interview(payload: dict = Body(...)):
    try:
        resume_text = payload.get("resume_text")
        jd_text = payload.get("jd_text")
        return StreamingResponse(stream_mock_interview(resume_text, jd_text), media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 10: Career Discovery Engine ---
@app.post("/discover_jobs")
async def discover_jobs(payload: dict = Body(...)):
    try:
        resume_text = payload.get("resume_text")
        if not resume_text:
            raise HTTPException(status_code=400, detail="Resume text is required.")
            
        # 1. Get titles from AI
        ai_response = recommend_job_profiles(resume_text)
        
        # 2. Programmatically build guaranteed-live search URLs
        enriched_profiles = []
        for profile in ai_response.get("profiles", []):
            title = profile.get("title", "")
            url_encoded_title = urllib.parse.quote(title)
            
            profile["links"] = {
                "LinkedIn": f"https://www.linkedin.com/jobs/search/?keywords={url_encoded_title}",
                "WeWorkRemotely": f"https://weworkremotely.com/remote-jobs/search?term={url_encoded_title}",
                "Indeed": f"https://www.indeed.com/jobs?q={url_encoded_title}"
            }
            enriched_profiles.append(profile)
            
        return {"status": "success", "recommendations": enriched_profiles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT 11: STREAMING Cold Email Generator ---
@app.post("/generate_cold_email")
async def generate_cold_email(payload: dict = Body(...)):
    try:
        resume_text = payload.get("resume_text")
        jd_text = payload.get("jd_text")
        return StreamingResponse(stream_cold_email(resume_text, jd_text), media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print("🚀 Final Backend Server running at http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)