"""Bambu Studio project 3MF with an automatic colour gradient on the scan and its colour bar (Qt-free).

Written to the layout Bambu Studio itself uses (production-extension 3MF + ``Metadata/model_settings.config``
+ ``Metadata/project_settings.config``), following the Bambu Studio sources (``bbs_3mf.cpp``,
``PresetBundle::load_config_file_config``, ``FilamentMixer``):

* printer, process and filament presets are named by their Bambu system preset names; Bambu Studio fills every
  other setting from those system presets (only the keys listed in ``different_settings_to_system`` keep the
  values of the file), so the printer start G-code, temperatures, speeds… are Bambu's own;
* physical filaments: plate colour, text colour and the two colours of every channel (identical colours shared);
* one **mixed filament per channel** (Color Mixing, Gradient mode, 2 components: low colour → high colour,
  ``Mixed color sublayer`` on) assigned to that channel's relief + 3D colour bar. Bambu Studio's gradient runs
  over the layers where the mixed filament is printed, so the relief and its colour bar get the same colour
  at the same height — exactly the colour-bar scale;
* plate and labels (texts, ticks, scale bar) keep their own solid filaments.
"""
from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path

import numpy as np

BAMBU_APP_VERSION = '02.05.03.00'     # first Bambu Studio with Color Mixing (gradient mode)
FILAMENT_ID = 'GFA00'                 # Bambu PLA Basic
NOZZLES = ('0.2', '0.4', '0.6', '0.8')
DEFAULT_PRINTER = 'Bambu Lab X1 Carbon'

