"""Studio module for the unchanged SPM MultiFrame 0.1.2 science engines."""
from legacy_engine import run_original

def run(ctx):
    p=ctx.parameters
    channels=[s.strip() for s in p['stack_channels'].split(',') if s.strip()]
    return run_original(
        ctx, estimate_drift=p['estimate_drift'],stack=p['stack_frames'],
        registration_channel=ctx.channel,stack_channels=channels or [ctx.channel],
        trace=p['trace_direction'], excludes=p['exclude_filenames'],
        method=p['combination_method'],drift_bootstrap=p['drift_bootstrap'],
        lattice_bootstrap=p['lattice_bootstrap'],
        atom_tracking_path=p['atom_tracking_path'],
        atom_vx=(p['atom_vx'] if p['use_manual_atom_velocity'] else None),
        atom_vy=(p['atom_vy'] if p['use_manual_atom_velocity'] else None),
        atom_units=p['atom_velocity_unit'],atom_convention=p['atom_velocity_convention'])
