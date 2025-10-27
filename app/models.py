from sqlalchemy import Column, Integer, String, ForeignKey, Float, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    image_id = Column(Integer, ForeignKey("images.id"), primary_key=True)
    acne = Column(Float, nullable=True)
    hemo = Column(Float, nullable=True)
    mela = Column(Float, nullable=True)
    pore = Column(Float, nullable=True)
    wrinkle = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())