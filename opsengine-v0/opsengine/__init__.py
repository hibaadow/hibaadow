"""Compliance operations engine v0: detect -> plan -> act -> verify -> record."""
from .config import load_dotenv

load_dotenv()  # before any module reads settings; real environment variables win

__version__ = "0.1.0"
