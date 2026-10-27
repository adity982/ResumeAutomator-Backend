"""Warm the configured model before opening the API port."""
import os

from .config import settings
from .services.embeddings import embed

if __name__ == "__main__":
    settings.validate()
    embed(["API startup warm-up"])
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
