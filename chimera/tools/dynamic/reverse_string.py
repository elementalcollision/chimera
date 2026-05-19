"""Auto-generated skill: reverse_string

Brief was:
# Take a string named text and return reversed: <reversed text>

Schema:
# {
#   "type": "function",
#   "function": {
#     "name": "reverse_string",
#     "description": "Reverse a string",
#     "parameters": {
#       "type": "object",
#       "properties": {
#         "text": {
#           "type": "string",
#           "description": "The string to reverse"
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


async def handle(args: dict, context) -> str:
    if "text" not in args:
        raise ValueError('Missing required argument "text"')
    if not isinstance(args["text"], str):
        raise ValueError('Argument "text" must be a string')
    return args["text"][::-1]

SCHEMA = {'type': 'function', 'function': {'name': 'reverse_string', 'description': 'Reverse a string', 'parameters': {'type': 'object', 'properties': {'text': {'type': 'string', 'description': 'The string to reverse'}}, 'required': ['text']}}}


def register(registry=None) -> None:
    """Idempotent registration for the 'reverse_string' dynamic skill."""
    reg = registry or default_registry()
    reg.register(
        name='reverse_string',
        toolset="dynamic",
        schema=SCHEMA,
        handler=handle,
        description='Reverse a string',
        override=True,
    )
