"""Cross-platform helpers for the AI assistant (Linux, macOS, Windows).

Pure Python, no Qt: everything here is unit-testable without a display.

* resolve_command(): turns ``pi`` / ``pi.cmd`` / an npm shim into a program +
  argument prefix that QProcess/subprocess can start on every OS. On Windows,
  npm installs ``.cmd`` batch shims which CreateProcess cannot run directly and
  whose argument quoting through ``cmd.exe`` is unsafe; the real JavaScript entry
  point is started with ``node`` instead. On Linux/macOS a shim starting with
  ``#!/usr/bin/env node`` also fails when Node is the private per-user copy that
  is not on PATH, so the same resolution is used there.
* node_info(): finds a usable Node.js (system or SPM Studio's private copy).
* git_bash(): Pi needs Bash on native Windows (Git for Windows).
* hardware(): RAM, GPU and VRAM on all three systems, with what was measured
  versus unknown stated explicitly.
* open_terminal(): runs a generated script in a visible terminal window, used
  for the one step that cannot be automated: browser sign-in (OAuth) for
  ChatGPT/Claude subscriptions, which Pi only offers interactively.
"""
from __future__ import annotations
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform.startswith('win')
IS_MAC = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

NODE_MIN = (22, 19, 0)       # @earendil-works/pi-coding-agent "engines" requirement


def os_label() -> str:
    return 'Windows' if IS_WINDOWS else 'macOS' if IS_MAC else 'Linux'


# --------------------------------------------------------------------------- paths
def data_root() -> Path:
    from ..paths import data_dir
    return data_dir()


def private_node_dir() -> Path:
    return data_root() / 'ai' / 'node'


def private_node_executable() -> Path | None:
    base = private_node_dir() / 'current'
    exe = base / 'node.exe' if IS_WINDOWS else base / 'bin' / 'node'
    return exe if exe.is_file() else None


def node_bin_dir(node: str | Path) -> Path:
    return Path(node).resolve().parent


