# MultiFrame physical stack (experimental)

Resamples every included scan onto the selected reference scan's physical pixel
centers using **scan center, range and angle**, not the same pixel crop from
all images. Reports contribution counts and per-pixel population SD, without
nonrigid warping. Same selected channel/direction required on all scans.

**Important restrictions:** The original `spm-multiframe-v0.1.2` engines were
archived in legacy_reference but not integrated; time-dependent drift, atom tracking, primitive lattice fitting,
Z/Δf_t consistency and per-scan crop previews are absent. Full physical
alignment **requires orientation validation** on the user's real acquisitions;
the module refuses to run without explicitly acknowledging this. GWY files
without absolute centers/angles will be skipped (never made up). Not intended
as a validated scientific replacement for `spm-stack`.
