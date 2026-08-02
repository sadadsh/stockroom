"""Errors raised while reading and normalizing P-CAD ASCII libraries."""


class PcadError(ValueError):
    """Base class for deterministic P-CAD conversion failures."""


class PcadLexError(PcadError):
    """The input cannot be tokenized safely."""


class PcadParseError(PcadError):
    """The token stream is not a valid bounded P-CAD document."""


class PcadNormalizeError(PcadError):
    """The document cannot be represented without losing required data."""
