"""Unit tests for the Confluence module."""

# Ensure all Confluence modules are properly imported for testing
from mcp_atlassian.confluence.client import ConfluenceClient
from mcp_atlassian.confluence.pages import PagesMixin
from mcp_atlassian.confluence.spaces import SpacesMixin

__all__ = ["SpacesMixin", "PagesMixin", "ConfluenceClient"]


import sys

print(sys.path)
