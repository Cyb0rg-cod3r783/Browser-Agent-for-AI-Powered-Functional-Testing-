from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import workflows


@asynccontextmanager
async def lifespan(app: FastAPI):
    # All data is stored in workflows_db.json — no DB setup needed
    yield


app = FastAPI(
    title="WorkflowBot API",
    description="Browser workflow recorder and AI-powered test automation",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex="chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows.router, prefix="/api/v1", tags=["Workflows"])


@app.get("/")
def read_root():
    return {"status": "ok", "storage": "json", "data_file": "workflows_db.json"}
