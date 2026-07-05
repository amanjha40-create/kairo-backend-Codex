"""Worker utilities — run the consumer with **`python -m app.workers.sqs_worker`**."""

from app.workers.registry import get_handler, register_handler, registered_types

__all__ = ["get_handler", "register_handler", "registered_types"]
