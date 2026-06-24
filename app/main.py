from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()


app = FastAPI(title="AI Kubernetes Troubleshooter", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routes import router as api_router  # noqa: E402

app.include_router(api_router)

web_dir = Path(__file__).parent / "web"
app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
