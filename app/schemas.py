# app/schemas.py
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

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