"""STEP (ISO 10303-21, AP214) writer for closed triangle meshes, as standard B-rep solids (Qt-free).

Each mesh becomes a MANIFOLD_SOLID_BREP made of ADVANCED_FACEs on PLANEs with shared EDGE_CURVEs/LINEs, the
form written by CAD programs and read by OpenCASCADE-based importers (Bambu Studio, Orca, PrusaSlicer,
FreeCAD…). Coplanar neighbouring triangles are merged into one planar face (with holes when needed), so flat
plates and text tops stay light.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from pathlib import Path

import numpy as np


def _planar_faces(verts, faces, tol=1e-6):
    """Group triangles into planar regions → list of (normal, point, loops) with loops of vertex indices."""
    v = np.asarray(verts, float)
    f = np.asarray(faces, np.int64)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    n = np.cross(b - a, c - a)
    length = np.linalg.norm(n, axis=1)
    keep = length > 1e-14
    f, n, a, length = f[keep], n[keep], a[keep], length[keep]
    n = n / length[:, None]
    d = np.einsum('ij,ij->i', n, a)
    key = np.column_stack([np.round(n / 1e-6), np.round(d / 1e-5)]).astype(np.int64)
    _u, group = np.unique(key, axis=0, return_inverse=True)
    group = group.ravel()
    # triangles sharing an edge and a plane belong to the same face
    parent = np.arange(len(f))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    owner = {}
    for t, tri in enumerate(f):
        for k in range(3):
            e = (min(tri[k], tri[(k + 1) % 3]), max(tri[k], tri[(k + 1) % 3]))
            other = owner.get(e)
            if other is None:
                owner[e] = t
            elif group[other] == group[t]:
                ra, rb = find(t), find(other)
                if ra != rb:
                    parent[ra] = rb
    regions = defaultdict(list)
    for t in range(len(f)):
        regions[find(t)].append(t)
    out = []
    for tris in regions.values():
        directed = set()
        for t in tris:
            tri = f[t]
            for k in range(3):
                directed.add((int(tri[k]), int(tri[(k + 1) % 3])))
        boundary = [e for e in directed if (e[1], e[0]) not in directed]
        nxt = defaultdict(list)
        for s, e in boundary:
            nxt[s].append(e)
        loops = []
        used = set()
        for s, e in boundary:
            if (s, e) in used:
                continue
            loop = [s]
            used.add((s, e))
            cur = e
            guard = 0
            while cur != s and guard <= len(boundary):
                loop.append(cur)
                options = [x for x in nxt[cur] if (cur, x) not in used]
                if not options:
                    break
                x = options[0]
                used.add((cur, x))
                cur = x
                guard += 1
            if cur == s and len(loop) >= 3:
                loops.append(loop)
        if loops:
            t0 = tris[0]
            out.append((n[t0], a[t0], loops))
    return out


def _loop_area(points, normal):
    p = np.asarray(points, float)
    return float(np.dot(np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0), normal)) / 2


def _fmt(x):
    s = f'{x:.6f}'.rstrip('0')
    return s + '0' if s.endswith('.') else s


def write_step_solids(path, solids, name='SPM Studio'):
    """solids: iterable of (label, verts, faces) closed meshes. Returns the path."""
    path = Path(path)
    lines = []
    count = [0]

    def add(text):
        count[0] += 1
        lines.append(f'#{count[0]}={text};')
        return count[0]
    label = str(name).replace("'", ' ')
    app = add("APPLICATION_CONTEXT('automotive design')")
    add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app})")
    pc = add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    pdc = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
    prod = add(f"PRODUCT('{label}','{label}','',(#{pc}))")
    add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(#{prod}))")
    pdf = add(f"PRODUCT_DEFINITION_FORMATION('','',#{prod})")
    pd = add(f"PRODUCT_DEFINITION('design','',#{pdf},#{pdc})")
    pds = add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
    length = add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
    angle = add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
    solid_angle = add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
    unc = add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),#{length},'distance_accuracy_value','')")
    ctx = add(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc}))"
              f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{length},#{angle},#{solid_angle}))REPRESENTATION_CONTEXT('',''))")
    origin = add("CARTESIAN_POINT('',(0.,0.,0.))")
    zdir = add("DIRECTION('',(0.,0.,1.))")
    xdir = add("DIRECTION('',(1.,0.,0.))")
    axis = add(f"AXIS2_PLACEMENT_3D('',#{origin},#{zdir},#{xdir})")
    breps = []
    for solid_label, verts, faces in solids:
        v = np.asarray(verts, float)
        vertex_ids = {}

        def vertex(i):
            ref = vertex_ids.get(i)
            if ref is None:
                x, y, z = v[i]
                p = add(f"CARTESIAN_POINT('',({_fmt(x)},{_fmt(y)},{_fmt(z)}))")
                ref = vertex_ids[i] = (add(f"VERTEX_POINT('',#{p})"), p)
            return ref
        edge_ids = {}

        def edge(i, j):
            k = (min(i, j), max(i, j))
            ref = edge_ids.get(k)
            if ref is None:
                (va, pa), (vb, _pb) = vertex(k[0]), vertex(k[1])
                d = v[k[1]] - v[k[0]]
                L = float(np.linalg.norm(d))
                u = d / L
                dr = add(f"DIRECTION('',({_fmt(u[0])},{_fmt(u[1])},{_fmt(u[2])}))")
                vec = add(f"VECTOR('',#{dr},{_fmt(L)})")
                line = add(f"LINE('',#{pa},#{vec})")
                ref = edge_ids[k] = add(f"EDGE_CURVE('',#{va},#{vb},#{line},.T.)")
            return ref, '.T.' if (i, j) == k else '.F.'
        face_ids = []
        for normal, point, loops in _planar_faces(v, faces):
            areas = [_loop_area(v[loop], normal) for loop in loops]
            outer = int(np.argmax(areas))
            bounds = []
            for li, loop in enumerate(loops):
                oriented = []
                for k in range(len(loop)):
                    e, sense = edge(loop[k], loop[(k + 1) % len(loop)])
                    oriented.append(add(f"ORIENTED_EDGE('',*,*,#{e},{sense})"))
                el = add("EDGE_LOOP('',(" + ','.join(f'#{o}' for o in oriented) + '))')
                kind = 'FACE_OUTER_BOUND' if li == outer else 'FACE_BOUND'
                bounds.append(add(f"{kind}('',#{el},.T.)"))
            ref = np.array([1.0, 0, 0]) if abs(normal[0]) < .9 else np.array([0, 1.0, 0])
            ref = ref - normal * np.dot(ref, normal)
            ref /= np.linalg.norm(ref)
            p0 = add(f"CARTESIAN_POINT('',({_fmt(point[0])},{_fmt(point[1])},{_fmt(point[2])}))")
            nz = add(f"DIRECTION('',({_fmt(normal[0])},{_fmt(normal[1])},{_fmt(normal[2])}))")
            nx = add(f"DIRECTION('',({_fmt(ref[0])},{_fmt(ref[1])},{_fmt(ref[2])}))")
            plane = add(f"PLANE('',#{add(f'AXIS2_PLACEMENT_3D({chr(39)}{chr(39)},#{p0},#{nz},#{nx})')})")
            face_ids.append(add("ADVANCED_FACE('',(" + ','.join(f'#{b}' for b in bounds) + f"),#{plane},.T.)"))
        shell = add("CLOSED_SHELL('',(" + ','.join(f'#{i}' for i in face_ids) + '))')
        breps.append(add(f"MANIFOLD_SOLID_BREP('{str(solid_label).replace(chr(39), ' ')}',#{shell})"))
    rep = add("ADVANCED_BREP_SHAPE_REPRESENTATION('',(" + ','.join(f'#{b}' for b in breps) +
              f",#{axis}),#{ctx})")
    add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rep})")
    stamp = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    header = ['ISO-10303-21;', 'HEADER;', "FILE_DESCRIPTION(('SPM Studio 3D print'),'2;1');",
              f"FILE_NAME('{path.name}','{stamp}',('SPM Studio'),(''),'SPM Studio','SPM Studio','');",
              "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));", 'ENDSEC;', 'DATA;']
    with path.open('w', encoding='ascii', newline='\n') as fh:
        fh.write('\n'.join(header) + '\n' + '\n'.join(lines) + '\nENDSEC;\nEND-ISO-10303-21;\n')
    return path


def check_step(text):
    """Structural check of a file written by write_step_solids → dict of counts (raises AssertionError)."""
    import re
    ents = {}
    for m in re.finditer(r'^#(\d+)=(.*);$', text, re.M):
        ents[int(m.group(1))] = m.group(2)
    refs = set(map(int, re.findall(r'#(\d+)', ''.join(ents.values()))))
    assert refs <= set(ents), 'undefined references'

    def args(i):
        return list(map(int, re.findall(r'#(\d+)', ents[i])))

    def point(i):
        nums = re.findall(r'\(([-0-9.E+]+),([-0-9.E+]+),([-0-9.E+]+)\)', ents[i])
        return np.array(list(map(float, nums[0])))
    solids = [i for i, e in ents.items() if e.startswith('MANIFOLD_SOLID_BREP(')]
    n_faces = 0
    for s in solids:
        use = defaultdict(list)
        shell = args(s)[0]
        for face in args(shell):
            assert ents[face].startswith('ADVANCED_FACE(')
            n_faces += 1
            fa = args(face)
            plane = fa[-1]
            ax = args(plane)[0]
            p0, nz, _nx = args(ax)
            origin = point(p0)
            normal = point(nz)
            for bound in fa[:-1]:
                loop = args(bound)[0]
                pts = []
                prev_end = None
                first_start = None
                for oe in args(loop):
                    e = args(oe)[0]
                    sense = ents[oe].rstrip(')').endswith('.T.')
                    va, vb, _line = args(e)
                    start, end = (va, vb) if sense else (vb, va)
                    use[e].append(sense)
                    if prev_end is not None:
                        assert start == prev_end, 'open edge loop'
                    else:
                        first_start = start
                    prev_end = end
                    pts.append(point(args(start)[0]))
                assert prev_end == first_start, 'edge loop not closed'
                for q in pts:
                    assert abs(np.dot(q - origin, normal)) < 1e-3, 'vertex off its plane'
        for e, senses in use.items():
            assert len(senses) == 2 and senses[0] != senses[1], 'edge not shared by exactly two faces'
    return {'solids': len(solids), 'faces': n_faces}