def npm_for_node(node: str | Path) -> list[str] | None:
    """npm belonging to a given node: ``[node, npm-cli.js]`` (portable on all OSes)."""
    base = node_bin_dir(node)
    for candidate in (base / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js',                 # Windows layout
                      base.parent / 'lib' / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js'):  # Unix layout
        if candidate.is_file():
            return [str(node), str(candidate)]
    found = shutil.which('npm')
    if found:
        program, prefix = resolve_command(found)
        return [program, *prefix]
    return None


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', text or '')
    return tuple(int(x) for x in m.groups()) if m else None


def node_version(node: str | Path) -> tuple[int, int, int] | None:
    try:
        r = subprocess.run([str(node), '--version'], capture_output=True, text=True, timeout=8,
                           **hidden_window())
        return parse_version(r.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


def node_info() -> dict:
    """Prefer SPM Studio's private Node, then the system one; report the version."""
    seen = []
    private = private_node_executable()
    if private:
        seen.append(('private', str(private)))
    system = shutil.which('node')
    if system:
        seen.append(('system', system))
    best = {'path': '', 'version': None, 'source': '', 'ok': False, 'found': []}
    for source, path in seen:
        version = node_version(path)
        best['found'].append({'source': source, 'path': path, 'version': version})
        if version and version >= NODE_MIN and not best['ok']:
            best.update(path=path, version=version, source=source, ok=True)
    if not best['ok'] and best['found']:
        first = best['found'][0]
        best.update(path=first['path'], version=first['version'], source=first['source'])
    return best


def version_text(v) -> str:
    return '.'.join(map(str, v)) if v else 'unknown'


# ---------------------------------------------------------------- command resolution
_CMD_SHIM = re.compile(r'"%(?:~?dp0)%\\?([^"%]+?\.(?:c|m)?js)"', re.IGNORECASE)


def _shim_target(shim: Path) -> Path | None:
    """JavaScript target of an npm ``.cmd``/``.ps1``/shell shim, if recognisable."""
    try:
        text = shim.read_text(encoding='utf8', errors='replace')[:6000]
    except OSError:
        return None
    m = _CMD_SHIM.search(text)                                     # Windows .cmd shim
    if m:
        target = (shim.parent / m.group(1).replace('\\', '/')).resolve()
        return target if target.is_file() else None
    m = re.search(r'\$basedir/([^"\s]+?\.(?:c|m)?js)', text)       # sh / ps1 shim
    if m:
        target = (shim.parent / m.group(1)).resolve()
        return target if target.is_file() else None
    return None


def _package_bin(package_dir: Path, name: str) -> Path | None:
    try:
        meta = json.loads((package_dir / 'package.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        return None
    binary = meta.get('bin')
    rel = binary.get(name) or next(iter(binary.values()), None) if isinstance(binary, dict) else binary
    if not isinstance(rel, str):
        return None
    target = (package_dir / rel).resolve()
    return target if target.is_file() else None


def find_node_for(script: Path) -> str:
    """The node to use for a JS entry point: private one, then system one."""
    info = node_info()
    if info['path']:
        return info['path']
    return 'node.exe' if IS_WINDOWS else 'node'


def resolve_command(executable: str) -> tuple[str, list[str]]:
    """Return ``(program, prefix_args)`` able to start ``executable`` on this OS.

    Handles: a plain program on PATH, an absolute path, an npm ``.bin`` symlink
    or shim, a Windows ``.cmd`` shim and a ``.js`` entry point.
    """
    exe = str(executable or '').strip().strip('"')
    if not exe:
        raise ValueError('No executable configured')
    path = Path(exe).expanduser()
    if not (path.is_absolute() or os.sep in exe or (os.altsep and os.altsep in exe)):
        found = shutil.which(exe)
        if not found:
            raise FileNotFoundError(f'"{exe}" was not found on PATH')
        path = Path(found)
    if not path.exists():
        raise FileNotFoundError(f'{path} does not exist')
    suffix = path.suffix.lower()
    if suffix in ('.js', '.mjs', '.cjs'):
        return find_node_for(path), [str(path)]
    if IS_WINDOWS and suffix in ('.cmd', '.bat', '.ps1', ''):
        target = _shim_target(path if suffix else path.with_suffix('.cmd'))
        if target is not None:
            return find_node_for(target), [str(target)]
        if suffix in ('.cmd', '.bat'):
            # Last resort: run the batch file through cmd.exe. Prompts are always sent
            # over stdin by SPM Studio, so no user text passes through cmd quoting.
            return os.environ.get('COMSPEC', 'cmd.exe'), ['/d', '/s', '/c', str(path)]
        if suffix == '.ps1':
            return 'powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(path)]
    real = path.resolve()
    if real.suffix.lower() in ('.js', '.mjs', '.cjs'):
        # npm .bin/pi symlink -> .../dist/cli.js : run with an explicit node, so a
        # private Node that is not on PATH still works with "#!/usr/bin/env node".
        return find_node_for(real), [str(real)]
    if not IS_WINDOWS:
        try:
            head = real.read_bytes()[:200]
        except OSError:
            head = b''
        if head.startswith(b'#!') and b'node' in head.split(b'\n', 1)[0]:
            return find_node_for(real), [str(real)]
    return str(path), []


def command_env(extra: dict | None = None, node: str | None = None) -> dict:
    """Process environment with the node in use first on PATH (npm/pi need it)."""
    env = dict(os.environ)
    node = node or node_info().get('path')
    if node and Path(node).is_absolute():
        env['PATH'] = str(Path(node).parent) + os.pathsep + env.get('PATH', '')
    env.setdefault('PI_SKIP_VERSION_CHECK', '1')
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
    return env


def hidden_window() -> dict:
    """subprocess kwargs that keep a console window from flashing on Windows."""
    if IS_WINDOWS:
        return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)}
    return {}


# ----------------------------------------------------------------------- windows bash
def git_bash() -> str | None:
    if not IS_WINDOWS:
        return shutil.which('bash')
    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        base = os.environ.get(env)
        if not base:
            continue
        for rel in (r'Git\bin\bash.exe', r'Programs\Git\bin\bash.exe'):
            p = Path(base) / rel
            if p.is_file():
                return str(p)
    found = shutil.which('bash')
    if found and 'system32' not in found.lower():     # System32\bash.exe is the WSL shim
        return found
    return None


def winget() -> str | None:
    return shutil.which('winget') if IS_WINDOWS else None


def brew() -> str | None:
    if not IS_MAC:
        return None
    return shutil.which('brew') or next((p for p in ('/opt/homebrew/bin/brew', '/usr/local/bin/brew')
                                         if Path(p).is_file()), None)


# ----------------------------------------------------------------------- hardware
def _run(cmd, timeout=4) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **hidden_window())
        return r.stdout if r.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def total_ram_bytes() -> int | None:
    if IS_LINUX:
        try:
            for line in open('/proc/meminfo', encoding='utf8'):
                if line.startswith('MemTotal:'):
                    return int(line.split()[1]) * 1024
        except OSError:
            return None
    if IS_MAC:
        out = _run(['sysctl', '-n', 'hw.memsize']).strip()
        return int(out) if out.isdigit() else None
    if IS_WINDOWS:
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:
            return None
    return None


def gpus() -> list[dict]:
    """Detected GPUs: name, vendor, usable memory (bytes or None) and backend."""
    found = []
    smi = shutil.which('nvidia-smi')
    if not smi and IS_WINDOWS:
        p = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'nvidia-smi.exe'
        smi = str(p) if p.is_file() else None
    if smi:
        for line in _run([smi, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits']).splitlines():
            parts = [x.strip() for x in line.split(',')]
            if len(parts) >= 2 and parts[1].replace('.', '', 1).isdigit():
                found.append({'name': parts[0], 'vendor': 'NVIDIA', 'memory_bytes': int(float(parts[1]) * 1024 ** 2),
                              'backend': 'CUDA', 'measured': True})
    if IS_LINUX and shutil.which('rocm-smi'):
        out = _run(['rocm-smi', '--showmeminfo', 'vram', '--json'])
        try:
            data = json.loads(out) if out else {}
            for card, info in data.items():
                total = info.get('VRAM Total Memory (B)') or info.get('vram total memory (b)')
                if total:
                    found.append({'name': card, 'vendor': 'AMD', 'memory_bytes': int(total), 'backend': 'ROCm',
                                  'measured': True})
        except (ValueError, AttributeError):
            pass
    if IS_MAC:
        chip = _run(['sysctl', '-n', 'machdep.cpu.brand_string']).strip()
        if platform.machine() == 'arm64':
            ram = total_ram_bytes()
            # Apple Silicon: unified memory; by default macOS lets the GPU wire roughly
            # 2/3 (<=36 GB machines) to 3/4 of it. Reported as an estimate, not a measurement.
            share = 0.67 if (ram or 0) <= 36 * 1024 ** 3 else 0.75
            found.append({'name': chip or 'Apple Silicon', 'vendor': 'Apple',
                          'memory_bytes': int(ram * share) if ram else None, 'backend': 'Metal',
                          'measured': False})
    if IS_WINDOWS and not found:
        out = _run(['powershell.exe', '-NoProfile', '-Command',
                    'Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json'], timeout=8)
        try:
            items = json.loads(out) if out else []
            items = items if isinstance(items, list) else [items]
            for item in items:
                name = str(item.get('Name') or '')
                if not name or 'basic display' in name.lower():
                    continue
                vendor = 'AMD' if 'amd' in name.lower() or 'radeon' in name.lower() else \
                         'Intel' if 'intel' in name.lower() else 'NVIDIA' if 'nvidia' in name.lower() else ''
                # AdapterRAM is a 32-bit field (caps at 4 GiB): only a lower bound.
                ram = item.get('AdapterRAM')
                found.append({'name': name, 'vendor': vendor, 'memory_bytes': int(ram) if ram else None,
                              'backend': 'Vulkan/DirectML' if vendor in ('AMD', 'Intel') else '', 'measured': False})
        except (ValueError, AttributeError, TypeError):
            pass
    return found


def hardware() -> dict:
    gpu_list = gpus()
    best = max((g for g in gpu_list if g.get('memory_bytes')), key=lambda g: g['memory_bytes'], default=None)
    try:
        free_disk = shutil.disk_usage(str(Path.home())).free
    except OSError:
        free_disk = None
    return {'os': os_label(), 'platform': platform.platform(), 'architecture': platform.machine(),
            'cpu': platform.processor() or platform.machine(), 'cpu_cores': os.cpu_count(),
            'ram_bytes': total_ram_bytes(), 'gpus': gpu_list,
            'gpu': (best or (gpu_list[0] if gpu_list else {})).get('name', 'none detected'),
            'gpu_memory_bytes': best['memory_bytes'] if best else None,
            'gpu_memory_measured': bool(best and best.get('measured')),
            'free_disk_bytes': free_disk}


# ----------------------------------------------------------------------- terminals
def write_terminal_script(folder: Path, name: str, env: dict, argv: list[str], banner: str) -> Path:
    """A small, visible script the user can read: sets env vars and runs argv."""
    folder.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        def q(s):
            return '"' + str(s).replace('"', '""') + '"'
        lines = ['@echo off', 'chcp 65001 >nul']
        lines += [f'set "{k}={v}"' for k, v in env.items()]
        def esc(text):           # cmd.exe metacharacters in echo text
            for ch in '^&|<>%':
                text = text.replace(ch, ('%%' if ch == '%' else '^' + ch))
            return text
        lines += [f'echo {esc(line)}' if line else 'echo.' for line in banner.splitlines()]
        lines += [' '.join(q(a) for a in argv), 'echo.', 'echo You can close this window now.', 'pause']
        target = folder / (name + '.cmd')
        target.write_text('\r\n'.join(lines) + '\r\n', encoding='utf8')
    else:
        import shlex
        lines = ['#!/bin/bash']
        lines += [f'export {k}={shlex.quote(str(v))}' for k, v in env.items()]
        lines += [f'echo {shlex.quote(line)}' for line in banner.splitlines()]
        lines += [' '.join(shlex.quote(str(a)) for a in argv),
                  "echo; read -r -p 'Done. Press Enter to close this window. ' _"]
        target = folder / (name + ('.command' if IS_MAC else '.sh'))
        target.write_text('\n'.join(lines) + '\n', encoding='utf8')
        target.chmod(0o700)
    return target


def terminal_command(script: Path) -> list[str] | None:
    """Command that opens ``script`` in a new visible terminal window."""
    if IS_WINDOWS:
        return ['startfile', str(script)]          # handled by open_terminal (os.startfile)
    if IS_MAC:
        return ['open', '-a', 'Terminal', str(script)]
    for term, args in (('x-terminal-emulator', ['-e']), ('gnome-terminal', ['--']), ('konsole', ['-e']),
                       ('xfce4-terminal', ['-x']), ('mate-terminal', ['-x']), ('tilix', ['-e']),
                       ('kitty', []), ('alacritty', ['-e']), ('xterm', ['-e'])):
        exe = shutil.which(term)
        if exe:
            return [exe, *args, 'bash', str(script)]
    return None


def open_terminal(script: Path) -> str:
    """Open the script in a terminal; return '' on success or the manual command."""
    cmd = terminal_command(script)
    if cmd is None:
        return f'bash {script}'
    try:
        if IS_WINDOWS:
            os.startfile(str(script))              # a .cmd opens in its own console window
        else:
            subprocess.Popen(cmd, cwd=str(script.parent), start_new_session=True)
        return ''
    except OSError:
        return str(script) if IS_WINDOWS else f'bash {script}'
