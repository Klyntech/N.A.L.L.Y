# WSGI entry point for Nally (FastAPI + Uvicorn)
# For production: uvicorn nally.web.app:app --host 0.0.0.0 --port 5000

from nally.web.app import app

__all__ = ["app"]
