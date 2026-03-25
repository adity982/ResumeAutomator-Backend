import asyncio
import random
from playwright.async_api import async_playwright

# A list of real human browsers to trick the anti-bot systems
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0"
]

async def scrape_job_description(url):
    async with async_playwright() as p:
        # Launch browser in stealth mode
        browser = await p.chromium.launch(headless=True)
        
        try:
            # Create a context with human-like properties
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={'width': 1920, 'height': 1080},
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1"
                }
            )
            
            page = await context.new_page()
            
            # Navigate to the URL
            response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Graceful Fallback: Check if we got blocked by an anti-bot system (Status 403 or 429)
            if response and response.status in [403, 429]:
                return {"error": f"Anti-Bot Captcha detected (Status {response.status}). Please try a different link or paste the text manually."}

            # Wait a random human-like amount of time (1.5 to 3.5 seconds)
            await page.wait_for_timeout(random.randint(1500, 3500))
            
            # Extract the data exactly as your UI expects it
            title = await page.title()
            description = await page.inner_text("body") 
            
            # If the text is suspiciously short, we might have hit a hidden captcha
            if len(description.strip()) < 100:
                return {"error": "Page loaded, but no job description text was found. The site might be blocking text extraction."}
                
            return {
                "title": title,
                "company": "Extracted from Page",
                "description": description[:5000] # Limit to 5000 characters to save AI tokens
            }
            
        except Exception as e:
            return {"error": f"Scraper Error: {str(e)}"}
            
        finally:
            # Always close the browser to prevent memory leaks
            await browser.close()