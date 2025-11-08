# seed_db.py

import random
from faker import Faker
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import logging
import re 

from app.models import Base, Claim, ClaimStatus, PolicyType
from app.database import engine, SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

fake = Faker()


def create_random_claim(customer_id, customer_name, policy_id, customer_phone):
    """Generates a single random insurance claim."""

    policy_type = random.choice(list(PolicyType))
    status = random.choice(list(ClaimStatus))
    incident_date = fake.date_time_between(start_date="-2y", end_date="now")
    date_reported = incident_date + timedelta(days=random.randint(0, 5))

    estimated_damage = round(random.uniform(250.0, 25000.0), 2)
    approved_amount = None
    if status in [ClaimStatus.APPROVED, ClaimStatus.PAID, ClaimStatus.CLOSED]:
        approved_amount = round(estimated_damage * random.uniform(0.75, 1.0), 2)
    
    agent_notes = ""
    if status == ClaimStatus.UNDER_REVIEW:
        agent_notes = f"Adjuster {fake.name()} scheduled for visit."
    elif status == ClaimStatus.APPROVED:
        agent_notes = "Approved after reviewing all documents and photos."
    elif status == ClaimStatus.PAID:
        agent_notes = f"Payment sent on {fake.date_this_year()}."
    elif status == ClaimStatus.DENIED:
        agent_notes = "Claim denied due to policy exclusion."


    # Incident types based on policy type
    incident_type_map = {
        PolicyType.AUTO: ["Auto Accident", "Vandalism", "Theft", "Hail Damage"],
        PolicyType.HOME: ["Water Damage", "Fire", "Burglary"],
        PolicyType.MEDICAL: ["ER Visit", "Scheduled Surgery"],
        PolicyType.THEFT: ["Vehicle Break-in", "Home Burglary"]
    }
    
    incident_type = random.choice(incident_type_map[policy_type])
    description = f"{incident_type} involving {fake.bs()}. {fake.paragraph(nb_sentences=2)}"

    return Claim(
        policy_id=policy_id,
        customer_id=customer_id,
        customer_name=customer_name,
        date_reported=date_reported,
        incident_date=incident_date,
        incident_type=incident_type,
        policy_type=policy_type,
        description=description,
        location=fake.address().replace("\n", ", "),
        status=status,
        estimated_damage=estimated_damage,
        approved_amount=approved_amount,
        assigned_adjuster=fake.name() if random.choice([True, False]) else None,
        agent_notes=agent_notes,
        customer_phone=customer_phone,
    )


def seed_database(num_entries=100):
    """Seeds the database with a specified number of claims."""
    db = SessionLocal()
    try:
        logger.info("Starting to seed the database...")
        num_deleted = db.query(Claim).delete()
        if num_deleted > 0:
            logger.info(f"Deleted {num_deleted} existing claims.")

        # ИЗМЕНЕНИЕ: Добавляем номера телефонов для каждого клиента.
        # Используем чистый формат E.164, который Telnyx присылает по умолчанию.
        customers = [
            {"id": 101, "name": "John Smith", "policy_id_prefix": "POL", "phone": "+15550101"},
            {"id": 102, "name": "Maria Garcia", "policy_id_prefix": "POL", "phone": "+15550102"},
            {"id": 103, "name": "David Chen", "policy_id_prefix": "HPC", "phone": "+15550103"},
            {"id": 104, "name": "Sarah Johnson", "policy_id_prefix": "AUT", "phone": "+15550104"},
            {"id": 105, "name": "James Wilson", "policy_id_prefix": "BUS", "phone": "+15550105"},
            # Добавим одного клиента с двумя полисами, но одним номером
            {"id": 106, "name": "Emily White", "policy_id_prefix": "AUT", "phone": "+15550106"},
            {"id": 107, "name": "Emily White", "policy_id_prefix": "HPC", "phone": "+15550106"},
        ]

        claims_to_add = []
        for i in range(num_entries):
            customer = random.choice(customers)
            policy_id = f"{customer['policy_id_prefix']}-{random.randint(1000, 9999)}"
            
            # ИЗМЕНЕНИЕ: Передаем номер телефона в функцию создания
            new_claim = create_random_claim(
                customer_id=customer["id"],
                customer_name=customer["name"],
                policy_id=policy_id,
                customer_phone=customer["phone"]
            )
            claims_to_add.append(new_claim)

        db.bulk_save_objects(claims_to_add)
        db.commit()
        logger.info(f"Successfully added {len(claims_to_add)} new claims to the database.")

    except Exception as e:
        logger.error(f"An error occurred during seeding: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database(num_entries=120)