"""Task definitions for coding environment.

Tasks are registered via the @problem decorator when imported.
"""
import importlib
import pkgutil

from grading import PROBLEM_REGISTRY


def import_submodules(module):
    """Import all submodules of a module, recursively."""
    for _loader, module_name, _is_pkg in pkgutil.walk_packages(
        module.__path__, module.__name__ + "."
    ):
        importlib.import_module(module_name)


def load_all_tasks():
    """Load all task modules to register problems."""
    from . import basic, hard, medium  # noqa: F401


# Load all tasks on import
load_all_tasks()

__all__ = ["PROBLEM_REGISTRY", "load_all_tasks"]
