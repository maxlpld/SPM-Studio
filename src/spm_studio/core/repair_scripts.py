"""Safely restore missing factory analysis companion files.

Usage: python -m spm_studio.core.repair_scripts
The app's launch scripts must set RS_APP_ROOT to the copied project root.
"""
from __future__ import annotations
from .paths import repair_missing_factory_helpers, scripts_dir


def main():
    for note in repair_missing_factory_helpers():
        print('Restored:', note)
    print('Factory script helpers checked:',scripts_dir())


if __name__ == '__main__':
    main()