# Bambu Studio system presets per printer model and nozzle (resources/profiles/BBL, Bambu Studio 2.9):
# process preset, filament preset (Bambu PLA Basic); bed in mm; extruder types.
PRINTERS = {
    'Bambu Lab A1': {
        "bed": (256, 256), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL A1 0.2 nozzle', 'Bambu PLA Basic @BBL A1 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL A1', 'Bambu PLA Basic @BBL A1'),
            '0.6': ('0.30mm Strength @BBL A1 0.6 nozzle', 'Bambu PLA Basic @BBL A1'),
            '0.8': ('0.40mm Standard @BBL A1 0.8 nozzle', 'Bambu PLA Basic @BBL A1'),
        }},
    'Bambu Lab A1 mini': {
        "bed": (180, 180), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL A1M 0.2 nozzle', 'Bambu PLA Basic @BBL A1M 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL A1M', 'Bambu PLA Basic @BBL A1M'),
            '0.6': ('0.30mm Standard @BBL A1M 0.6 nozzle', 'Bambu PLA Basic @BBL A1M'),
            '0.8': ('0.40mm Standard @BBL A1M 0.8 nozzle', 'Bambu PLA Basic @BBL A1M'),
        }},
    'Bambu Lab A2L': {
        "bed": (330, 320), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL A2L 0.2 nozzle', 'Bambu PLA Basic @BBL A2L 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL A2L', 'Bambu PLA Basic @BBL A2L 0.4 nozzle'),
            '0.6': ('0.30mm Standard @BBL A2L 0.6 nozzle', 'Bambu PLA Basic @BBL A2L 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL A2L 0.8 nozzle', 'Bambu PLA Basic @BBL A2L 0.8 nozzle'),
        }},
    'Bambu Lab H2C': {
        "bed": (330, 320), "extruders": ('Direct Drive', 'Direct Drive'),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL H2C 0.2 nozzle', 'Bambu PLA Basic @BBL H2C 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL H2C', 'Bambu PLA Basic @BBL H2C'),
            '0.6': ('0.30mm Standard @BBL H2C 0.6 nozzle', 'Bambu PLA Basic @BBL H2C 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL H2C 0.8 nozzle', 'Bambu PLA Basic @BBL H2C 0.8 nozzle'),
        }},
    'Bambu Lab H2D': {
        "bed": (350, 320), "extruders": ('Direct Drive', 'Direct Drive'),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL H2D 0.2 nozzle', 'Bambu PLA Basic @BBL H2D 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL H2D', 'Bambu PLA Basic @BBL H2D'),
            '0.6': ('0.30mm Standard @BBL H2D 0.6 nozzle', 'Bambu PLA Basic @BBL H2D 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL H2D 0.8 nozzle', 'Bambu PLA Basic @BBL H2D 0.8 nozzle'),
        }},
    'Bambu Lab H2D Pro': {
        "bed": (350, 320), "extruders": ('Direct Drive', 'Direct Drive'),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL H2DP 0.2 nozzle', 'Bambu PLA Basic @BBL H2DP 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL H2DP', 'Bambu PLA Basic @BBL H2DP'),
            '0.6': ('0.30mm Standard @BBL H2DP 0.6 nozzle', 'Bambu PLA Basic @BBL H2DP 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL H2DP 0.8 nozzle', 'Bambu PLA Basic @BBL H2DP 0.8 nozzle'),
        }},
    'Bambu Lab H2S': {
        "bed": (340, 320), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL H2S 0.2 nozzle', 'Bambu PLA Basic @BBL H2S 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL H2S', 'Bambu PLA Basic @BBL H2S'),
            '0.6': ('0.30mm Standard @BBL H2S 0.6 nozzle', 'Bambu PLA Basic @BBL H2S 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL H2S 0.8 nozzle', 'Bambu PLA Basic @BBL H2S 0.8 nozzle'),
        }},
    'Bambu Lab H3C': {
        "bed": (330, 320), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL H3C 0.2 nozzle', 'Bambu PLA Basic @BBL H3C 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL H3C', 'Bambu PLA Basic @BBL H3C'),
            '0.6': ('0.30mm Standard @BBL H3C 0.6 nozzle', 'Bambu PLA Basic @BBL H3C 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL H3C 0.8 nozzle', 'Bambu PLA Basic @BBL H3C 0.8 nozzle'),
        }},
    'Bambu Lab P1P': {
        "bed": (256, 256), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL P1P 0.2 nozzle', 'Bambu PLA Basic @BBL P1P 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL P1P', 'Bambu PLA Basic @BBL P1P'),
            '0.6': ('0.30mm Standard @BBL P1P 0.6 nozzle', 'Bambu PLA Basic @BBL P1P 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL P1P 0.8 nozzle', 'Bambu PLA Basic @BBL P1P'),
        }},
    'Bambu Lab P1S': {
        "bed": (256, 256), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL X1C 0.2 nozzle', 'Bambu PLA Basic @BBL X1C 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL X1C', 'Bambu PLA Basic @BBL P1S 0.4 nozzle'),
            '0.6': ('0.30mm Standard @BBL X1C 0.6 nozzle', 'Bambu PLA Basic @BBL P1S 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL X1C 0.8 nozzle', 'Bambu PLA Basic @BBL X1C 0.8 nozzle'),
        }},
    'Bambu Lab P2S': {
        "bed": (256, 256), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL P2S 0.2 nozzle', 'Bambu PLA Basic @BBL P2S 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL P2S', 'Bambu PLA Basic @BBL P2S'),
            '0.6': ('0.30mm Standard @BBL P2S 0.6 nozzle', 'Bambu PLA Basic @BBL P2S 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL P2S 0.8 nozzle', 'Bambu PLA Basic @BBL P2S 0.8 nozzle'),
        }},
    'Bambu Lab X1': {
        "bed": (256, 256), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL X1C 0.2 nozzle', 'Bambu PLA Basic @BBL X1C 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL X1C', 'Bambu PLA Basic @BBL X1'),
            '0.6': ('0.30mm Standard @BBL X1 0.6 nozzle', 'Bambu PLA Basic @BBL X1'),
            '0.8': ('0.40mm Standard @BBL X1 0.8 nozzle', 'Bambu PLA Basic @BBL X1'),
        }},
    'Bambu Lab X1 Carbon': {
        "bed": (256, 256), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL X1C 0.2 nozzle', 'Bambu PLA Basic @BBL X1C 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL X1C', 'Bambu PLA Basic @BBL X1C'),
            '0.6': ('0.30mm Standard @BBL X1C 0.6 nozzle', 'Bambu PLA Basic @BBL X1C 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL X1C 0.8 nozzle', 'Bambu PLA Basic @BBL X1C 0.8 nozzle'),
        }},
    'Bambu Lab X1E': {
        "bed": (256, 256), "extruders": ('Direct Drive',),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL X1C 0.2 nozzle', 'Bambu PLA Basic @BBL X1C 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL X1C', 'Bambu PLA Basic @BBL X1C'),
            '0.6': ('0.30mm Standard @BBL X1C 0.6 nozzle', 'Bambu PLA Basic @BBL X1C'),
            '0.8': ('0.40mm Standard @BBL X1C 0.8 nozzle', 'Bambu PLA Basic @BBL X1C 0.8 nozzle'),
        }},
    'Bambu Lab X2D': {
        "bed": (256, 256), "extruders": ('Direct Drive', 'Bowden'),
        "nozzles": {
            '0.2': ('0.10mm Standard @BBL X2D 0.2 nozzle', 'Bambu PLA Basic @BBL X2D 0.2 nozzle'),
            '0.4': ('0.20mm Standard @BBL X2D', 'Bambu PLA Basic @BBL X2D 0.4 nozzle'),
            '0.6': ('0.30mm Standard @BBL X2D 0.6 nozzle', 'Bambu PLA Basic @BBL X2D 0.6 nozzle'),
            '0.8': ('0.40mm Standard @BBL X2D 0.8 nozzle', 'Bambu PLA Basic @BBL X2D 0.8 nozzle'),
        }},
}


