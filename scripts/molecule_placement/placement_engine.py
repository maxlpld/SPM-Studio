"""Lattice-registered, calibrated molecule artwork placement (2-D geometry only)."""
from __future__ import annotations
from pathlib import Path
import math
import numpy as np
from PIL import Image
from lattice_artifacts import validate_artifact


def find_lattice_result(scan_path, explicit=''):
    """Resolve a user-selected manifest, or the latest analysis of this scan."""
    scan=Path(scan_path).resolve()
    if explicit and str(explicit).strip():
        path,doc=validate_artifact(explicit)
        sources=[Path(doc['source_scan']).resolve()]
        if doc.get('lattice_region_gwy'):sources.append(Path(doc['lattice_region_gwy']).resolve())
        if scan not in sources:
            raise ValueError('Selected lattice manifest was computed for a DIFFERENT scan. Choose the corresponding source scan.')
        return path,doc
    root=scan.parent/'SPM_Studio_Results'/scan.stem
    # Current Studio stores output under <scan>/Data/lattice_measurements_*/.
    # Older releases put those folders directly under <scan>; support both.
    candidates=(sorted([*root.glob('Data/lattice_measurements_*/lattice_result.json'),
                        *root.glob('*lattice_measurements*/lattice_result.json')],
                       key=lambda p:p.stat().st_mtime_ns,reverse=True)
                if root.exists() else [])
    # Support when the user opened the cropped GWY file itself.
    if not candidates and (scan.parent/'lattice_result.json').is_file():
        candidates=[scan.parent/'lattice_result.json']
    for candidate in candidates:
        try:
            path,doc=validate_artifact(candidate)
            sources=[Path(doc['source_scan']).resolve()]
            if doc.get('lattice_region_gwy'):sources.append(Path(doc['lattice_region_gwy']).resolve())
            if scan in sources:return path,doc
        except (ValueError,OSError,KeyError):pass
    raise FileNotFoundError('No calibrated lattice result for this scan. Run "Lattice measurements" (primitive_auto) first, then return here; or choose lattice_result.json in Tool settings.')



def _clamp_fraction(value):
    return max(0.0,min(1.0,float(value)))


