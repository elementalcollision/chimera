"""Auto-generated skill: word_count_v5

Brief was:
# Input: args is a dict with key "text" (a string). Return the count of whitespace-separated tokens as a string. Raise ValueError if text is missing or not a string. Pure stdlib, no imports.

Schema:
# {
#   "type": "function",
#   "function": {
#     "name": "word_count_v5",
#     "description": "Count the number of whitespace-separated tokens in a text string.",
#     "parameters": {
#       "type": "object",
#       "properties": {
#         "text": {
#           "type": "string"
#         }
#       },
#       "required": [
#         "text"
#       ]
#     }
#   }
# }
"""

from __future__ import annotations

from chimera.tools import default_registry


async def handle(args, context):
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return str(len(text.split()))

SCHEMA = {'type': 'function', 'function': {'name': 'word_count_v5', 'description': 'Count the number of whitespace-separated tokens in a text string.', 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}}


def register(registry=None) -> None:
    """Idempotent registration for the 'word_count_v5' dynamic skill."""
    reg = registry or default_registry()
    reg.register(
        name='word_count_v5',
        toolset="dynamic",
        schema=SCHEMA,
        handler=handle,
        description='Count the number of whitespace-separated tokens in a text string.',
        override=True,
    )
