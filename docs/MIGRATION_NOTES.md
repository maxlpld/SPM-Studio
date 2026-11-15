# Migration state — v0.3.1

The original sources are now available under `legacy_reference/` and were
statically inspected, but **their complex scientific algorithms have not been
fully ported**. The v0.3.0 project was originally created without the source
archives; the old statements claiming the sources were unavailable are no
longer applicable to this v0.3.1 audit. The archive includes 119 parseable
Python source files across all supplied projects.

The v0.3.1 core patch replaces the fragile normal SXM loading path with a
small native, guarded Nanonis SXM reader. `nanonispy` remains optional for
unusual SXM dialects, with its removed NumPy aliases installed only while
its parser is running. `gwyfile` 0.3.0 or newer is a default requirement,
because Gwyddion is a first-class source format. Diagnostic CLI is
`spm-studio-check`. The GUI layout is unchanged.

Scientific migration status, module by module, and a precise statement of
remaining acceptance tests are in `REQUIREMENTS_AUDIT.md`.