def printer_names():
    return list(PRINTERS)


def preset_names(printer, nozzle):
    info = PRINTERS.get(printer)
    if info is None:
        raise ValueError(f'Unknown Bambu Lab printer {printer!r}')
    key = f'{float(nozzle):.1f}'
    if key not in info['nozzles']:
        raise ValueError(f'{printer}: no {key} mm nozzle profile')
    process, filament = info['nozzles'][key]
    return {'printer': f'{printer} {key} nozzle', 'process': process, 'filament': filament, 'nozzle': key,
            'model': printer, 'bed': info['bed'], 'extruders': info['extruders']}


def _hex(color):
    c = str(color).strip().upper()
    if not c.startswith('#'):
        c = '#' + c
    if len(c) == 4:
        c = '#' + ''.join(ch * 2 for ch in c[1:])
    return c[:7]


def blend(a, b, t=.5):
    pa = np.array([int(_hex(a)[i:i + 2], 16) for i in (1, 3, 5)], float)
    pb = np.array([int(_hex(b)[i:i + 2], 16) for i in (1, 3, 5)], float)
    c = np.clip(np.rint(pa * (1 - t) + pb * t), 0, 255).astype(int)
    return '#%02X%02X%02X' % tuple(c)


def filament_plan(plate, gradient=True):
    """Physical colours, mixed filaments and the filament (1-based slot) of every 3MF part."""
    physical = []

    def slot(color):
        c = _hex(color)
        if c not in physical:
            physical.append(c)
        return physical.index(c) + 1
    parts = {}
    background = slot(plate.params.get('background_color', '#FFFFFF'))
    text = slot(plate.params.get('text_color', '#000000'))
    mixed = []
    pending = []
    for name, bodies in plate.parts().items():
        if name == 'Plate':
            parts[name] = background
        elif name == 'Labels':
            parts[name] = text
        else:
            info = next((p for p in plate.panels if p['part'] == name), None)
            colors = info['colors'] if info else (bodies[0].color, bodies[0].color)
            lo, hi = slot(colors[0]), slot(colors[1])
            if gradient and lo != hi:
                pending.append((name, lo, hi))
            else:
                parts[name] = lo
    for name, lo, hi in pending:          # mixed slots come after every physical filament (Bambu's order)
        mixed.append({'part': name, 'components': (lo, hi), 'colour': blend(physical[lo - 1], physical[hi - 1])})
        parts[name] = len(physical) + len(mixed)
    return physical, mixed, parts


