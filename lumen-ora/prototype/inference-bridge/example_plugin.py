"""
Example Lumen Ora plugin — copy to ~/.lumen/tools/my_plugin.py and modify.

Plugin files placed in ~/.lumen/tools/ are automatically loaded at startup.
Each file must define a PLUGIN_TOOLS list.  Every entry is a dict with:

  name        — unique tool name (string, no spaces)
  description — shown to the model in the system prompt
  parameters  — JSON Schema object describing the tool's parameters
  execute     — callable(params: dict) -> Any   (return value is serialised to JSON)

The tool is then available to the AI just like the built-in tools, and every
call passes through the Policy Engine before execution.
"""

from typing import Any


def _execute_hello(params: dict[str, Any]) -> str:
    name = params.get("name", "world")
    return f"Hello, {name}! This response came from a plugin."


PLUGIN_TOOLS = [
    {
        "name": "hello_plugin",
        "description": "Example plugin tool — greets by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name to greet."},
            },
            "required": [],
        },
        "execute": _execute_hello,
    }
]
