from pydantic import BaseModel
from sqlalchemy import (create_engine, Column, Integer, String,
                        BigInteger, DateTime, func)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=func.now())

class TrafficRecord(Base):
    __tablename__ = "traffic"
    id = Column(Integer, primary_key=True, index=True)
    user_name = Column(String, index=True)
    bytes_recv = Column(BigInteger)
    bytes_sent = Column(BigInteger)
    timestamp = Column(DateTime, default=func.now())

Base.metadata.create_all(bind=engine)

class UserCreate(BaseModel):
    name: str