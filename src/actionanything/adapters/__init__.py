"""Provider payload adapters that normalize into canonical actions.

Adapters deliberately do not make model requests or own API keys. They are
small parsing boundaries between a provider response and the local runtime.
"""

from .base import ActionAdapter, AdapterCapabilities, AdapterError
from .anthropic import AnthropicComputerUseAdapter
from .openai import OpenAIComputerUseAdapter

__all__ = [
    "ActionAdapter",
    "AdapterCapabilities",
    "AdapterError",
    "AnthropicComputerUseAdapter",
    "OpenAIComputerUseAdapter",
]
