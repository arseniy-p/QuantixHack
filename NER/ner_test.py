# filename: standalone_ner_test.py

import spacy
import regex as re

def setup_nlp_rules():
    """
    Loads the spaCy NLP model required for entity and keyword extraction.
    """
    print("Loading NLP model for keyword extraction...")
    try:
        # Using the same large model as the agent for consistency
        nlp = spacy.load("insurance_ner_finetuned")
        print("Model ready.")
        return nlp
    except OSError:
        print("\n---[ Model Not Found ]---")
        print("Error: 'en_core_web_lg' not found. Please run the following command:")
        print("python -m spacy download en_core_web_lg")
        exit()


def formulate_search_query(text: str, nlp) -> str:
    """
    Extracts key entities and nouns to create a concise search string.
    This is the core NER algorithm isolated from the agent.
    """
    # Process the input text with the loaded NLP model
    doc = nlp(text)
    search_terms = []
    
    # 1. Extract named entities (people, dates, organizations, locations, products)
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "DATE", "ORG", "GPE", "PRODUCT"]:
            search_terms.append(ent.text)
            
    # 2. Extract important noun chunks (e.g., "pipe burst", "auto accident")
    # This captures subjects and objects that are not recognized as named entities.
    for chunk in doc.noun_chunks:
        # Add the chunk if its root word is not already part of a named entity
        if chunk.root.ent_type_ == 0: 
             search_terms.append(chunk.text)

    # 3. Use regex to specifically find policy IDs if spaCy misses them
    policy_id_match = re.search(r'POL-\d{3,}', text, re.IGNORECASE)
    if policy_id_match:
        search_terms.append(policy_id_match.group(0))

    # 4. Remove duplicate terms while preserving order and join into a single string
    unique_terms = list(dict.fromkeys(search_terms))
    final_query = " ".join(unique_terms)
    
    # Failsafe: if no specific terms were found, use the original text
    if not final_query.strip():
        return text

    return final_query

def start_ner_test_session():
    """
    Main loop to run the NER extraction test from the console.
    """
    # Load the NLP model once
    nlp = setup_nlp_rules()
    
    print("\n--- NER Keyword Extraction Test ---")
    print("Enter a sentence to see the extracted keywords for the API.")
    print("Type 'quit' or 'exit' to stop.")
    
    while True:
        # Get input from the user
        user_input = input("\n> ")
        if user_input.lower() in ["quit", "exit"]:
            break
            
        if not user_input.strip():
            continue

        # Run the NER algorithm on the input
        extracted_keywords = formulate_search_query(user_input, nlp)
        
        # Print the result
        print(f"  -> Extracted Keywords: '{extracted_keywords}'")


if __name__ == "__main__":
    try:
        start_ner_test_session()
    except KeyboardInterrupt:
        print("\nExiting...")