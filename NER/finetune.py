# filename: fine_tune_insurance_ner_refined.py
# --------------------------------
# Fine-tune spaCy NER on insurance claims data.
# Automatically removes overlapping entities to prevent [E103] errors.
# Refined to handle multiple entities of the same type.

import json
import random
import pandas as pd
import spacy
from spacy.training import Example
from spacy.util import minibatch, compounding


# ------------------------------------------------------------
# 1️⃣ Load and clean training data (No changes needed here)
# ------------------------------------------------------------
def load_training_data(filepath):
    """Load JSONL file into spaCy-style training tuples"""
    data = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line.strip())
            text = item["text"]
            entities = [(start, end, label) for start, end, label in item["entities"]]
            data.append((text, {"entities": entities}))
    return data


def clean_overlapping_entities(data):
    """Remove overlapping entities from training data to prevent ValueError [E103]"""
    cleaned = []
    for text, ann in data:
        ents = sorted(ann["entities"], key=lambda x: (x[0], x[1]))
        non_overlapping = []
        prev_end = -1
        for start, end, label in ents:
            if start < prev_end:
                # This is a valuable warning to see if your annotation has issues
                print(f"⚠️ Overlap found in text: '{text[start:end]}' — skipping duplicate entity")
                continue
            non_overlapping.append((start, end, label))
            prev_end = end
        cleaned.append((text, {"entities": non_overlapping}))
    return cleaned


# ------------------------------------------------------------
# 2️⃣ Fine-tune pretrained spaCy model (No changes needed here)
# ------------------------------------------------------------
def fine_tune_ner_model(train_data, base_model="en_core_web_lg", n_iter=20, output_dir="insurance_ner_finetuned"):
    """Fine-tune a pretrained spaCy model on insurance data"""
    print(f"🔹 Loading pretrained model '{base_model}' ...")
    # Using a larger model for better accuracy
    nlp = spacy.load(base_model)

    # Add or get NER pipeline
    if "ner" not in nlp.pipe_names:
        ner = nlp.add_pipe("ner", last=True)
    else:
        ner = nlp.get_pipe("ner")

    # Add entity labels from training data
    for _, annotations in train_data:
        for ent in annotations.get("entities"):
            ner.add_label(ent[2])

    # Train only NER, disabling other pipes
    other_pipes = [p for p in nlp.pipe_names if p != "ner"]
    with nlp.disable_pipes(*other_pipes):
        optimizer = nlp.resume_training()
        print("🔹 Starting fine-tuning...")
        for epoch in range(n_iter):
            random.shuffle(train_data)
            losses = {}
            batches = minibatch(train_data, size=compounding(4.0, 32.0, 1.5))
            for batch in batches:
                examples = [Example.from_dict(nlp.make_doc(text), ann) for text, ann in batch]
                nlp.update(examples, drop=0.3, losses=losses)
            print(f"Epoch {epoch+1}/{n_iter} - Losses: {losses}")

    nlp.to_disk(output_dir)
    print(f"\n✅ Fine-tuned model saved to: {output_dir}")
    return nlp


# ------------------------------------------------------------
# 3️⃣ Query claims database (MODIFIED FOR ROBUSTNESS)
# ------------------------------------------------------------
def find_claim_info(user_query, nlp_model, db):
    """Extract entities and query the database"""
    doc = nlp_model(user_query)
    
    # --- MODIFICATION START ---
    # Store entities in a dictionary where values are lists
    # This correctly handles multiple entities of the same type
    from collections import defaultdict
    ents = defaultdict(list)
    for ent in doc.ents:
        ents[ent.label_].append(ent.text)
    # --- MODIFICATION END ---

    print("\n🔍 Extracted entities:")
    if not doc.ents:
        print("  No entities found.")
    else:
        for label, texts in ents.items():
            print(f"  {label:<15}: {', '.join(texts)}")

    result = db.copy()

    # Query based on the first found entity for each type (can be extended)
    if "CUSTOMER" in ents:
        result = result[result["Customer Name"].str.contains(ents["CUSTOMER"][0], case=False, na=False)]
    if "POLICY_ID" in ents:
        result = result[result["Policy ID"].str.contains(ents["POLICY_ID"][0], case=False, na=False)]
    if "INCIDENT_TYPE" in ents:
        result = result[result["Incident Type"].str.contains(ents["INCIDENT_TYPE"][0], case=False, na=False)]
    if "DATE" in ents: # Assuming the label might just be DATE
        # This simple logic just checks if the date string is anywhere in the column
        result = result[result["Date Reported"].str.contains(ents["DATE"][0], case=False, na=False)]

    if len(result) == 0:
        return "No matching claim found."
    elif len(result) > 1:
        return "Multiple claims match your request. Please specify a date or policy number."
    else:
        row = result.iloc[0]
        return (
            f"Claim {row['Policy ID']} for {row['Customer Name']} "
            f"({row['Incident Type']}) is currently {row['Status']} "
            f"with estimated damages of ${row['Estimated Damage']}."
        )


# ------------------------------------------------------------
# 4️⃣ Main — train + test + query
# ------------------------------------------------------------
if __name__ == "__main__":
    TRAIN_PATH = "spacy_ner_claims.jsonl"  # Your training data file
    CLAIMS_CSV = "dbsample.csv"         # Your claim database CSV
    OUTPUT_DIR = "insurance_ner_finetuned"
    
    # NOTE: You need to create the training file 'spacy_ner_claims.jsonl'
    # and the database 'dbsample.csv' for this to run.

    # 1. Load and clean data
    # train_data = load_training_data(TRAIN_PATH)
    # train_data = clean_overlapping_entities(train_data)

    # 2. Fine-tune the model
    # nlp = fine_tune_ner_model(train_data, base_model="en_core_web_lg", n_iter=10, output_dir=OUTPUT_DIR)
    
    # 3. Or, if already trained, just load it from disk
    print(f"🔹 Loading fine-tuned model from: {OUTPUT_DIR}")
    nlp = spacy.load(OUTPUT_DIR)

    # 4. Load claims database
    claims_df = pd.read_csv(CLAIMS_CSV)

    # 5. Example test
    test_query = "Can you tell me the status of Robert Taylor's fire claim from October 30?"
    response = find_claim_info(test_query, nlp, claims_df)

    print("\nUser:", test_query)
    print("Assistant:", response)