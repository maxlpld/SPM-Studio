# KPFM edge analysis (experimental)

Assumes the specified topography and selected CPD channel share a registered,
identical grid (it refuses shape differences). Calculates 10–90% topographic width,
FWHM of an endpoint-linear CPD residual near the steepest topographic edge,
absolute width difference, and 2-D Pearson correlation between |∇Z| and CPD.
Requires a line ROI or uses averaged columns. Units are SI for values,
metres for calibrated distances. These baseline/crossing choices are NOT verified
equivalent to the old 2,964-line analysis, which was not included.
