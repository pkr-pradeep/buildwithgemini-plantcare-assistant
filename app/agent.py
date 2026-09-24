# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
from zoneinfo import ZoneInfo

import os
from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from .a2ui_utils import a2ui_callback


# IMPORTANT: Hardcode project ID as a string for the Firestore client
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-02-2b66acfe63f6"
GCS_BUCKET_NAME = "plantcare-assets-qwiklabs-gcp-02-2b66acfe63f6"

# Code Execution Sandbox configuration from deployment_metadata.json
DEPLOYMENT_METADATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "deployment_metadata.json"
)
AGENT_ENGINE_ID = "projects/725054625673/locations/us-east1/reasoningEngines/7629302277928386560"
if os.path.exists(DEPLOYMENT_METADATA_PATH):
    try:
        with open(DEPLOYMENT_METADATA_PATH, "r") as f:
            _meta = json.load(f)
            if _meta.get("remote_agent_runtime_id"):
                AGENT_ENGINE_ID = _meta.get("remote_agent_runtime_id")
    except Exception:
        pass

code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=AGENT_ENGINE_ID
)


_firestore_client = None


def get_firestore_client():
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore

        _firestore_client = firestore.Client(project=FIRESTORE_PROJECT_ID)
    return _firestore_client


def search_house_plants(query: str = "") -> str:
    """Searches or lists plants in the house_plants Firestore database by name, care level, or keyword.

    Args:
        query: Optional search term to filter plants (e.g. "easy", "monstera", "toxic"). If empty, returns all plants.

    Returns:
        A JSON string listing matching plant records from the database.
    """
    db = get_firestore_client()
    docs = db.collection("house_plants").stream()
    results = []
    q = query.lower().strip()
    for doc in docs:
        data = doc.to_dict()
        if not q:
            results.append(data)
        else:
            searchable_text = f"{data.get('name', '')} {data.get('scientific_name', '')} {data.get('care_level', '')} {data.get('toxicity', '')} {data.get('description', '')}".lower()
            if q in searchable_text:
                results.append(data)
    if not results:
        return f"No plants found matching query: '{query}'."
    return json.dumps(results, indent=2)


def get_plant_details(plant_id: str) -> str:
    """Gets detailed information for a specific plant from the house_plants database by its plant_id.

    Args:
        plant_id: The unique plant identifier (e.g. "monstera_deliciosa", "snake_plant", "pothos_golden").

    Returns:
        A formatted JSON string with plant details or an error message if not found.
    """
    db = get_firestore_client()
    doc_ref = db.collection("house_plants").document(plant_id.lower().strip())
    doc = doc_ref.get()
    if doc.exists:
        return json.dumps(doc.to_dict(), indent=2)
    return f"Plant with ID '{plant_id}' was not found in the catalog."


def add_house_plant(
    plant_id: str,
    name: str,
    scientific_name: str,
    care_level: str,
    light_requirement: str,
    watering_frequency_days: int,
    toxicity: str,
    description: str,
) -> str:
    """Adds a new house plant entry to the Firestore house_plants collection.

    Args:
        plant_id: Unique identifier string for the plant (e.g. "peace_lily").
        name: Common name of the plant (e.g. "Peace Lily").
        scientific_name: Botanical scientific name (e.g. "Spathiphyllum wallisii").
        care_level: Difficulty level (e.g. "Easy", "Moderate", "Expert").
        light_requirement: Lighting requirement (e.g. "Low to medium indirect light").
        watering_frequency_days: Recommended watering interval in days (e.g. 7).
        toxicity: Safety info regarding pets/children (e.g. "Toxic to cats and dogs", "Non-toxic").
        description: Detailed plant description and care tips.

    Returns:
        Confirmation message that the plant was successfully added or updated.
    """
    db = get_firestore_client()
    doc_data = {
        "plant_id": plant_id.lower().strip(),
        "name": name,
        "scientific_name": scientific_name,
        "care_level": care_level,
        "light_requirement": light_requirement,
        "watering_frequency_days": int(watering_frequency_days),
        "humidity_preference": "Average",
        "toxicity": toxicity,
        "description": description,
    }
    db.collection("house_plants").document(doc_data["plant_id"]).set(doc_data)
    return f"Successfully saved plant '{name}' ({doc_data['plant_id']}) to Firestore!"


