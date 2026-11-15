class SPMError(Exception):
    """Base exception for expected SPM MultiFrame failures."""


class SXMFormatError(SPMError):
    """The SXM file cannot be parsed safely."""


class MissingMetadataError(SPMError):
    """Required acquisition metadata is missing or invalid."""


class DriftFitError(SPMError):
    """Linear drift fitting failed or is underconstrained."""


class LatticeDetectionError(SPMError):
    """A physically consistent lattice could not be detected."""


class StaleAnalysisError(SPMError):
    """An analysis manifest does not match the current input files."""