def view_for_session_crop(doc, region):
    """Intersect saved lattice ROI with the *current original-scan crop*.

    The ROI is specified as fractions of the original acquisition raster by
    SPM Studio's CropRegion. The lattice manifest can refer to an earlier ROI,
    including one made *after* a previous Studio crop. Both windows are mapped
    into the same original scan reference coordinates before intersection.

    This is a view, not a resampling of the molecule. Molecule width/height and
    lattice basis stay in nm. The primitive lattice phase is shifted by the
    old ROI-centre minus the new ROI-centre in calibrated local nm.
    """
    if not region:
        return doc
    reference=region.get('reference_geometry') or {}
    target=[_clamp_fraction(region[k]) for k in ('left','top','right','bottom')]
    if target[2]<=target[0] or target[3]<=target[1]:
        raise ValueError('Invalid current scan crop region')
    geometry=doc['roi_geometry']
    roi_bounds=geometry.get('pixel_bounds_xyxy')
    source_geometry=doc.get('source_raster_geometry') or reference
    shape=source_geometry.get('shape',reference.get('shape'))
    if not roi_bounds or not shape or min(shape)<=0:
        raise ValueError('Cannot align old lattice ROI to a later crop: original raster geometry is missing; rerun Lattice measurements on this region.')
    ny,nx=map(int,shape)
    x0,y0,x1,y1=map(float,roi_bounds)
    input_window=[x0/nx,y0/ny,x1/nx,y1/ny]
    analysis_crop=doc.get('analysis_session_crop')
    if analysis_crop:
        prior=[_clamp_fraction(analysis_crop[k]) for k in ('left','top','right','bottom')]
        input_window=[prior[0]+input_window[0]*(prior[2]-prior[0]),
                      prior[1]+input_window[1]*(prior[3]-prior[1]),
                      prior[0]+input_window[2]*(prior[2]-prior[0]),
                      prior[1]+input_window[3]*(prior[3]-prior[1])]
    width=input_window[2]-input_window[0]
    height=input_window[3]-input_window[1]
    if width<=0 or height<=0:raise ValueError('Invalid lattice analysis ROI geometry')
    intersection=[max(input_window[0],target[0]),max(input_window[1],target[1]),
                  min(input_window[2],target[2]),min(input_window[3],target[3])]
    if intersection[2]<=intersection[0] or intersection[3]<=intersection[1]:
        raise ValueError('Current scan crop does not overlap the analyzed lattice region; rerun Lattice measurements on the new region.')
    raw=np.load(doc['cropped_scan_npy'],mmap_mode='r',allow_pickle=False)
    rows,cols=raw.shape
    col0=max(0,min(cols-1,round((intersection[0]-input_window[0])/width*cols)))
    col1=max(col0+1,min(cols,round((intersection[2]-input_window[0])/width*cols)))
    row0=max(0,min(rows-1,round((intersection[1]-input_window[1])/height*rows)))
    row1=max(row0+1,min(rows,round((intersection[3]-input_window[1])/height*rows)))
    if min(row1-row0,col1-col0)<2:
        raise ValueError('Crop overlaps fewer than two measured lattice pixels')
    # Cropped scientific pixels retain their original values and X/Y pitch.
    roi_w,roi_h=map(float,geometry['size_nm'])
    new_geo=dict(geometry)
    new_geo['shape_yx']=[row1-row0,col1-col0]
    new_geo['size_nm']=[roi_w*(col1-col0)/cols,roi_h*(row1-row0)/rows]
    new_geo['pixel_size_nm']=[roi_w/cols,roi_h/rows]
    centre_dx=((col0+col1)/(2*cols)-.5)*roi_w
    centre_dy=(.5-(row0+row1)/(2*rows))*roi_h
    new_geo['center_local_nm']=[float(geometry.get('center_local_nm',[0,0])[0]+centre_dx),
                                float(geometry.get('center_local_nm',[0,0])[1]+centre_dy)]
    if geometry.get('center_sample_nm') is not None:
        theta=math.radians(float(geometry.get('scan_angle_deg',0)))
        centre=geometry['center_sample_nm']
        new_geo['center_sample_nm']=[centre[0]+centre_dx*math.cos(theta)-centre_dy*math.sin(theta),
                                    centre[1]+centre_dx*math.sin(theta)+centre_dy*math.cos(theta)]
    result=dict(doc)
    result['roi_geometry']=new_geo
    result['_raw_view']=np.asarray(raw[row0:row1,col0:col1])
    result['_origin_shift_nm']=[-centre_dx,-centre_dy]
    result['_crop_pixel_window_xyxy']=[col0,row0,col1,row1]
    return result


def orientation_deg(basis,mode,offset):
    vec=np.asarray(basis,dtype=float)[:,0]
    angle=math.degrees(math.atan2(vec[1],vec[0]))
    if mode=='align_width_a':return angle+float(offset)
    if mode=='align_height_a':return angle-90.+float(offset)
    if mode=='manual':return float(offset)
    raise ValueError('Unknown molecule orientation mode')


def centers(basis,size_nm,origin_nm=(0,0),limit=1200):
    """All lattice sites within ROI plus a guard ring; translation is user editable."""
    b=np.asarray(basis,dtype=float)
    w,h=map(float,size_nm)
    origin=np.asarray(origin_nm,dtype=float)
    box=np.asarray([[-w/2,-h/2],[w/2,-h/2],[-w/2,h/2],[w/2,h/2]])-origin
    pairs=np.linalg.solve(b,box.T).T
    start=np.floor(pairs.min(axis=0)).astype(int)-2
    stop=np.ceil(pairs.max(axis=0)).astype(int)+2
    count=int(np.prod(stop-start+1))
    if count>max(2,int(limit))*8:
        raise ValueError(f'{count} possible lattice positions. Choose a smaller ROI or increase the placement limit.')
    sites=[]
    for i in range(start[0],stop[0]+1):
        for j in range(start[1],stop[1]+1):
            p=origin+b@np.array([i,j],dtype=float)
            if -w/2<=p[0]<=w/2 and -h/2<=p[1]<=h/2:
                sites.append((float(p[0]),float(p[1]),i,j))
    if len(sites)>limit:raise ValueError(f'{len(sites)} molecules requested; limit {limit}. Reduce ROI or increase limit.')
    return sites


