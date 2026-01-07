"""
Pinacotheca - Old World Sprite Extractor

Extract and catalog sprite assets from the Old World strategy game.
"""

__version__ = "1.0.0"
__all__ = [
    "extract_sprites",
    "extract_unit_meshes",
    "generate_gallery",
    "categorize",
    "CATEGORIES",
    "render_mesh_to_image",
]

from pinacotheca.categories import CATEGORIES, categorize
from pinacotheca.extractor import extract_sprites, extract_unit_meshes
from pinacotheca.gallery import generate_gallery
from pinacotheca.renderer import render_mesh_to_image
