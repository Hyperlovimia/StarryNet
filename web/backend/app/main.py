import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router


app = FastAPI(title="StarryNet Control Plane", version="0.1.0")
cors_origin_regex = os.getenv("STARRYNET_CORS_ALLOW_ORIGIN_REGEX", ".*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
