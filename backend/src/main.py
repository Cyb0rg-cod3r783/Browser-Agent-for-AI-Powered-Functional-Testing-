from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database.connection import create_all_tables
from .database.vector_db import vector_db_client
from .api import workflows

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_all_tables()
    try:
        vector_db_client.create_collections()
    except Exception as e:
        print(f"Warning: Could not connect to Qdrant vector DB: {e}. Continuing without it.")
    yield
    # Shutdown (nothing to do for now)

app = FastAPI(lifespan=lifespan)

# Set up CORS middleware to allow requests from our frontend
origins = [
    "http://localhost:3000", # The default port for React's development server
    "chrome-extension://omngiinkbfmmnjdeljbohnjnihjlipgp"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows.router, prefix="/api/v1", tags=["Workflows"])

@app.get("/")
def read_root():
    return {"Hello": "World"}