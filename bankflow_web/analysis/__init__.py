"""Framework-neutral analysis orchestration for desktop frontends."""

from .service import AnalysisOutcome, AnalysisService, SourceOutcome
from .task_manager import AnalysisTaskManager

__all__ = ["AnalysisOutcome", "AnalysisService", "AnalysisTaskManager", "SourceOutcome"]
