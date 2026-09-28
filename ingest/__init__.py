"""Input ingestion for requirement material."""
from .extract import Document, SUPPORTED, bundle, extract_all, extract_file, extract_text

__all__ = ["Document", "SUPPORTED", "bundle", "extract_all", "extract_file", "extract_text"]
