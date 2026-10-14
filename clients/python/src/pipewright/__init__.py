"""Pipewright's Python client: `from pipewright import Client`."""

from pipewright.client import Client, PipewrightError
from pipewright.embed import embed_link, embed_token

__all__ = ["Client", "PipewrightError", "embed_link", "embed_token"]
