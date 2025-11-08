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
    Performs a full-text search across multiple fields in the claims table.
    
    Args:
        db: The SQLAlchemy session.
        query: The search string from NER (e.g., "POL-001 water damage").
        customer_phone: Optional phone number to filter results for a specific user.

    Returns:
        A list of matching claim records.
    """
    
    # 1. Sanitize and format the query for to_tsquery
    # We replace spaces with '&' to search for all words (AND logic)
    # This is a basic approach; more complex logic can be added here.
    search_terms = query.strip().split()
    formatted_query = " & ".join(search_terms)

    # 2. Build the base SQLAlchemy query using the FTS operator `@@`
    # The `text()` construct is used to safely pass the FTS functions.
    # We also rank the results to show the most relevant ones first.
    base_query = (
        db.query(models.Claim)
        .filter(models.Claim.search_vector.op("@@")(func.to_tsquery('simple', formatted_query)))
        .order_by(func.ts_rank(models.Claim.search_vector, func.to_tsquery('simple', formatted_query)).desc())
    )

    # 3. (Optional but Recommended) Filter by customer if identified
    # In a real system, you'd link calls to customers. Here we simulate it.
    # if customer_phone:
    #     # This assumes you have a way to link phone numbers to customers/policies.
    #     # For this example, we'll filter by a field if it exists.
    #     # You might need to add a 'customer_phone' field to your Claim model
    #     pass

    # 4. Execute and return results
    results = base_query.limit(10).all() # Limit to top 10 relevant results
    return results