def update_watering_schedule(plant_id: str, watering_frequency_days: int) -> str:
    """Updates the watering frequency interval for a plant in the house_plants database.

    Args:
        plant_id: The unique identifier of the plant (e.g. "fiddle_leaf_fig").
        watering_frequency_days: New watering interval in days.

    Returns:
        Confirmation message of the update.
    """
    db = get_firestore_client()
    doc_ref = db.collection("house_plants").document(plant_id.lower().strip())
    doc = doc_ref.get()
    if not doc.exists:
        return f"Cannot update schedule: plant with ID '{plant_id}' does not exist."
    doc_ref.update({"watering_frequency_days": int(watering_frequency_days)})
    return f"Updated watering frequency for '{plant_id}' to every {watering_frequency_days} days."


def lookup_botanical_taxonomy(plant_name: str) -> str:
    """Queries the GBIF (Global Biodiversity Information Facility) public botanical API to fetch real scientific taxonomy (kingdom, family, genus, scientific name) for any plant.

    Args:
        plant_name: Common or botanical name of the plant (e.g. "Monstera deliciosa", "Fiddle Leaf Fig", "Peace Lily").

    Returns:
        A JSON string containing real botanical taxonomy data from the GBIF API.
    """
    import os
    import urllib.parse
    import urllib.request

    # If an API key is specified in the environment, read it from os.getenv
    api_key = os.getenv("TREFLE_API_KEY") or os.getenv("BOTANY_API_KEY")

    encoded_name = urllib.parse.quote(plant_name.strip())
    url = f"https://api.gbif.org/v1/species/match?name={encoded_name}"

    req = urllib.request.Request(url, headers={"User-Agent": "PlantCareAssistant/1.0"})
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                if data.get("matchType") == "NONE":
                    return f"No botanical taxonomy match found for '{plant_name}'."
                taxonomy_info = {
                    "query": plant_name,
                    "scientificName": data.get("scientificName"),
                    "canonicalName": data.get("canonicalName"),
                    "rank": data.get("rank"),
                    "kingdom": data.get("kingdom"),
                    "family": data.get("family"),
                    "genus": data.get("genus"),
                    "species": data.get("species"),
                    "confidence": data.get("confidence"),
                }
                return json.dumps(taxonomy_info, indent=2)
            return f"GBIF Botanical API returned status code {response.status}."
    except Exception as e:
        return f"Error fetching botanical data: {str(e)}"


def get_maps_api_key() -> str:
    """Retrieves GOOGLE_MAPS_API_KEY from environment or local .env file."""
    import os

    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not key or key == "PASTE_KEY_HERE":
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith("GOOGLE_MAPS_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val and val != "PASTE_KEY_HERE":
                            return val
    return key or ""


def geocode_address(address: str) -> str:
    """Uses the Google Maps Geocoding API to convert a street address or city name into latitude and longitude coordinates.

    Args:
        address: The street address or city to geocode (e.g. "1600 Amphitheatre Pkwy, Mountain View, CA" or "Seattle, WA").

    Returns:
        A JSON string containing the formatted address, location coordinates (latitude, longitude), and place ID.
    """
    import urllib.parse
    import urllib.request

    api_key = get_maps_api_key()
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    encoded_address = urllib.parse.quote(address.strip())
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PlantCareAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data.get("status") == "OK" and data.get("results"):
                result = data["results"][0]
                loc = result.get("geometry", {}).get("location", {})
                info = {
                    "input_address": address,
                    "formatted_address": result.get("formatted_address"),
                    "location": {
                        "latitude": loc.get("lat"),
                        "longitude": loc.get("lng"),
                    },
                    "place_id": result.get("place_id"),
                }
                return json.dumps(info, indent=2)
            return f"Geocoding API returned status '{data.get('status')}': {data.get('error_message', 'No results found.')}"
    except Exception as e:
        return f"Error during geocoding request: {str(e)}"


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "florist",
    radius_meters: float = 5000.0,
) -> str:
    """Uses the Google Places API (New) REST endpoint to search for nearby places of a given type around latitude/longitude coordinates.

    Args:
        latitude: Latitude coordinate of the search center.
        longitude: Longitude coordinate of the search center.
        place_type: Type of place to search for (e.g. "florist", "park", "store", "garden_center").
        radius_meters: Search radius in meters (default is 5000.0 meters).

    Returns:
        A JSON string listing matching nearby places with key fields (name, formatted address, location coordinates).
    """
    import urllib.error
    import urllib.request

    api_key = get_maps_api_key()
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }
    body = {
        "includedTypes": [place_type.lower().strip()],
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                },
                "radius": float(radius_meters),
            }
        },
    }

    try:
        req_data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            places_list = data.get("places", [])
            if not places_list:
                return f"No nearby places of type '{place_type}' found within {radius_meters}m radius."

            results = []
            for item in places_list:
                display_name = item.get("displayName", {}).get("text", "")
                formatted_addr = item.get("formattedAddress", "")
                loc = item.get("location", {})
                results.append(
                    {
                        "name": display_name,
                        "address": formatted_addr,
                        "location": {
                            "latitude": loc.get("latitude"),
                            "longitude": loc.get("longitude"),
                        },
                    }
                )
            return json.dumps(results, indent=2)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        return f"Places API HTTP error {e.code}: {err_body or e.reason}"
    except Exception as e:
        return f"Error searching nearby places: {str(e)}"


