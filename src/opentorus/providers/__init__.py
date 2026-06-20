"""Model providers behind a common interface.

The provider layer must never leak into core agent logic: the agent loop only
ever talks to :class:`BaseProvider`.
"""

from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.providers.mock_provider import MockProvider

__all__ = ["BaseProvider", "ProviderResponse", "MockProvider"]
