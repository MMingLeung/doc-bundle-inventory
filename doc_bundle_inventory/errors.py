"""Errors raised by the public inventory API."""


class InventoryError(Exception):
    """The input cannot be inventoried.

    Nested members that are merely skipped (path traversal, size limits,
    optional RAR/7z support) are reported in the manifest ``warnings`` list
    instead of raising.
    """


class OptionalDependencyError(InventoryError):
    """An optional archive backend is not installed."""
