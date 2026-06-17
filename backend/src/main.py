from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import workflows

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup (DB and Qdrant disabled for temporary JSON-only storage mode)
    # create_all_tables()
    # try:
    #     vector_db_client.create_collections()
    # except Exception as e:
    #     print(f"Warning: Could not connect to Qdrant vector DB: {e}. Continuing without it.")
    yield
    # Shutdown (nothing to do for now)

app = FastAPI(lifespan=lifespan)

# Set up CORS middleware to allow requests from our frontend and browser extensions
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
    return {"Hello": "World"}