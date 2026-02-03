"""Task definitions for coding environment.

Tasks are registered via the @problem decorator when imported.
"""
from grading import PROBLEM_REGISTRY

from . import basic, hard, medium  # noqa: F401 - registers problems

__all__ = ["PROBLEM_REGISTRY"]
