import fitz  # PyMuPDF
import re

class ResumeRegex:
    # Pattern for Phone: Supports +91, (xxx), or simple 10 digits
    PHONE = r'\(?\+?[\d\s-]{10,15}\)?'
    # Pattern for Email
    EMAIL = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    # Pattern for LinkedIn/GitHub URLs
    URLS = r'(https?://(?:www\.)?(?:linkedin\.com|github\.com)/[a-zA-Z0-9\-_/]+)'

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text("text") + "\n"
    return full_text

def improved_parse(text):
    # Find all matches using our regex patterns
    emails = re.findall(ResumeRegex.EMAIL, text)
    phones = re.findall(ResumeRegex.PHONE, text)
    links = re.findall(ResumeRegex.URLS, text)
    
    # Split text into lines to find the name (usually top of resume)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    data = {
        "name": lines[0] if lines else "Not Found",
        "email": emails[0] if emails else "Not Found",
        "phone": phones[0] if phones else "Not Found",
        "links": list(set(links)), # Remove duplicates
        "raw_content": text
    }
    
    return data