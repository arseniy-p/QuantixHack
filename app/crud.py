# app/crud.py

from sqlalchemy.orm import Session
from sqlalchemy import func, text
from typing import List, Optional

from . import models, schemas

# --- Standard CRUD Operations ---

def get_claim_by_id(db: Session, claim_id: int) -> Optional[models.Claim]:
    """
    Get a single claim by its primary key ID.
    """
    return db.query(models.Claim).filter(models.Claim.id == claim_id).first()

def get_all_claims(db: Session, skip: int = 0, limit: int = 100) -> List[models.Claim]:
    """
    Get a paginated list of all claims.
    """
    return db.query(models.Claim).offset(skip).limit(limit).all()

def create_claim(db: Session, claim: schemas.ClaimCreate) -> models.Claim:
    """
    Create a new claim record.
    """
    db_claim = models.Claim(**claim.model_dump())
    db.add(db_claim)
    db.commit()
    db.refresh(db_claim)
    return db_claim

# --- Advanced Search Functionality ---

def search_claims(db: Session, query: str, customer_phone: Optional[str] = None) -> List[models.Claim]:
    """
    Performs a full-text search across multiple fields in the claims table,
    optionally filtering by the customer's phone number.
    
    Args:
        db: The SQLAlchemy session.
        query: The search string from NER (e.g., "POL-001 water damage").
        customer_phone: The phone number of the caller (e.g., '+15550101') to scope the search.

    Returns:
        A list of matching claim records.
    """
    
    search_terms = query.strip().split()
    formatted_query = " & ".join(search_terms)

    base_query = (
        db.query(models.Claim)
        .filter(models.Claim.search_vector.op("@@")(func.to_tsquery('simple', formatted_query)))
    )

    if customer_phone:
        base_query = base_query.filter(models.Claim.customer_phone == customer_phone)

    ordered_query = base_query.order_by(
        func.ts_rank(models.Claim.search_vector, func.to_tsquery('simple', formatted_query)).desc()
    )

    results = ordered_query.limit(10).all()
    return results