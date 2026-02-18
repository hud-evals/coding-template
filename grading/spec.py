"""Grading specifications and types."""

import logging
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import numpy as np

logger = logging.getLogger(__name__)

ValidateMode = Literal["baseline_fail", "golden_pass"]

def validate_grader_name(name: str) -> str:
    """Validate a grader name."""
    if not name:
        raise ValueError("Grader name cannot be empty")
    if not name.isidentifier():
        raise ValueError("Grader name must be a valid Python identifier")
    return name


GraderName = Annotated[str, "A grader name containing only letters, underscores, and hyphens"]


@dataclass(kw_only=True, frozen=True)
class SubGrade:
    name: GraderName
    score: float
    weight: float
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        validate_grader_name(self.name)


@dataclass(kw_only=True, frozen=True)
class Grade:
    """The grade returned by a scenario."""

    subscores: dict[str, float]
    weights: dict[str, float]
    metadata: dict[str, Any] | None

    @property
    def score(self):
        assert self.subscores.keys() == self.weights.keys()
        assert np.isclose(sum(self.weights.values()), 1)
        assert min(self.subscores.values()) >= 0
        assert max(self.subscores.values()) <= 1

        score = sum([self.subscores[key] * self.weights[key] for key in self.subscores.keys()])
        return np.clip(score, 0.0, 1.0)

    @staticmethod
    def from_subscores(subscores: list[SubGrade]) -> "Grade":
        # First pass: count occurrences of each name
        name_counts = {}
        for subscore in subscores:
            name_counts[subscore.name] = name_counts.get(subscore.name, 0) + 1

        # Second pass: assign final names
        subscores_dict = {}
        weights_dict = {}
        metadata_dict = {}
        name_usage = {}

        for subscore in subscores:
            original_name = subscore.name

            if name_counts[original_name] == 1:
                final_name = original_name
            else:
                if original_name not in name_usage:
                    name_usage[original_name] = 1
                else:
                    name_usage[original_name] += 1
                final_name = f"{original_name}-{name_usage[original_name]}"

            subscores_dict[final_name] = subscore.score
            weights_dict[final_name] = subscore.weight

            if subscore.metadata:
                metadata_dict[final_name] = subscore.metadata

        return Grade(subscores=subscores_dict, weights=weights_dict, metadata=metadata_dict)


class Grader:
    name: str = "BaseGrader"

    @classmethod
    def grade(cls, weight: float, **kwargs) -> SubGrade:
        """Grade and return a SubGrade."""
        result = cls.compute_score(**kwargs)

        if isinstance(result, tuple):
            score, metadata = result
        else:
            score = result
            metadata = {}

        return SubGrade(name=cls.name, score=score, weight=weight, parameters=kwargs, metadata=metadata)

    @classmethod
    def compute_score(cls, **kwargs) -> float | tuple[float, dict[str, Any]]:
        """Compute a score between 0.0 and 1.0 based on the current state."""
        raise NotImplementedError("Subclasses must implement compute_score")

    @classmethod
    def any(cls, weight: float, subgrades: list[SubGrade]) -> SubGrade:
        """Return a SubGrade that passes if any of the subgrades pass."""
        max_score = max(subgrade.score for subgrade in subgrades)
        combined_metadata = {
            "subgrades": [sg.name for sg in subgrades],
            "subgrade_metadata": {sg.name: sg.metadata for sg in subgrades if sg.metadata},
        }
        return SubGrade(
            name=f"{cls.name}_any",
            score=max_score,
            weight=weight,
            parameters={"subgrades": [sg.name for sg in subgrades]},
            metadata=combined_metadata,
        )

    @classmethod
    def all(cls, weight: float, subgrades: list[SubGrade]) -> SubGrade:
        """Return a SubGrade that passes only if all subgrades pass."""
        min_score = min(subgrade.score for subgrade in subgrades)
        combined_metadata = {
            "subgrades": [sg.name for sg in subgrades],
            "subgrade_metadata": {sg.name: sg.metadata for sg in subgrades if sg.metadata},
        }
        return SubGrade(
            name=f"{cls.name}_all",
            score=min_score,
            weight=weight,
            parameters={"subgrades": [sg.name for sg in subgrades]},
            metadata=combined_metadata,
        )
