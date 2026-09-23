"""Database setup for StockFlow Mini."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://stockflow:stockflow@db:5432/stockflow")

engine = create_engine(DATABASE_URL, future=True, echo=False)

# Session factory
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# Base class for models
class Base(DeclarativeBase):
    pass

# Create tables if not exist (for simplicity in tests)
Base.metadata.create_all(bind=engine)
