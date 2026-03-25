import requests
from bs4 import BeautifulSoup
import re

async def scrape_job_description(url: str):
    print(f"Starting lightweight scrape for: {url}")
    try:
        # We disguise our scraper as a normal Chrome browser
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        # Fetch the webpage
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Rip out the garbage (nav bars, footers, javascript, CSS)
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.extract()
            
        # Get the raw text
        text = soup.get_text(separator=' ', strip=True)
        
        # Clean up multiple spaces
        clean_text = re.sub(r'\s+', ' ', text)
        
        if len(clean_text) < 50:
            return {"error": "Website blocked the scraper or has no readable text."}
            
        print("Scrape successful!")
        return {
            "title": soup.title.string if soup.title else "Job Description",
            "description": clean_text[:8000] # Cap it so we don't overwhelm the Groq API
        }
        
    except Exception as e:
        print(f"Scrape Error: {str(e)}")
        return {"error": f"Failed to scrape job: {str(e)}"}