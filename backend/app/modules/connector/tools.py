"""
Modular facade for Connector Tools.
Re-exports:
- TOOL_DEFINITIONS: Whitelisted OpenAI/Gemini/Anthropic function calling schemas
- execute_tool: Tenant-isolated tool dispatcher for Tally & CtrlBooks operations
"""

from app.modules.connector.tool_definitions import TOOL_DEFINITIONS
from app.modules.connector.tool_executor import execute_tool

__all__ = ["TOOL_DEFINITIONS", "execute_tool"]
