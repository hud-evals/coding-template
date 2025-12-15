import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Literal, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


def validate_grader_name(name: str) -> str:
    """Validate a grader name."""
    if not name:
        raise ValueError("Grader name cannot be empty")
    if not name.isidentifier():
        raise ValueError("Grader name must be a valid Python identifier")
    return name


# Type for grader names that don't contain numbers
GraderName = Annotated[str, "A grader name containing only letters, underscores, and hyphens"]


@dataclass(kw_only=True, frozen=True)
class SubGrade:
    name: GraderName
    score: float
    weight: float
    parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Validate the name, since we use hyphens and numbers to distinguish multiple subgraders of the same type
        validate_grader_name(self.name)


@dataclass(kw_only=True, frozen=True)
class Grade:
    """The grade to return within the mcp.grade_problem tool."""

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
                # No duplicates, use original name
                final_name = original_name
            else:
                # Has duplicates, add number suffix
                if original_name not in name_usage:
                    name_usage[original_name] = 1
                else:
                    name_usage[original_name] += 1
                final_name = f"{original_name}-{name_usage[original_name]}"

            subscores_dict[final_name] = subscore.score
            weights_dict[final_name] = subscore.weight

            # Add metadata using the final name as the key
            if subscore.metadata:
                metadata_dict[final_name] = subscore.metadata

        return Grade(subscores=subscores_dict, weights=weights_dict, metadata=metadata_dict)


class EnvironmentState:
    """The state of the environment at the time of grading."""

    def __init__(self):
        """Initialize the environment state without database functionality."""
        logger.info("Initializing EnvironmentState without database")

    @classmethod
    def from_sqlite(cls, sqlite_path: str) -> "EnvironmentState":
        """Create an EnvironmentState from an existing SQLite database file."""
        # This method is kept for compatibility but no longer uses the database
        logger.warning("from_sqlite method called but database functionality is disabled")
        return cls()

    def export_to_sqlite(self, sqlite_path: str) -> None:
        """Export the current database state to a new SQLite file."""
        # This method is kept for compatibility but no longer uses the database
        logger.warning("export_to_sqlite method called but database functionality is disabled")


# the different levels of review
ReviewLevel = Literal[
    "no-review",
    "creator-reviewed",
    "hud-approved",
    "customer-approved",
]

@dataclass
class HintSpec:
    hint_type: Literal["legit", "leaky"]
    # the text of the hint (provided to the model)
    text: str
    # the reason why the hint is legitimate (for human reviewers)
    why_legitmate: str | None = None



# New registry machinery
@dataclass
class ProblemSpec:
    # required fields (no defaults)
    id: str
    description: str
    hints: list[HintSpec]
    difficulty: str
    task_type: str
    solution_fn: Callable[[EnvironmentState], Grade] = field(repr=False)
    review_level: ReviewLevel
    # optional fields (with defaults)
    config: dict[str, Any] | None
    image_base_string: str
    startup_command: str
    demo: bool
    too_hard: bool
    base: str
    test: str
    golden: str


# global list of all registered problems
PROBLEM_REGISTRY: list[ProblemSpec] = []

# decorator to register a problem spec alongside its grading function


def problem(
    *,
    id: str,
    description: str,
    hints: list[HintSpec],
    difficulty: str,
    task_type: str,
    review_level: ReviewLevel,
    config: dict[str, Any] | None = None,
    image_base_string: str = "eval_",
    startup_command: str = "hud_eval",
    demo: bool = False,
    too_hard: bool = False,
    base: str,
    test: str,
    golden: str,
):
    def decorator(fn: Callable[[EnvironmentState], Grade]):
        spec = ProblemSpec(
            id=id,
            description=description,
            hints=hints,
            difficulty=difficulty,
            task_type=task_type,
            review_level=review_level,
            config=config,
            image_base_string=image_base_string,
            startup_command=startup_command,
            solution_fn=fn,
            demo=demo,
            too_hard=too_hard,
            base=base,
            test=test,
            golden=golden,
        )
        PROBLEM_REGISTRY.append(spec)
        return fn

    return decorator


class Grader:
    name: str = "BaseGrader"

    @classmethod
    def grade(cls, state: EnvironmentState, weight: float, **kwargs) -> SubGrade:
        """Grade the current state and return a SubGrade."""
        result = cls.compute_score(state, **kwargs)

        # Handle both float and tuple return types
        if isinstance(result, tuple):
            score, metadata = result
        else:
            score = result
            metadata = {}

        return SubGrade(name=cls.name, score=score, weight=weight, parameters=kwargs, metadata=metadata)

    @classmethod
    def compute_score(cls, state: EnvironmentState, **kwargs) -> Union[float, Tuple[float, Dict[str, Any]]]:
        """
        Compute a score between 0.0 and 1.0 based on the current state.

        Can return either:
        - float: Just the score
        - tuple[float, dict]: Score and metadata dictionary
        """
        raise NotImplementedError("Subclasses must implement compute_score")

    @classmethod
    def any(cls, weight: float, subgrades: List[SubGrade]) -> SubGrade:
        """Return a SubGrade that passes if any of the subgrades pass."""
        max_score = max(subgrade.score for subgrade in subgrades)
        # Combine metadata from all subgrades
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
    def all(cls, weight: float, subgrades: List[SubGrade]) -> SubGrade:
        """Return a SubGrade that passes only if all subgrades pass."""
        min_score = min(subgrade.score for subgrade in subgrades)
        # Combine metadata from all subgrades
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
