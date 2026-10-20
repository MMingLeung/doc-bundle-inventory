"""Inventory nested archives and mixed documents into a manifest."""

from doc_bundle_inventory.errors import InventoryError
from doc_bundle_inventory.inventory import inventory
from doc_bundle_inventory.limits import Limits

__version__ = "0.1.0"
__all__ = ["InventoryError", "Limits", "inventory", "__version__"]
