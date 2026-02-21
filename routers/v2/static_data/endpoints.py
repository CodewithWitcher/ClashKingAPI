"""
Static game data endpoints for Clash of Clans.

This module provides access to static game data including buildings, troops, spells,
heroes, pets, equipment, and other game elements from the clashy.py library.
"""

import json
import os
import copy
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Path
from fastapi_cache.decorator import cache

router = APIRouter(prefix="/v2/static", tags=["Static Data"], include_in_schema=True)

# Load static data from clashy.py package
def load_static_data() -> dict:
    """Load static data from clashy.py's static_data.json file."""
    try:
        # Try to find the static_data.json file in the coc package
        import coc
        coc_path = os.path.dirname(coc.__file__)
        static_data_path = os.path.join(coc_path, "static", "static_data.json")

        with open(static_data_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load static data: {str(e)}")


def load_translations() -> dict:
    """Load translations from clashy.py's translations.json file."""
    try:
        import coc
        coc_path = os.path.dirname(coc.__file__)
        translations_path = os.path.join(coc_path, "static", "translations.json")

        with open(translations_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load translations: {str(e)}")


def translate_items(items: list, locale: str, translations: dict) -> list:
    """
    Translate item names based on locale.

    Args:
        items: List of items with TID.name field
        locale: Locale code (e.g., 'FR', 'DE', 'ES')
        translations: Translations dictionary

    Returns:
        List of items with translated names
    """
    locale_upper = locale.upper()
    translated_items = []

    for item in items:
        # Deep copy to avoid modifying original data
        item_copy = copy.deepcopy(item)
        tid_name = item_copy.get("TID", {}).get("name")

        if tid_name and tid_name in translations:
            translation = translations[tid_name].get(locale_upper)
            if translation:
                item_copy["name"] = translation

        translated_items.append(item_copy)

    return translated_items


# Cache the static data and translations in memory
STATIC_DATA = load_static_data()
TRANSLATIONS = load_translations()

# Available locales
AVAILABLE_LOCALES = ["EN", "AR", "CN", "CNT", "DE", "ES", "FA", "FI", "FR", "ID", "IT", "JP", "KR", "MS", "NL", "NO", "PL", "PT", "RU", "TH", "TR", "VI"]

# Available categories with their metadata
CATEGORIES = {
    "buildings": {"id_field": "_id", "supports_village": True, "supports_type": True},
    "traps": {"id_field": "_id", "supports_village": True},
    "troops": {"id_field": "_id", "supports_village": True, "supports_category": True},
    "guardians": {"id_field": "_id"},
    "spells": {"id_field": "_id", "supports_village": True},
    "heroes": {"id_field": "_id", "supports_village": True},
    "pets": {"id_field": "_id"},
    "equipment": {"id_field": "_id"},
    "decorations": {"id_field": "_id"},
    "obstacles": {"id_field": "_id"},
    "sceneries": {"id_field": "_id"},
    "skins": {"id_field": "_id"},
    "capital_house_parts": {"id_field": "_id"},
    "helpers": {"id_field": "_id"},
    "war_leagues": {"id_field": "_id"},
    "league_tiers": {"id_field": "_id"},
    "achievements": {"id_field": "_id"},
}

# Categories that have items with levels (eligible for maxlevel endpoint)
ELIGIBLE_CATEGORIES_FOR_LEVELS = {
    "buildings", "traps", "troops", "guardians", "spells", 
    "heroes", "pets", "equipment", "helpers", "achievements"
}


@router.get("/categories", name="Get all available static data categories")
@cache(expire=3600)
async def get_categories():
    """
    Get list of all available static data categories.

    Returns:
        List of category names with item counts
    """
    return {
        "categories": [
            {
                "name": category,
                "count": len(STATIC_DATA.get(category, []))
            }
            for category in CATEGORIES.keys()
        ]
    }


@router.get("/{category}", name="Get all items from a category")
@cache(expire=3600)
async def get_category_items(
    category: str = Path(..., description="Category name (e.g., buildings, troops, heroes)"),
    name: Optional[str] = Query(None, description="Filter by name (partial match, case-insensitive)"),
    village: Optional[str] = Query(None, description="Filter by village type (home/builder)"),
    type: Optional[str] = Query(None, description="Filter by type (for buildings)"),
    category_filter: Optional[str] = Query(None, description="Filter by category (for troops)", alias="category"),
    locale: Optional[str] = Query(None, description="Locale for translations (e.g., FR, DE, ES)")
):
    """
    Get all items from a specific category with optional filtering and translation.

    Args:
        category: Category name (buildings, troops, spells, heroes, pets, etc.)
        name: Optional filter by name (case-insensitive partial match)
        village: Optional filter by village type (home/builder)
        type: Optional filter by type (for buildings)
        category_filter: Optional filter by category (for troops)
        locale: Optional locale for translations (e.g., FR, DE, ES)

    Returns:
        List of items with their complete data

    Example:
        GET /v2/static/buildings?village=home
        GET /v2/static/troops?name=dragon
        GET /v2/static/heroes
        GET /v2/static/league_tiers?locale=FR
    """
    # Validate category
    if category not in CATEGORIES:
        raise HTTPException(
            status_code=404,
            detail=f"Category '{category}' not found. Available categories: {', '.join(CATEGORIES.keys())}"
        )

    # Validate locale if provided
    if locale and locale.upper() not in AVAILABLE_LOCALES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid locale '{locale}'. Available locales: {', '.join(AVAILABLE_LOCALES)}"
        )

    items = STATIC_DATA.get(category, [])
    category_meta = CATEGORIES[category]

    # Apply translation if locale is provided
    if locale:
        items = translate_items(items, locale, TRANSLATIONS)

    # Apply filters
    if name:
        items = [item for item in items if name.lower() in item.get("name", "").lower()]

    if village and category_meta.get("supports_village"):
        items = [item for item in items if item.get("village") == village.lower()]

    if type and category_meta.get("supports_type"):
        items = [item for item in items if item.get("type") == type]

    if category_filter and category_meta.get("supports_category"):
        items = [item for item in items if item.get("category") == category_filter]

    return {"items": items, "count": len(items)}


@router.get("/{category}/names", name="Get simplified list of names from a category")
@cache(expire=3600)
async def get_category_names(
    category: str = Path(..., description="Category name (e.g., buildings, troops, heroes)"),
    village: Optional[str] = Query(None, description="Filter by village type (home/builder)"),
    type: Optional[str] = Query(None, description="Filter by type (for buildings)"),
    category_filter: Optional[str] = Query(None, description="Filter by category (for troops)", alias="category"),
    locale: Optional[str] = Query(None, description="Locale for translations (e.g., FR, DE, ES)")
):
    """
    Get simplified list with only names from a category.
    Useful for dropdowns, autocomplete, and other UI components.

    Args:
        category: Category name (buildings, troops, spells, heroes, pets, etc.)
        village: Optional filter by village type (home/builder)
        type: Optional filter by type (for buildings)
        category_filter: Optional filter by category (for troops)
        locale: Optional locale for translations (e.g., FR, DE, ES)

    Returns:
        Array of item names

    Example:
        GET /v2/static/buildings/names?village=home
        Returns: ["Army Camp", "Barracks", "Town Hall", ...]

        GET /v2/static/troops/names
        Returns: ["Barbarian", "Archer", "Giant", ...]

        GET /v2/static/league_tiers/names?locale=FR
        Returns: ["Non classé", "Ligue Squelette 1", ...]
    """
    # Validate category
    if category not in CATEGORIES:
        raise HTTPException(
            status_code=404,
            detail=f"Category '{category}' not found. Available categories: {', '.join(CATEGORIES.keys())}"
        )

    # Validate locale if provided
    if locale and locale.upper() not in AVAILABLE_LOCALES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid locale '{locale}'. Available locales: {', '.join(AVAILABLE_LOCALES)}"
        )

    items = STATIC_DATA.get(category, [])
    category_meta = CATEGORIES[category]

    # Apply translation if locale is provided
    if locale:
        items = translate_items(items, locale, TRANSLATIONS)

    # Apply filters
    if village and category_meta.get("supports_village"):
        items = [item for item in items if item.get("village") == village.lower()]

    if type and category_meta.get("supports_type"):
        items = [item for item in items if item.get("type") == type]

    if category_filter and category_meta.get("supports_category"):
        items = [item for item in items if item.get("category") == category_filter]

    # Return just an array of names
    return [item.get("name") for item in items]


