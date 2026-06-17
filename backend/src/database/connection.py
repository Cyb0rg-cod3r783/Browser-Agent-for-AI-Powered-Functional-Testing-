from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..core.config import settings

# Create the SQLAlchemy engine using the database URL from settings
engine = create_engine(
    settings.DATABASE_URL,
    # The pool_pre_ping argument ensures that the database connection is
    # still alive before it's used by the application.
    pool_pre_ping=True 
)

# Create a session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """FastAPI dependency to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_all_tables():
    """
    A function to create all the database tables defined in the models.
    This is typically run once at application startup.
    """
    from .models import Base
    # The Base.metadata.create_all() function uses the engine to create
    # all of the tables stored in the metadata.
    Base.metadata.create_all(bind=engine)