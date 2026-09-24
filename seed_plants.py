import os
from google.cloud import firestore

# IMPORTANT: Hardcoded Project ID string as requested
PROJECT_ID = "qwiklabs-gcp-02-2b66acfe63f6"

db = firestore.Client(project=PROJECT_ID)

PLANTS_DATA = [
    {
        "plant_id": "monstera_deliciosa",
        "name": "Monstera Deliciosa",
        "scientific_name": "Monstera deliciosa",
        "care_level": "Easy",
        "light_requirement": "Bright indirect light",
        "watering_frequency_days": 7,
        "humidity_preference": "High",
        "toxicity": "Toxic to cats and dogs",
        "description": "Iconic tropical plant with broad, glossy split leaves (fenestrations). Thrives in warm, humid rooms.",
    },
    {
        "plant_id": "snake_plant",
        "name": "Snake Plant",
        "scientific_name": "Sansevieria trifasciata",
        "care_level": "Beginner",
        "light_requirement": "Low to bright indirect light",
        "watering_frequency_days": 14,
        "humidity_preference": "Average",
        "toxicity": "Toxic to pets if ingested",
        "description": "Extremely resilient architectural succulent with upright sword-like leaves with yellow borders.",
    },
    {
        "plant_id": "pothos_golden",
        "name": "Golden Pothos",
        "scientific_name": "Epipremnum aureum",
        "care_level": "Easy",
        "light_requirement": "Low to bright indirect light",
        "watering_frequency_days": 7,
        "humidity_preference": "Average",
        "toxicity": "Toxic to pets",
        "description": "Vining plant with heart-shaped leaves variegated with marble yellow and green patterns.",
    },
    {
        "plant_id": "fiddle_leaf_fig",
        "name": "Fiddle Leaf Fig",
        "scientific_name": "Ficus lyrata",
        "care_level": "Moderate",
        "light_requirement": "Bright consistent light",
        "watering_frequency_days": 10,
        "humidity_preference": "High",
        "toxicity": "Toxic to pets",
        "description": "Dramatic indoor tree with large violin-shaped leaves that prefers stable locations and steady care.",
    },
    {
        "plant_id": "calathea_rattlesnake",
        "name": "Rattlesnake Plant",
        "scientific_name": "Goeppertia insignis",
        "care_level": "Moderate",
        "light_requirement": "Medium indirect light",
        "watering_frequency_days": 5,
        "humidity_preference": "High",
        "toxicity": "Non-toxic to pets",
        "description": "Striking foliage with dark green spotted leaves and deep purple undersides. Safe for households with pets.",
    },
]

def seed_database():
    collection_ref = db.collection("house_plants")
    print(f"Seeding Firestore collection 'house_plants' in project '{PROJECT_ID}'...")
    for plant in PLANTS_DATA:
        doc_ref = collection_ref.document(plant["plant_id"])
        doc_ref.set(plant)
        print(f"  - Added/Updated plant: {plant['name']} ({plant['plant_id']})")
    print("Database seeding completed successfully!")

if __name__ == "__main__":
    seed_database()
