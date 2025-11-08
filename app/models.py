# app/models.py
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from .database import Base


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
