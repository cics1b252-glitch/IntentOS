"""Modules package — plugin system for the Intent OS Kernel."""

from intent_kernel.modules.base import Module
from intent_kernel.modules.core import CoreModule
from intent_kernel.modules.fin import FinanceModule

__all__ = ["Module", "CoreModule", "FinanceModule"]
