"""Run native analysis in an isolated process; never inside the Qt event loop."""
from __future__ import annotations
import argparse, importlib.util, os, sys, traceback
from pathlib import Path
from .module_api import from_snapshot, emit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--entry-file', required=True)
    parser.add_argument('--function', default='run')
    parser.add_argument('--context', required=True)
    args = parser.parse_args()
    try:
        ctx = from_snapshot(Path(args.context))
        module_file = Path(args.entry_file).resolve()
        sys.path.insert(0, str(module_file.parent))
        spec = importlib.util.spec_from_file_location(f'_spm_module_{os.getpid()}', module_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f'Cannot load entrypoint {module_file}')
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except ModuleNotFoundError as exc:
            if exc.name and '.' not in exc.name:
                candidate = module_file.parent / f'{exc.name}.py'
                raise ModuleNotFoundError(
                    f'{exc.name!r} not found for {module_file.parent.name}. '
                    f'For a local helper, place it at {candidate}; '
                    'for a third-party dependency, install it into the SPM Studio isolated Python environment.'
                ) from exc
            raise
        run = getattr(mod, args.function)
        ctx.log(f'Running {module_file.name} on {ctx.scan_path.name} / {ctx.channel} / {ctx.direction}')
        run(ctx)
        emit('finished', status='success')
    except Exception as exc:
        traceback.print_exc()
        emit('error', message=f'{type(exc).__name__}: {exc}')
        emit('finished', status='failed')
        raise SystemExit(1)

if __name__ == '__main__':
    main()