def project_config(names, physical, mixed):
    n_phys, n = len(physical), len(physical) + len(mixed)
    heads = len(names['extruders'])
    colours = list(physical) + [m['colour'] for m in mixed]
    flush = []
    for _h in range(heads):
        for i in range(n):
            for j in range(n):
                flush.append('0' if i == j else '280')
    filament_presets = [names['filament']] * n
    cfg = {
        'name': 'project_settings', 'from': 'project', 'version': BAMBU_APP_VERSION,
        'printer_settings_id': names['printer'], 'print_settings_id': names['process'],
        'filament_settings_id': filament_presets, 'printer_model': names['model'],
        'nozzle_diameter': [names['nozzle']] * heads, 'extruder_type': list(names['extruders']),
        'filament_colour': colours, 'filament_multi_colour': colours, 'filament_colour_type': ['1'] * n,
        'filament_ids': [FILAMENT_ID] * n, 'filament_type': ['PLA'] * n,
        'filament_self_index': [str(i + 1) for i in range(n)],
        'filament_extruder_variant': ['Direct Drive Standard'] * n,
        'filament_map': ['1'] * n, 'flush_volumes_matrix': flush, 'flush_volumes_vector': ['140'] * (2 * n),
        'flush_multiplier': ['1'] * heads,
        'filament_is_mixed': ['0'] * n_phys + ['1'] * len(mixed),
        'filament_mixed_components': [''] * n_phys + [f"{m['components'][0]},{m['components'][1]}" for m in mixed],
        'filament_mixed_sublayer_ratios': [''] * n_phys + ['0.5000,0.5000'] * len(mixed),
        'filament_mixed_gradient': ['0'] * n_phys + ['1'] * len(mixed),
        # first component (= low colour) from 90 % at the bottom to 10 % at the top (Bambu's "down" direction)
        'filament_mixed_gradient_range': [''] * n_phys + ['0.9000,0.1000'] * len(mixed),
        'filament_mixed_gradient_curve': [''] * n,
        'filament_mixed_gradient_per_part': ['0'] * n,
        'enable_mixed_color_sublayer': '1' if mixed else '0',
        # keys kept from this file; everything else comes from the Bambu system presets named above
        'different_settings_to_system': (['enable_mixed_color_sublayer'] if mixed else ['']) + [''] * (n + 1),
        'inherits_group': [''] * (n + 2),
    }
    return cfg