@router.get("/{category}/{item_id_or_name}", name="Get specific item by ID or name from a category")
@cache(expire=3600)
async def get_category_item_by_id(
    category: str = Path(..., description="Category name (e.g., buildings, troops, heroes)"),
    item_id_or_name: str = Path(..., description="Item ID (integer) or name (string)")
):
    """
    Get a specific item by its ID or name from a category.

    Args:
        category: Category name (buildings, troops, spells, heroes, pets, etc.)
        item_id: The unique ID of the item (integer) or the name of the item (string, case-insensitive)

    Returns:
        Complete item data with all levels and stats

    Example:
        GET /v2/static/buildings/1000001
        GET /v2/static/buildings/Town%20Hall
        GET /v2/static/heroes/28000000
        GET /v2/static/troops/4000000
    """
    return find_item_by_id_or_name(category, item_id_or_name)


def find_item_by_id_or_name(category: str, item_id: str) -> dict:
    """
    Helper function to find an item by ID or name in a category.
    
    Args:
        category: Category name
        item_id: Item ID (integer as string) or name (string)
    
    Returns:
        Item dictionary if found
    
    Raises:
        HTTPException: If category not found or item not found
    """
    # Validate category
    if category not in CATEGORIES:
        raise HTTPException(
            status_code=404,
            detail=f"Category '{category}' not found. Available categories: {', '.join(CATEGORIES.keys())}"
        )

    items = STATIC_DATA.get(category, [])
    category_meta = CATEGORIES[category]
    id_field = category_meta["id_field"]

    # Try to parse as integer first (ID lookup)
    try:
        item_id_int = int(item_id)
        item = next((i for i in items if i.get(id_field) == item_id_int), None)
        if item:
            return item
    except ValueError:
        # Not an integer, treat as name
        pass

    # If we reach here, either parsing as int failed or item not found by ID
    # Try to find by name (case-insensitive)
    item = next((i for i in items if i.get("name", "").lower() == item_id.lower()), None)

    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Item with ID or name '{item_id}' not found in category '{category}'"
        )

    return item