def generate_plant_image(prompt: str, tool_context: ToolContext) -> str:
    """Generates a realistic image for a plant, flower, or diagnostic guide using gemini-3.1-flash-lite-image model in global region.

    Saves the image as a Playground session artifact and uploads image bytes directly to public Cloud Storage, returning the public HTTPS URL.

    Args:
        prompt: Detailed visual description of the plant image to generate (e.g. "A vibrant green Monstera Deliciosa in a white ceramic pot").
        tool_context: ADK ToolContext automatically injected by the framework.

    Returns:
        The public HTTPS URL (https://storage.googleapis.com/<bucket>/<object>) of the generated image.
    """
    import uuid
    from google import genai
    from google.cloud import storage

    try:
        genai_client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT_ID,
            location="global",
        )
        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break

        if not image_bytes:
            return "Error: Model response did not contain generated image data."

        filename = f"plant_{uuid.uuid4().hex[:8]}.jpg"

        # 1. Save artifact with tool_context so it shows up in Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload image bytes directly to public Cloud Storage bucket in memory (no local file)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return public_url
    except Exception as e:
        return f"Error generating or uploading plant image: {str(e)}"


def generate_plant_video(prompt: str, tool_context: ToolContext) -> str:
    """Generates a short video for a houseplant, flower, or plant care routine using Google's gemini-omni-flash-preview model in the global region.

    Saves the video as a Playground session artifact and uploads video bytes directly to public Cloud Storage, returning the public HTTPS URL.

    Args:
        prompt: Detailed visual description of the plant video to generate (e.g. "Time-lapse of a Monstera Deliciosa leaf unfurling").
        tool_context: ADK ToolContext automatically injected by the framework.

    Returns:
        The public HTTPS URL (https://storage.googleapis.com/<bucket>/<object>) of the generated video.
    """
    import base64
    import uuid
    from google import genai
    from google.cloud import storage

    try:
        genai_client = genai.Client(
            vertexai=True,
            project=FIRESTORE_PROJECT_ID,
            location="global",
        )
        interaction = genai_client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )

        video_bytes = None
        mime_type = "video/mp4"

        if hasattr(interaction, "output_video") and interaction.output_video:
            if hasattr(interaction.output_video, "data") and interaction.output_video.data:
                video_bytes = base64.b64decode(interaction.output_video.data)
                if hasattr(interaction.output_video, "mime_type") and interaction.output_video.mime_type:
                    mime_type = interaction.output_video.mime_type
            elif hasattr(interaction.output_video, "uri") and interaction.output_video.uri:
                uri = interaction.output_video.uri
                file_name = uri.split("/")[-1]
                while True:
                    f_info = genai_client.files.get(name=f"files/{file_name}")
                    if getattr(f_info, "state", None) and getattr(f_info.state, "name", None) == "ACTIVE":
                        break
                    elif getattr(f_info, "state", None) and getattr(f_info.state, "name", None) == "FAILED":
                        return "Error: Video generation failed on server."
                    import time
                    time.sleep(3)
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
                    genai_client.files.download(file=uri, destination=tmp.name)
                    with open(tmp.name, "rb") as f:
                        video_bytes = f.read()

        if not video_bytes and hasattr(interaction, "outputs"):
            for item in interaction.outputs:
                if isinstance(item, dict) and item.get("type") == "video":
                    b64_data = item.get("data")
                    if b64_data:
                        video_bytes = base64.b64decode(b64_data)
                        break

        if not video_bytes:
            return "Error: Model response did not contain generated video data."

        filename = f"plant_video_{uuid.uuid4().hex[:8]}.mp4"

        # 1. Save artifact with tool_context so it shows up in Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload video bytes directly to public Cloud Storage bucket in memory (no local file)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
        return public_url
    except Exception as e:
        return f"Error generating or uploading plant video: {str(e)}"


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


