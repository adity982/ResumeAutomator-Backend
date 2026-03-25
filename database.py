from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime

# Create a local SQLite database file named "resume_app.db"
SQLALCHEMY_DATABASE_URL = "sqlite:///./resume_app.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# --- TABLE 1: Users ---
class User(Base):
    __tablename__ = "users"
    
    uid = Column(String, primary_key=True, index=True) # We will store the Google Login ID here
    email = Column(String, unique=True, index=True)
    
    # Link to their resumes
    resumes = relationship("SavedResume", back_populates="owner")

# --- TABLE 2: Saved Resumes ---
class SavedResume(Base):
    __tablename__ = "saved_resumes"
    
    id = Column(Integer, primary_key=True, index=True)
    user_uid = Column(String, ForeignKey("users.uid")) # Links to the User table
    job_url = Column(String)
    match_score = Column(Integer)
    tailored_text = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    owner = relationship("User", back_populates="resumes")

# Create the tables in the database file automatically
Base.metadata.create_all(bind=engine)

# Helper function to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()