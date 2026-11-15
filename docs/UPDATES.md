# How SPM Studio updates itself

## For users

- *Settings › Check for updates…* (also in *Help*) compares your version with the newest **GitHub Release**
  of the repository in `src/spm_studio/update_config.json` and shows the notes of every newer version.
- With your consent (*Install update*), it downloads that release's source archive over HTTPS, checks that
  the archive is safe to extract and contains the announced version, and opens a terminal running the
  archive's own installer. Nothing is installed without that click.
- The installer builds the new version in its own folder (`releases/<version>`) with its own Python
  environment, runs an offscreen self-test, and only then switches the launcher. If anything fails, the
  current version keeps working. User data (scans, results, scripts, settings, conversations, AI sign-ins)
  lives outside the release folders and is never modified.
- Optional quiet check at most once a day at startup (one request to `api.github.com`; switch it off in the
  same dialog). Terminal: `spm-studio --check-update`, `spm-studio --update`.
- Private repository: the check needs a GitHub sign-in on your computer (`gh auth login`, or a token in
  `SPM_STUDIO_GITHUB_TOKEN`). See the README, *Private repository*.

If the project publishes tags but no GitHub Release, the check uses the newest `vX.Y.Z` tag and reads the
notes from that tag's `CHANGELOG.md`. Pre-releases are offered only with `"include_prereleases": true`.

## For maintainers

See [`RELEASING.md`](RELEASING.md).

## History

Up to 0.5.4 SPM Studio used an opt-in *offline patch* system (`spm-studio-update patch.zip` with a
`patch.json` manifest of file hashes, created by `tools/make_patch.py`). It was retired in internal build
0.7.0, when releases became complete, side-by-side installations; the tool and the patch format are no
longer part of the project. Two of its principles were kept: user files are never overwritten, and the
Python package stays named `spm_studio` so that existing extensions and settings keep working.