def _xml(text):
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def write_bambu_3mf(path, plate, printer=DEFAULT_PRINTER, nozzle=0.4, gradient=True, name='SPM Studio plate'):
    """Write the Bambu Studio project; returns (path, notes)."""
    from .print3d_plate import gradient_recipe, merged
    path = Path(path)
    names = preset_names(printer, nozzle)
    physical, mixed, part_slot = filament_plan(plate, gradient)
    notes = []
    W, H = plate.size_mm
    bw, bh = names['bed']
    if W > bw or H > bh:
        notes.append(f'The plate ({W:.0f} × {H:.0f} mm) is larger than the {printer} bed ({bw} × {bh} mm)')
    if len(physical) > 4:
        notes.append(f'{len(physical)} different filaments: more than one AMS unit of 4 slots is needed '
                     '(or use the same colour for several items)')
    parts = plate.parts()
    part_names = list(parts)
    uuids = {}

    def obj_uuid(i):
        return uuids.setdefault(i, str(uuid.uuid4()))
    sub = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
           ' xmlns:BambuStudio="http://schemas.bambulab.com/package/2021"'
           ' xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">',
           '<metadata name="BambuStudio:3mfVersion">1</metadata>', '<resources>']
    for i, part in enumerate(part_names):
        verts, faces = merged(parts[part])
        sub.append(f'<object id="{i + 1}" p:uuid="{obj_uuid(i + 1)}" type="model"><mesh><vertices>')
        sub.extend(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
        sub.append('</vertices><triangles>')
        sub.extend(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
        sub.append('</triangles></mesh></object>')
    sub += ['</resources>', '<build/>', '</model>']
    assembly = len(part_names) + 1
    tx, ty = (bw - W) / 2, (bh - H) / 2
    main = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
            ' xmlns:BambuStudio="http://schemas.bambulab.com/package/2021"'
            ' xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">',
            # Bambu Studio reads the project settings (presets, mixed filaments) only from files whose
            # generator is BambuStudio; the version is the first one with Color Mixing.
            f'<metadata name="Application">BambuStudio-{BAMBU_APP_VERSION}</metadata>',
            '<metadata name="BambuStudio:3mfVersion">1</metadata>',
            f'<metadata name="Title">{_xml(name)}</metadata>',
            '<metadata name="Description">SPM Studio 3D print plate</metadata>',
            '<metadata name="Designer">SPM Studio</metadata>',
            '<resources>',
            f'<object id="{assembly}" p:uuid="{obj_uuid(assembly)}" type="model"><components>']
    main += [f'<component p:path="/3D/Objects/object_1.model" objectid="{i + 1}" p:uuid="{obj_uuid(100 + i)}"'
             ' transform="1 0 0 0 1 0 0 0 1 0 0 0"/>' for i in range(len(part_names))]
    main += ['</components></object>', '</resources>',
             f'<build p:uuid="{uuid.uuid4()}"><item objectid="{assembly}" p:uuid="{obj_uuid(200)}" '
             f'transform="1 0 0 0 1 0 0 0 1 {tx:.4f} {ty:.4f} 0" printable="1"/></build>', '</model>']
    identity = '1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1'
    settings = ['<?xml version="1.0" encoding="UTF-8"?>', '<config>', f'  <object id="{assembly}">',
                f'    <metadata key="name" value="{_xml(name)}"/>',
                f'    <metadata key="extruder" value="{part_slot.get("Plate", 1)}"/>']
    for i, part in enumerate(part_names):
        faces = sum(len(b.faces) for b in parts[part])
        settings += [f'    <part id="{i + 1}" subtype="normal_part">',
                     f'      <metadata key="name" value="{_xml(part)}"/>',
                     f'      <metadata key="matrix" value="{identity}"/>',
                     f'      <metadata key="extruder" value="{part_slot[part]}"/>',
                     f'      <mesh_stat face_count="{faces}" edges_fixed="0" degenerate_facets="0" facets_removed="0"'
                     ' facets_reversed="0" backwards_edges="0"/>', '    </part>']
    settings += ['  </object>', '  <plate>', '    <metadata key="plater_id" value="1"/>',
                 '    <metadata key="plater_name" value=""/>', '    <metadata key="locked" value="false"/>',
                 '    <model_instance>', f'      <metadata key="object_id" value="{assembly}"/>',
                 '      <metadata key="instance_id" value="0"/>', '      <metadata key="identify_id" value="101"/>',
                 '    </model_instance>', '  </plate>', '  <assemble>',
                 f'   <assemble_item object_id="{assembly}" instance_id="0" '
                 f'transform="1 0 0 0 1 0 0 0 1 {tx:.4f} {ty:.4f} 0" offset="0 0 0" />', '  </assemble>', '</config>']
    cfg = project_config(names, physical, mixed)
    recipe = gradient_recipe(plate)
    recipe['bambu'] = {'printer': names['printer'], 'process': names['process'], 'filament': names['filament'],
                       'physical_filaments': physical, 'mixed_filaments': mixed, 'part_filament': part_slot}
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                     '<Default Extension="png" ContentType="image/png"/>'
                     '<Default Extension="gcode" ContentType="text/x.gcode"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>')
    model_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                  ' <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" '
                  'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>')
    tmp = path.with_suffix('.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('3D/3dmodel.model', '\n'.join(main))
        zf.writestr('3D/_rels/3dmodel.model.rels', model_rels)
        zf.writestr('3D/Objects/object_1.model', '\n'.join(sub))
        zf.writestr('Metadata/model_settings.config', '\n'.join(settings))
        zf.writestr('Metadata/project_settings.config', json.dumps(cfg, indent=4))
        zf.writestr('Metadata/spm_studio_gradients.json', json.dumps(recipe, indent=1, ensure_ascii=False))
    tmp.replace(path)
    if mixed:
        notes.append(f'Bambu Studio project for {names["printer"]}: {len(physical)} filaments + {len(mixed)} '
                     'gradient mixed filament(s), already assigned to the scan and colour-bar parts '
                     '(open it as a project in Bambu Studio ≥ 2.5.3, then match the filaments to your AMS)')
        notes.append('Bambu Studio draws a mixed filament in one blended colour in the Prepare view: the gradient '
                     'is computed when slicing and shows in the Preview tab (keep Process › Mixed color sublayer on)')
    else:
        notes.append(f'Bambu Studio project for {names["printer"]}: {len(physical)} filaments assigned to the parts')
    return path, notes
