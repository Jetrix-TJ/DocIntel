"""Error taxonomy. Every class still results in an emitted Stage 8 record."""


class DocIntelError(Exception):
    """Base for everything this package raises."""


class TransientError(DocIntelError):
    """Retry with backoff; on exhaustion route to the dead-letter queue."""


class PermanentError(DocIntelError):
    """Corrupt or unsupported input. DLQ + disposition dead_letter."""


class PackError(DocIntelError):
    """A pack hook threw. This document goes to the DLQ; the run continues."""


class ValidationError(DocIntelError):
    """A persona write violated the closed grammar (V1-V13). Whole write rejected."""


class ContractError(DocIntelError):
    """An emitted record failed Stage 8 schema validation."""