def load_artwork(file_path,white_background=False,target_long_side=None):
    source=Path(file_path).expanduser()
    if not source.is_file():raise FileNotFoundError('Select a molecule SVG or PNG in Tool settings')
    if source.suffix.lower()=='.svg':
        # CairoSVG is excellent where available, but requires extra C libraries
        # on some Windows machines. QtSVG is already bundled with PySide6.
        try:
            import cairosvg
        except (ImportError, OSError):
            from io import BytesIO
            try:
                from PySide6.QtSvg import QSvgRenderer
                from PySide6.QtGui import QImage, QPainter
                from PySide6.QtCore import QSize
                renderer=QSvgRenderer(str(source))
                if not renderer.isValid():raise ValueError('Invalid molecule SVG')
                size=renderer.defaultSize()
                w,h=max(16,size.width()),max(16,size.height())
                ratio=(min(1.,2048/max(w,h)) if target_long_side is None
                       else min(2048/max(w,h),max(1.,target_long_side/max(w,h))))
                w,h=max(16,int(w*ratio)),max(16,int(h*ratio))
                frame=QImage(w,h,QImage.Format.Format_RGBA8888)
                frame.fill(0)
                painter=QPainter(frame)
                try:renderer.render(painter)
                finally:painter.end()
                im=Image.frombytes('RGBA',(w,h),bytes(frame.constBits()))
            except ImportError as exc:
                raise RuntimeError('SVG needs CairoSVG or PySide6 QtSvg') from exc
        else:
            from io import BytesIO
            im=Image.open(BytesIO(cairosvg.svg2png(url=str(source)))).convert('RGBA')
            if target_long_side and max(im.size)<target_long_side:
                scale=float(target_long_side)/max(im.size)
                im=Image.open(BytesIO(cairosvg.svg2png(url=str(source),scale=scale))).convert('RGBA')
    else:
        im=Image.open(source).convert('RGBA')
    if min(im.size)<2:raise ValueError('Molecule artwork is too small')
    if white_background:
        a=np.array(im,dtype=np.uint8)
        strength=np.min(a[:,:,:3],axis=2)
        a[:,:,3]=np.minimum(a[:,:,3],np.clip((255-strength).astype(float)*4,0,255).astype(np.uint8))
        im=Image.fromarray(a,'RGBA')
    return im


def artwork_content_box(im, *, white_tolerance=12, alpha_min=8):
    """Bounding box (x0,y0,x1,y1 in px) of the VISIBLE molecule in the artwork.

    Transparent pixels and (near-)white background pixels are treated as empty
    margin.  Returns the whole canvas when nothing is found.
    """
    a=np.asarray(im.convert('RGBA'))
    mask=(a[...,3]>alpha_min)&(a[...,:3].min(axis=2)<255-int(white_tolerance))
    if not mask.any():return (0,0,im.width,im.height)
    ys,xs=np.nonzero(mask)
    return (int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1)


def _truthy(value, default=True):
    if value is None or value=='':return default
    if isinstance(value,str):return value.strip().lower() in ('1','true','yes','on')
    return bool(value)