@router.get("/{category}/{item_id_or_name}/maxlevel", name="Get maximum level of an item")
@cache(expire=3600)
async def get_item_max_level(
    category: str = Path(..., description="Category name (e.g., buildings, troops, heroes)"),
    item_id_or_name: str = Path(..., description="Item ID (integer) or name (string)")
):
    """
    Get the maximum level of a specific item from a category.
    Only works for categories that have items with levels.

    Args:
        category: Category name (must be one of: buildings, traps, troops, guardians, spells, heroes, pets, equipment, helpers, achievements)
        item_id: The unique ID of the item (integer) or the name of the item (string, case-insensitive)

    Returns:
        Object with item name and maximum level

    Example:
        GET /v2/static/buildings/1000001/maxlevel
        Returns: {"name": "Town Hall", "max_level": 17}

        GET /v2/static/buildings/Town%20Hall/maxlevel
        Returns: {"name": "Town Hall", "max_level": 17}

        GET /v2/static/heroes/Barbarian%20King/maxlevel
        Returns: {"name": "Barbarian King", "max_level": 90}
    """
    # Check if category is eligible
    if category not in ELIGIBLE_CATEGORIES_FOR_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{category}' does not support levels. Eligible categories: {', '.join(sorted(ELIGIBLE_CATEGORIES_FOR_LEVELS))}"
        )

    # Find the item
    item = find_item_by_id_or_name(category, item_id_or_name)

    # Extract levels
    levels = item.get("levels", [])
    if not levels:
        raise HTTPException(
            status_code=404,
            detail=f"Item '{item.get('name', item_id_or_name)}' in category '{category}' has no levels defined"
        )

    # Extract level numbers from the levels array
    level_numbers = []
    for level in levels:
        if isinstance(level, dict):
            # If level is a dict, try to get the "level" field
            if "level" in level:
                level_numbers.append(level["level"])
        elif isinstance(level, (int, float)):
            # If level is directly a number
            level_numbers.append(int(level))

    if not level_numbers:
        raise HTTPException(
            status_code=404,
            detail=f"Could not extract level numbers from item '{item.get('name', item_id_or_name)}' in category '{category}'"
        )

    max_level = max(level_numbers)

    return {
        "name": item.get("name"),
        "max_level": max_level
    }
