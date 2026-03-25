import os
import json
import re
import time
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in .env file!")

client = Groq(api_key=GROQ_API_KEY)
MODEL_NAME = "llama-3.1-8b-instant"

# --- 1. Analyze Match (Stays the same because it needs to return strict JSON) ---
def analyze_match(resume_text, jd_text):
    resume_snippet = resume_text[:2000] 
    jd_snippet = jd_text[:2000]

    prompt = f"""
    Compare the following Resume and Job Description. 
    Return ONLY a raw JSON object with no markdown formatting.
    Format required: {{"score": int, "missing_keywords": list, "verdict": str}}
    
    Resume: {resume_snippet}
    JD: {jd_snippet}
    """
    
    for attempt in range(2):
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a precise ATS system. You only output valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                model=MODEL_NAME,
                temperature=0.2, 
            )
            
            response_text = chat_completion.choices[0].message.content
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            break 
            
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                time.sleep(5)
            else:
                return {"score": 0, "missing_keywords": [], "verdict": f"Groq Error: {str(e)}"}

    return {"score": 0, "missing_keywords": ["API Limit"], "verdict": "Rate limit exceeded. Try again later."}

# --- 2. STREAMING: Tailor Resume ---
def stream_rewrite_resume(resume_text, jd_text):
    prompt = f"""
    You are an expert executive resume writer. Rewrite the provided resume to perfectly align with the Job Description.
    CRITICAL RULES:
    1. Maintain standard resume order (Header, Summary, Education, Experience, Projects, Skills).
    2. DO NOT output any XML tags, intro text, or conversational filler. Start writing the resume immediately.
    
    Resume: {resume_text[:2500]} 
    JD: {jd_text[:2500]}
    """
    
    try:
        stream = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a strict resume formatter. Output only the final resume text."},
                {"role": "user", "content": prompt}
            ],
            model=MODEL_NAME,
            temperature=0.2,
            stream=True, # Turn on streaming!
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"\n[Stream Error: {str(e)}]"

# --- 3. STREAMING: Cover Letter ---
def stream_cover_letter(resume_text, jd_text):
    prompt = f"""
    Write a highly tailored, professional cover letter (under 300 words) based on the candidate's resume and target JD.
    CRITICAL RULE: DO NOT output any XML tags or intro text. Start writing the letter immediately.
    
    Resume: {resume_text[:2000]}
    JD: {jd_text[:2000]}
    """
    
    try:
        stream = client.chat.completions.create(
            messages=[{"role": "system", "content": "You are an expert career coach."}, {"role": "user", "content": prompt}],
            model=MODEL_NAME,
            temperature=0.4,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"\n[Stream Error: {str(e)}]"

# --- 4. STREAMING: Mock Interview ---
def stream_mock_interview(resume_text, jd_text):
    prompt = f"""
    You are an elite Senior Director at a FAANG company. Generate 5 grueling, highly specific interview questions based on this resume and JD.
    CRITICAL RULE: DO NOT output any XML tags or intro text. Output the 5 questions directly.
    
    Resume: {resume_text[:2000]}
    JD: {jd_text[:2000]}
    """
    
    try:
        stream = client.chat.completions.create(
            messages=[{"role": "system", "content": "You are a ruthless FAANG interviewer."}, {"role": "user", "content": prompt}],
            model=MODEL_NAME,
            temperature=0.7,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"\n[Stream Error: {str(e)}]"

# --- 5. NEW FEATURE: Career Discovery Engine ---
def recommend_job_profiles(resume_text):
    prompt = f"""
    You are an elite Tech Recruiter. Analyze this resume and recommend the top 3 job titles this candidate should apply for.
    Look for "Bridge" roles if they have mixed experience (e.g., Tech + Business).
    
    CRITICAL RULE: Return ONLY a raw JSON object. No markdown, no intro text.
    Format required:
    {{
      "profiles": [
        {{"title": "Job Title 1", "reason": "1 sentence explaining why their specific skills match this."}},
        {{"title": "Job Title 2", "reason": "1 sentence explaining why their specific skills match this."}},
        {{"title": "Job Title 3", "reason": "1 sentence explaining why their specific skills match this."}}
      ]
    }}
    
    Resume:
    {resume_text[:3000]}
    """
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a precise JSON generator. Output only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            model=MODEL_NAME,
            temperature=0.3,
        )
        
        response_text = chat_completion.choices[0].message.content
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return {"profiles": []}
            
    except Exception as e:
        print(f"AI Recommendation Error: {e}")
        return {"profiles": []}

# --- 6. NEW FEATURE: STREAMING Cold Email ---
def stream_cold_email(resume_text, jd_text):
    prompt = f"""
    You are an expert career strategist. Write a short, punchy, 3-sentence cold email to a Recruiter or Hiring Manager for the provided job description, highlighting the best matching skills from the resume.
    CRITICAL RULES:
    1. Keep it strictly under 100 words.
    2. Make it engaging, confident, and professional.
    3. Include a clear call to action (e.g., asking for a brief 10-minute chat).
    4. DO NOT output any XML tags, subject lines, or conversational filler. Output the email body immediately.
    
    Resume: {resume_text[:2000]}
    JD: {jd_text[:2000]}
    """
    
    try:
        stream = client.chat.completions.create(
            messages=[{"role": "system", "content": "You are a master of concise LinkedIn outreach."}, {"role": "user", "content": prompt}],
            model=MODEL_NAME,
            temperature=0.6,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"\n[Stream Error: {str(e)}]"