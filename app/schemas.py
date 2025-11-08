# app/schemas.py
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from .models import ClaimStatus, PolicyType


class TranscriptSchema(BaseModel):
    id: int
    speaker: str
    text: str
    timestamp: datetime

    class Config:
        from_attributes = True


class CallSchema(BaseModel):
    id: int
    call_sid: str
    status: str
    direction: str
    from_number: str
    to_number: str
    start_time: datetime
    end_time: Optional[datetime] = None
    recording_url: Optional[str] = None
    transcripts: List[TranscriptSchema] = []

    class Config:
        from_attributes = True


class ClaimBase(BaseModel):
    policy_id: str
    customer_name: str
    incident_date: datetime
    incident_type: str
    policy_type: PolicyType
    description: str
    location: str
    status: ClaimStatus
    estimated_damage: float
    approved_amount: Optional[float] = None
    assigned_adjuster: Optional[str] = None
    agent_notes: Optional[str] = None


class ClaimCreate(ClaimBase):
    pass


class ClaimSchema(ClaimBase):
    id: int
    customer_id: Optional[int] = None
    date_reported: datetime
    last_updated: datetime

    class Config:
        from_attributes = True

class ClaimSearchQuery(BaseModel):
    text: str