def prepare_artwork(file_path, params, target_long_side=None):
    """Load artwork and make molecule WIDTH/HEIGHT refer to the drawn molecule.

    v29 scale fix: previously the nm size was mapped onto the full artwork
    canvas, so empty margins (very common in ChemDraw/VESTA/PNG exports)
    shrank every placed molecule (≈2× for a molecule filling half the canvas).
    With ``trim_artwork_margins`` (default) the visible content box is used.
    A width or height of 0 keeps the artwork's own aspect ratio.
    Returns (image, info) and writes the resolved sizes back into ``params``.
    """
    white=_truthy(params.get('remove_white_background',False),False)
    im=load_artwork(file_path,white,target_long_side=target_long_side)
    full=im.size
    box=(0,0,im.width,im.height)
    if _truthy(params.get('trim_artwork_margins',True),True):
        box=artwork_content_box(im)
        if (box[2]-box[0])>=2 and (box[3]-box[1])>=2:
            im=im.crop(box)
        else:box=(0,0,full[0],full[1])
    fx=(box[0]/full[0],box[1]/full[1],box[2]/full[0],box[3]/full[1])
    w=float(params.get('molecule_width_nm',0) or 0)
    h=float(params.get('molecule_height_nm',0) or 0)
    if w<=0 and h<=0:raise ValueError('Give the molecule WIDTH and/or HEIGHT in nm (0 = from artwork aspect)')
    if h<=0:h=w*im.height/im.width
    if w<=0:w=h*im.width/im.height
    params['molecule_width_nm']=w;params['molecule_height_nm']=h
    params['_artwork_content_box']=list(fx)
    info={'artwork_canvas_px':list(full),'visible_molecule_px':[im.width,im.height],
          'content_box_px':list(box),'content_box_fraction':list(fx),
          'trimmed':box!=(0,0,full[0],full[1]),
          'nm_per_artwork_px':[w/im.width,h/im.height],
          'artwork_aspect_px':im.width/im.height,'requested_aspect_nm':w/h}
    return im,info


def _place_artwork(base,source,geometry,site,angle_deg,molecule_width_nm,molecule_height_nm,opacity):
    """Inverse physical affine warp; correct even when scan pixel X != pixel Y.

    The molecule PNG aspect ratio is not trusted: dimensions come from the
    user-provided real-space footprint and calibrated cropped scan metadata.
    """
    dx,dy=map(float,geometry['pixel_size_nm'])
    width_nm,height_nm=map(float,geometry['size_nm'])
    cx,cy=site
    theta=math.radians(float(angle_deg));cs=math.cos(theta);sn=math.sin(theta)
    radius=0.5*math.hypot(molecule_width_nm,molecule_height_nm)+max(dx,dy)*2
    ox=int(max(0,math.floor((cx-radius+width_nm/2)/dx)))
    ex=int(min(base.width,math.ceil((cx+radius+width_nm/2)/dx)))
    oy=int(max(0,math.floor((height_nm/2-cy-radius)/dy)))
    ey=int(min(base.height,math.ceil((height_nm/2-cy+radius)/dy)))
    if ex<=ox or ey<=oy:return
    # Pillow output pixel (i,j) to source pixel (u,v); x,y use nm.
    x0=(ox+0.5)*dx-width_nm/2-cx
    y0=height_nm/2-(oy+0.5)*dy-cy
    sw,sh=source.size
    a=sw/molecule_width_nm*cs*dx
    b=-sw/molecule_width_nm*sn*dy
    c=sw*(0.5+(cs*x0+sn*y0)/molecule_width_nm)
    d=sh/molecule_height_nm*sn*dx
    e=sh/molecule_height_nm*cs*dy
    f=sh*(0.5+(sn*x0-cs*y0)/molecule_height_nm)
    warped=source.transform((ex-ox,ey-oy),Image.Transform.AFFINE,(a,b,c,d,e,f),resample=Image.Resampling.BICUBIC)
    if opacity<1:
        alpha=warped.getchannel('A').point(lambda v:int(v*opacity))
        warped.putalpha(alpha)
    base.alpha_composite(warped,(ox,oy))


def _display_image(raw,doc,plot_config=None):
    """The scan as shown in the viewer (colormap + contrast), else 2–98 % gray."""
    from lattice_artifacts import normalize_gray
    try:
        from vector_publication import display_style_for
        from spm_studio.core.display import render_rgb
        style=display_style_for(doc,plot_config)
        return Image.fromarray(np.ascontiguousarray(render_rgb(np.asarray(raw),style)),'RGB')
    except Exception:
        return normalize_gray(raw)


