"""
Pinacotheca - Old World Sprite Extractor

Extract and catalog sprite assets from the Old World strategy game.
"""

__version__ = "1.0.0"
__all__ = ["extract_sprites", "generate_gallery", "categorize", "CATEGORIES"]

from pinacotheca.categories import CATEGORIES, categorize
from pinacotheca.extractor import extract_sprites
from pinacotheca.gallery import generate_gallery
