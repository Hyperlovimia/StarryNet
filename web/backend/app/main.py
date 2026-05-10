from fastapi import FastAPI

from .api.routes import router


app = FastAPI(title="StarryNet Control Plane", version="0.1.0")
app.include_router(router)