_mem_service = None


def get_memory_service():
    global _mem_service
    if _mem_service is None:
        _mem_service = VertexAiMemoryBankService(
            project=FIRESTORE_PROJECT_ID,
            location="us-east1",
            agent_engine_id="7629302277928386560",
        )
    return _mem_service


async def ensure_memory_service_callback(callback_context: CallbackContext):
    if not callback_context._invocation_context.memory_service:
        callback_context._invocation_context.memory_service = get_memory_service()
    return None


async def generate_memories_callback(callback_context: CallbackContext):
    await ensure_memory_service_callback(callback_context)
    await callback_context.add_session_to_memory()
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_prompt = schema_manager.generate_system_prompt(
    role_description=(
        "You are PlantCare Assistant, an expert AI agent that helps plant enthusiasts "
        "care for their house plants, discover new varieties, generate plant images and videos, "
        "calculate plant watering math via Python code execution, and find local plant nurseries or florists."
    ),
    workflow_description="Analyze the request, use tools when appropriate, and return structured A2UI UI when visually appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

agent_instruction = f"""{a2ui_prompt}

Additional Capabilities & Rules:
1. A Firestore database containing a catalog of house plants (search_house_plants, get_plant_details, add_house_plant, update_watering_schedule).
2. The GBIF public botanical API via lookup_botanical_taxonomy to look up scientific plant taxonomy.
3. The Google Maps Geocoding API (geocode_address) to turn addresses or city names into latitude/longitude coordinates.
4. The Google Places API (New) (find_nearby_places) to find nearby plant nurseries, florists, or garden centers.
5. Image generation via generate_plant_image using gemini-3.1-flash-lite-image in the global region to create visuals of plants, flowers, or diagnostic guides.
6. Short video generation via generate_plant_video using gemini-omni-flash-preview in the global region to create time-lapse videos of houseplants, blooming flowers, or care routines.
7. Safe Python code execution via AgentEngineSandboxCodeExecutor for environmental calculations, pot volume math, and watering schedules.
8. Long-term Memory Bank integration via PreloadMemoryTool to recall user preferences and past facts across sessions. Pay special attention to and ALWAYS remember user allergies (e.g., pollen, sap, specific plant/flower species, pet allergies), user name/personal details, health conditions, and preferences stated across conversations, ensuring that all plant recommendations and advice strictly avoid any plants or materials that trigger the user's allergies.

IMPORTANT GUIDANCE:
- Memory & Storing Facts: You do NOT have or need any function tool to store memories (do NOT attempt to call non-existent tools like `store_user_data`, `tool_code`, `remember`, or `save_memory`). Simply acknowledge the user's name, allergies, or facts directly and warmly in plain text. Long-term memories are saved automatically in the background after each turn by your Memory Bank callback.
- Code Execution: Only run Python code when explicit math or calculations are needed."""


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=agent_instruction,
    tools=[
        PreloadMemoryTool(),
        search_house_plants,
        get_plant_details,
        add_house_plant,
        update_watering_schedule,
        lookup_botanical_taxonomy,
        geocode_address,
        find_nearby_places,
        generate_plant_image,
        generate_plant_video,
        get_current_time,
    ],
    before_agent_callback=ensure_memory_service_callback,
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)