def render_molecules(doc,artwork,params,max_preview_side=None,plot_config=None):
    geo=dict(doc['roi_geometry'])
    # Recreate the full-resolution scan + vectors from the original float data.
    # The old pipeline composited onto an 8-bit low-resolution lattice PNG and
    # saved its PDF at 150 dpi, producing blurred molecule strokes/text.
    from lattice_artifacts import normalize_gray,lattice_draw
    has_raw=('_raw_view' in doc or bool(doc.get('cropped_scan_npy') and Path(doc['cropped_scan_npy']).is_file()))
    if has_raw:
        raw=doc['_raw_view'] if '_raw_view' in doc else np.load(doc['cropped_scan_npy'],mmap_mode='r')
        original=_display_image(raw,doc,plot_config)
    else:
        # Old projects may have only the original lattice preview. Preserve
        # backward compatibility without assuming the raw NPY exists.
        if not doc.get('lattice_preview_png'):
            raise ValueError('The lattice result has no numeric scan; rerun Lattice measurements')
        original=Image.open(doc['lattice_preview_png']).convert('RGB')
    # Scale to 3x original sampling for sharp SVG placement and glyphs. The
    # measured scan pixels themselves are enlarged using NEAREST, not blurred.
    desired=max(original.size)*(3 if has_raw else 1)
    side=min(desired,4096)
    if max_preview_side is not None:side=min(side,int(max_preview_side))
    ratio=side/max(original.size)
    size=(max(1,round(original.width*ratio)),max(1,round(original.height*ratio)))
    scaled=original.resize(size,Image.Resampling.NEAREST) if size!=original.size else original
    if has_raw:
        base=lattice_draw(scaled,doc['basis_local_nm'],geo,
              colors=tuple(doc.get('vector_colors',('#16d8f5','#fbb748'))),
              legend_corner=doc.get('vector_legend_corner','top_left')).convert('RGBA')
    else:
        base=scaled.convert('RGBA')
    geo['shape_yx']=[base.height,base.width]
    geo['pixel_size_nm']=[geo['size_nm'][0]/base.width,geo['size_nm'][1]/base.height]
    width=float(params['molecule_width_nm']);height=float(params['molecule_height_nm'])
    if not (0<width<10000 and 0<height<10000):raise ValueError('Molecule width/height must be positive finite values in nm')
    angle=orientation_deg(doc['basis_local_nm'],params.get('orientation_mode','align_height_a'),params.get('rotation_offset_deg',0))
    # The user offset is defined relative to the ORIGINAL lattice ROI centre.
    # After a scan crop, translate that site origin to the new visible centre;
    # otherwise molecule registration would jump even though sizes remain nm.
    shift=doc.get('_origin_shift_nm',(0.,0.))
    origin=(float(params.get('origin_x_nm',0))+float(shift[0]),
            float(params.get('origin_y_nm',0))+float(shift[1]))
    sites=centers(doc['basis_local_nm'],geo['size_nm'],origin,limit=int(params.get('max_molecules',1200)))
    requested=int(params.get('molecule_count',0) or 0)
    if requested<0:
        raise ValueError('Number of molecules must be 0 (all) or positive')
    if requested:
        # Populate the closest sites to the chosen lattice origin first,
        # rather than picking an arbitrary first row of the scan.
        sites=sorted(sites,key=lambda s:(s[0]-origin[0])**2+(s[1]-origin[1])**2)[:requested]
    drawn_sites=sites
    if max_preview_side and len(sites)>260:
        drawn_sites=sites[::math.ceil(len(sites)/260)]
    for cx,cy,_,_ in drawn_sites:
        _place_artwork(base,artwork,geo,(cx,cy),angle,width,height,float(params.get('opacity',0.9)))
    return base,len(sites),angle,sites
