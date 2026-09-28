"""Typed errors for the MX AI Suite.

Every failure the suite can produce is one of these, so the UI and CLI can
render a useful message instead of a stack trace.
"""
from __future__ import annotations


class SuiteError(Exception):
    """Base for every error raised by the suite."""

    #: short, stable code shown in the UI and logs
    code = "SUITE_ERROR"
    #: what the operator should do about it
    remedy = "Check the logs for detail."

    def __init__(self, message: str, *, remedy: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if remedy:
            self.remedy = remedy

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "remedy": self.remedy}


class ConfigError(SuiteError):
    code = "CONFIG"
    remedy = "Fix config/suite.yaml or your .env, then run `python run.py doctor`."


class LLMError(SuiteError):
    code = "LLM"
    remedy = "Check your model credentials with `python run.py doctor`."


class MaximoError(SuiteError):
    code = "MAXIMO"
    remedy = "Check MAXIMO_MANAGE_URL / MAXIMO_MANAGE_APIKEY, or run offline (validation falls back to the bundled schema catalogue)."


class BrainError(SuiteError):
    code = "BRAIN"
    remedy = "Run `python run.py index --rebuild` to rebuild the AI Brain index."


class GateError(SuiteError):
    code = "GATE"
    remedy = "A user gate must be approved before this phase can run."


class RenderError(SuiteError):
    code = "RENDER"
    remedy = "Check that the template exists under /templates and is a valid .docx."


class IngestError(SuiteError):
    code = "INGEST"
    remedy = "Unsupported or unreadable input file. Supported: .docx .xlsx .pdf .pptx .md .txt .json .csv"
