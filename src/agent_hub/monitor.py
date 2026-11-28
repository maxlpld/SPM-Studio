"""Local inference monitoring (Qt-free collectors). Values are measured or absent — never invented.

``sample()`` returns one reading; a key is missing when this computer does not expose it (no NVIDIA tool,
no readable sensor, unsupported OS). Sources, all unprivileged:

* CPU %, RAM: ``psutil`` when installed, else ``/proc/stat`` and ``/proc/meminfo`` (Linux); host-wide.
* CPU temperature: ``psutil.sensors_temperatures`` or ``/sys/class/thermal`` (Linux, when readable).
* NVIDIA GPU: ``nvidia-smi --query-gpu`` (utilization, memory used/total, temperature, power).
* AMD GPU (Linux): ``/sys/class/drm/card*/device/gpu_busy_percent`` and ``mem_info_vram_*``.
* Apple Silicon / Intel: unified or integrated memory — GPU metrics are not readable without elevated
  privileges, so they are reported as unavailable.
* Ollama: ``/api/ps`` (loaded models, memory in VRAM). Tokens/s and time to first token come from Ollama's own
  counters of the last reply (see ``agents.ollama.chat``), not from this sampler.

Nothing is sent anywhere; the sampler runs off the GUI thread at ~1 Hz only while the strip is visible.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_prev_cpu = None


def _cpu_percent_proc() -> float | None:
    global _prev_cpu
    try:
        with open('/proc/stat', encoding='utf8') as f:
            parts = [int(x) for x in f.readline().split()[1:8]]
    except (OSError, ValueError):
        return None
    idle, total = parts[3] + parts[4], sum(parts)
    prev, _prev_cpu = _prev_cpu, (idle, total)
    if prev is None or total == prev[1]:
        return None
    return round(100.0 * (1 - (idle - prev[0]) / (total - prev[1])), 1)


def _ram_proc() -> tuple[int, int] | None:
    try:
        info = {}
        with open('/proc/meminfo', encoding='utf8') as f:
            for line in f:
                k, v = line.split(':', 1)
                info[k] = int(v.split()[0]) * 1024
        return info['MemTotal'] - info.get('MemAvailable', info.get('MemFree', 0)), info['MemTotal']
    except (OSError, ValueError, KeyError):
        return None


def _cpu_temp() -> float | None:
    try:
        import psutil
        temps = psutil.sensors_temperatures() or {}
        for name in ('coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'acpitz'):
            if temps.get(name):
                return round(max(t.current for t in temps[name]), 1)
    except Exception:
        pass
    if sys.platform.startswith('linux'):
        best = None
        for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
            try:
                kind = (zone / 'type').read_text().strip().lower()
                if not any(w in kind for w in ('x86_pkg', 'cpu', 'soc', 'k10', 'acpitz')):
                    continue
                value = int((zone / 'temp').read_text().strip()) / 1000
                best = value if best is None else max(best, value)
            except (OSError, ValueError):
                continue
        return round(best, 1) if best is not None else None
    return None


def _nvidia() -> list[dict]:
    smi = shutil.which('nvidia-smi')
    if not smi:
        return []
    try:
        r = subprocess.run([smi, '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw',
                            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3,
                           **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in r.stdout.splitlines():
        p = [x.strip() for x in line.split(',')]
        if len(p) < 6:
            continue

        def num(x):
            try:
                return float(x)
            except ValueError:
                return None                      # "[N/A]" → unavailable
        out.append({'name': p[0], 'vendor': 'NVIDIA', 'util': num(p[1]),
                    'vram_used': int(num(p[2]) * 2 ** 20) if num(p[2]) is not None else None,
                    'vram_total': int(num(p[3]) * 2 ** 20) if num(p[3]) is not None else None,
                    'temp': num(p[4]), 'power_w': num(p[5])})
    return out


def _amd() -> list[dict]:
    out = []
    if not sys.platform.startswith('linux'):
        return out
    for dev in sorted(Path('/sys/class/drm').glob('card[0-9]/device')):
        busy = dev / 'gpu_busy_percent'
        if not busy.exists():
            continue
        try:
            gpu = {'name': dev.parent.name, 'vendor': 'AMD', 'util': float(busy.read_text().strip())}
            used, total = dev / 'mem_info_vram_used', dev / 'mem_info_vram_total'
            if used.exists() and total.exists():
                gpu['vram_used'], gpu['vram_total'] = int(used.read_text()), int(total.read_text())
            hw = next(dev.glob('hwmon/hwmon*/temp1_input'), None)
            if hw is not None:
                gpu['temp'] = int(hw.read_text()) / 1000
            out.append(gpu)
        except (OSError, ValueError):
            continue
    return out


def sample(ollama_base: str | None = 'http://127.0.0.1:11434') -> dict:
    s = {'ts': time.time(), 'scope': 'host-wide (this computer)'}
    try:
        import psutil
        s['cpu'] = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        s['ram_used'], s['ram_total'] = int(vm.total - vm.available), int(vm.total)
    except Exception:
        cpu = _cpu_percent_proc()
        if cpu is not None:
            s['cpu'] = cpu
        ram = _ram_proc()
        if ram:
            s['ram_used'], s['ram_total'] = ram
    t = _cpu_temp()
    if t is not None:
        s['cpu_temp'] = t
    gpus = _nvidia() or _amd()
    if gpus:
        s['gpus'] = gpus
    elif sys.platform == 'darwin':
        s['gpu_note'] = 'Apple GPU metrics need elevated privileges — not shown'
    if ollama_base:
        from .agents import ollama
        models = ollama.loaded(ollama_base, timeout=0.8)
        if models:
            s['loaded'] = [{'name': m.get('name', ''), 'size': m.get('size'), 'size_vram': m.get('size_vram')}
                           for m in models]
    return s
