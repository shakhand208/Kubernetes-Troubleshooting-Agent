"""Global service state management to avoid circular imports."""

from typing import Any
from app.services.investigation_service import InvestigationService

_current_service: InvestigationService | None = None
_current_signal_provider: Any = None


def get_investigation_service() -> InvestigationService:
    """Get the current investigation service."""
    from app.services.investigation_service import InvestigationService
    from app.services.ai_agent import AIAgent
    from app.services.history_store import HistoryStore
    from app.services.signal_provider import MockSignalProvider
    import os
    
    global _current_service
    if _current_service is not None:
        return _current_service
    
    # Return mock service as default
    _history_path = os.getenv("HISTORY_FILE", "data/investigation_history.json")
    return InvestigationService(
        signal_provider=MockSignalProvider(),
        ai_agent=AIAgent(),
        history_store=HistoryStore(_history_path),
    )


def set_current_service(service: InvestigationService) -> None:
    """Set the current investigation service."""
    global _current_service
    _current_service = service


def get_current_signal_provider() -> Any:
    """Get the current signal provider."""
    global _current_signal_provider
    return _current_signal_provider


def set_current_signal_provider(provider: Any) -> None:
    """Set the current signal provider."""
    global _current_signal_provider
    _current_signal_provider = provider
