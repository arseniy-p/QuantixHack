# app/models.py
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Float,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.sql import func
import enum
from .database import Base
from datetime import datetime


class CallStatus(str, enum.Enum):
    INITIATED = "initiated"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class CallDirection(str, enum.Enum):
    INBOUND = "incoming"
    OUTBOUND = "outbound"


class RecordingStatus(str, enum.Enum):
    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"


class Call(Base):
    __tablename__ = "calls"

    id = Column(Integer, primary_key=True, index=True)
    call_control_id = Column(String, unique=True, index=True, nullable=False)
    call_sid = Column(String, unique=True, index=True)

    status = Column(SQLAlchemyEnum(CallStatus), default=CallStatus.INITIATED)
    direction = Column(SQLAlchemyEnum(CallDirection), nullable=False)

    from_number = Column(String)
    to_number = Column(String)

    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)

    recording_status = Column(
        SQLAlchemyEnum(RecordingStatus), default=RecordingStatus.PENDING
    )
    recording_url = Column(String, nullable=True)  # URL в нашем MinIO

    transcripts = relationship("Transcript", back_populates="call")


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(Integer, ForeignKey("calls.id"), nullable=False)
    speaker = Column(String)  # "user" or "bot"
    text = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    call = relationship("Call", back_populates="transcripts")


class ClaimStatus(enum.Enum):
    SUBMITTED = "Submitted"
    UNDER_REVIEW = "Under Review"
    APPROVED = "Approved"
    PAID = "Paid"
    DENIED = "Denied"
    CLOSED = "Closed"


class PolicyType(enum.Enum):
    AUTO = "Auto"
    HOME = "Homeowners"
    MEDICAL = "Medical"
    THEFT = "Theft"


class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(String, index=True, nullable=False)
    customer_id = Column(Integer, index=True)
    customer_name = Column(String)
    date_reported = Column(DateTime, default=datetime.utcnow)
    incident_date = Column(DateTime, nullable=False)
    incident_type = Column(String, index=True)
    policy_type = Column(SQLAlchemyEnum(PolicyType), nullable=False)
    description = Column(String)
    location = Column(String)
    status = Column(
        SQLAlchemyEnum(ClaimStatus), default=ClaimStatus.SUBMITTED, nullable=False
    )
    estimated_damage = Column(Float)
    approved_amount = Column(Float, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    assigned_adjuster = Column(String, nullable=True)
    agent_notes = Column(String, nullable=True)
    
    search_vector = Column(TSVECTOR, nullable=True)


    def __repr__(self):
        return f"<Claim(policy_id='{self.policy_id}', status='{self.status}')>"
