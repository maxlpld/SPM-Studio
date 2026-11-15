"""Physical ROI artifacts shared by the lattice and placement modules.

Coordinates are sample-local: +x right, +y up; raster row increases down.
The original acquisition file is always left untouched.
"""
from __future__ import annotations
import json
import math
import struct
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def rectangle_crop(data, geometry, roi=None):
    data=np.asarray(data)
    ny,nx=data.shape
    x0,y0,x1,y1=0,0,nx,ny
    if roi is not None:
        if roi.kind != 'rectangle':
            raise ValueError('Lattice crop must be a rectangle ROI')
        if len(roi.points_px)!=2:raise ValueError('A rectangle has two opposite corners')
        (a,b),(c,d)=roi.points_px
        x0=max(0,min(nx,int(math.floor(min(a,c)+.5))))
        x1=max(0,min(nx,int(math.ceil(max(a,c)+.5))))
        y0=max(0,min(ny,int(math.floor(min(b,d)+.5))))
        y1=max(0,min(ny,int(math.ceil(max(b,d)+.5))))
        if min(x1-x0,y1-y0)<32:
            raise ValueError('Selected region must contain at least 32 × 32 pixels')
    if geometry.size_m is None:
        raise ValueError('The scan has no calibrated physical X/Y dimensions')
    width_nm=geometry.size_m[0]*1e9*(x1-x0)/nx
    height_nm=geometry.size_m[1]*1e9*(y1-y0)/ny
    px_x=geometry.size_m[0]*1e9/nx
    px_y=geometry.size_m[1]*1e9/ny
    # Cropped image centre, measured relative to the original image centre.
    x_shift_nm=((x0+x1)/2/nx-0.5)*geometry.size_m[0]*1e9
    y_shift_nm=(0.5-(y0+y1)/2/ny)*geometry.size_m[1]*1e9
    angle=float(geometry.angle_deg or 0)
    theta=math.radians(angle)
    if geometry.center_m is not None:
        gx=geometry.center_m[0]*1e9+x_shift_nm*math.cos(theta)-y_shift_nm*math.sin(theta)
        gy=geometry.center_m[1]*1e9+x_shift_nm*math.sin(theta)+y_shift_nm*math.cos(theta)
        center_sample_nm=[gx,gy]
    else:center_sample_nm=None
    crop=data[y0:y1,x0:x1]
    meta={'pixel_bounds_xyxy':[x0,y0,x1,y1], 'shape_yx':list(crop.shape),
          'size_nm':[width_nm,height_nm], 'pixel_size_nm':[px_x,px_y],
          'center_local_nm':[x_shift_nm,y_shift_nm], 'center_sample_nm':center_sample_nm,
          'scan_angle_deg':angle, 'orientation':'stored array: x right, y down; local physical y up',
          'verified_orientation':bool(geometry.verified_orientation)}
    return crop,meta


def validate_artifact(path):
    path=Path(path).resolve()
    document=json.loads(path.read_text(encoding='utf8'))
    if document.get('schema_version')!=1 or document.get('kind')!='spm_studio_lattice_roi':
        raise ValueError('Not an SPM Studio calibrated lattice ROI manifest')
    for key in ('cropped_scan_npy','basis_local_nm','roi_geometry','source_scan'):
        if key not in document:raise ValueError(f'Lattice manifest is missing {key}')
    geom=document['roi_geometry']
    shape=geom['shape_yx'];size=geom['size_nm'];scale=geom['pixel_size_nm']
    if (len(shape)!=2 or len(size)!=2 or len(scale)!=2 or
        min(shape)<1 or min(size)<=0 or min(scale)<=0):
        raise ValueError('Invalid calibrated ROI dimensions')
    if not np.allclose([size[0]/shape[1],size[1]/shape[0]],scale,rtol=1e-9):
        raise ValueError('ROI pixel scale does not agree with dimensions')
    basis=np.asarray(document['basis_local_nm'],dtype=float)
    if basis.shape!=(2,2) or not np.all(np.isfinite(basis)) or abs(np.linalg.det(basis))<1e-8:
        raise ValueError('Lattice basis is invalid or singular')
    return path, document


def _object(type_name,fields):
    """Minimal Gwyddion GWYP object serializer, little-endian binary format."""
    body=bytearray()
    for name,kind,value in fields:
        body+=str(name).encode('utf-8')+b'\0'+kind.encode('ascii')
        if kind=='i':body+=struct.pack('<i',int(value))
        elif kind=='d':body+=struct.pack('<d',float(value))
        elif kind=='s':body+=str(value).encode('utf-8')+b'\0'
        elif kind=='o':body+=bytes(value)
        elif kind=='D':
            arr=np.asarray(value,dtype='<f8').ravel()
            body+=struct.pack('<I',arr.size)+arr.tobytes(order='C')
        else:raise ValueError(f'Unknown Gwyddion field type: {kind}')
    return type_name.encode('ascii')+b'\0'+struct.pack('<I',len(body))+body


def gwy_bytes(channels, roi_geometry, basis_local_nm=None, extra_metadata=None):
    """Write cropped numeric image data, and separate display-only annotation fields.

    Annotations are rasterized in independent channels; the source channel's
    measured values remain unchanged. The physical scale is metres in GWY.
    """
    sx,sy=np.asarray(roi_geometry['size_nm'],float)*1e-9
    xoff=yoff=0.0
    center=roi_geometry.get('center_sample_nm')
    if center is not None and not roi_geometry.get('scan_angle_deg'):
        xoff=center[0]*1e-9-sx/2
        yoff=center[1]*1e-9-sy/2
    fields=[]
    if extra_metadata is None:extra_metadata={}
    for i,(title,arr,unit) in enumerate(channels):
        data=np.asarray(arr)

        if data.ndim!=2:raise ValueError('GWY requires two-dimensional images')
        ny,nx=data.shape
        if [ny,nx]!=roi_geometry['shape_yx']:raise ValueError('GWY image shape does not match cropped geometry')
        finite=np.isfinite(data)
        if not finite.any():raise ValueError(f'No finite pixels in GWY channel {title}')
        # Gwyddion forbids NaN/Inf in stored doubles. Keep original NaNs in
        # cropped_scan.npy; the GWY replacement is accompanied by a native mask.
        if not finite.all():
            median=float(np.median(data[finite]))
            original_mask=(~finite).astype(float)
            data=np.where(finite,data,median)
        else:original_mask=None
        si_xy=_object('GwySIUnit',[('unitstr','s','m')])
        si_z=_object('GwySIUnit',[('unitstr','s',unit or '')])
        field=_object('GwyDataField',[
            ('xres','i',nx),('yres','i',ny),('xreal','d',sx),('yreal','d',sy),
            ('xoff','d',xoff),('yoff','d',yoff),
            ('si_unit_xy','o',si_xy),('si_unit_z','o',si_z),('data','D',data)])
        fields.extend([(f'/{i}/data','o',field),(f'/{i}/data/title','s',title)])
        if original_mask is not None:
            mask_field=_object('GwyDataField',[
                ('xres','i',nx),('yres','i',ny),('xreal','d',sx),('yreal','d',sy),
                ('xoff','d',xoff),('yoff','d',yoff),
                ('si_unit_xy','o',si_xy),('si_unit_z','o',_object('GwySIUnit',[('unitstr','s','')])),
                ('data','D',original_mask)])
            fields.append((f'/{i}/mask','o',mask_field))
        if extra_metadata:
            meta=_object('GwyContainer',[(str(k),'s',str(v)) for k,v in extra_metadata.items()])
            fields.append((f'/{i}/meta','o',meta))
    if basis_local_nm is not None:
        b=np.asarray(basis_local_nm,dtype=float)
        if b.shape!=(2,2):raise ValueError('Lattice selection must be a 2x2 vector matrix')
        # Gwyddion selections are physical line endpoints in metres. The
        # selection's y coordinates increase down in the stored raster.
        cx=xoff+sx/2;cy=yoff+sy/2
        lines=[]
        for v in b.T:
            lines.extend([cx,cy,cx+v[0]*1e-9,cy-v[1]*1e-9])
        selection=_object('GwySelectionLine',[('max','i',2),('data','D',lines)])
        fields.append(('/0/select/line','o',selection))
    # Store orientation as text; GwyDataField itself has no scan rotation metadata.
    fields.append(('/spm_studio/roi_metadata_json','s',json.dumps(roi_geometry)))
    return b'GWYP'+_object('GwyContainer',fields)


def write_gwy(path, channels, roi_geometry, basis_local_nm=None, extra_metadata=None):
    path=Path(path)
    path.write_bytes(gwy_bytes(channels,roi_geometry,basis_local_nm,extra_metadata))
    return path


def normalize_gray(arr):
    a=np.asarray(arr,dtype=float)
    valid=np.isfinite(a)
    if not np.any(valid):raise ValueError('No finite scan pixels in selected ROI')
    lo,hi=np.nanpercentile(a[valid],[2,98])
    if hi<=lo:hi=lo+max(abs(lo)*1e-9,1e-12)
    gray=np.where(valid,np.clip((a-lo)/(hi-lo)*255,0,255),0).astype('uint8')
    return Image.fromarray(gray,'L').convert('RGB')


def _annotation_font(size_px):
    """Use a real scalable glyph set (gamma/Angstrom), not PIL 10-px bitmap."""
    from PIL import ImageFont
    try:return ImageFont.truetype('DejaVuSans.ttf',int(size_px))
    except OSError:return ImageFont.load_default(size=int(size_px))


def _nice_length_nm(full_width_nm):
    """Match Studio's physical export rule: 1/2/5 step near 25% width."""
    length=float(full_width_nm)
    if not np.isfinite(length) or length<=0:return 0.
    target=length*.25
    exponent=int(math.floor(math.log10(target)))
    candidates=[base*10.**power for power in range(exponent-2,exponent+2)
                for base in (1.,2.,5.)]
    good=[x for x in candidates if 0<x<=length*.35]
    return min(good,key=lambda x:(abs(math.log(x/target)),-x)) if good else target


def _scale_bar(draw, shape, width_nm, *, fill='white'):
    """Same 1/2/5 convention as SPM Studio publication export, bottom right."""
    nx,ny=shape
    bar_nm=_nice_length_nm(width_nm)
    if bar_nm<=0:return
    width=max(2,round(nx*bar_nm/width_nm))
    x1=nx-round(.055*nx)
    x0=x1-width
    y=ny-round(.10*ny)
    tick=max(3,round(ny*.032))
    weight=max(2,round(nx*.0037))
    draw.line([(x0,y),(x1,y)],fill=fill,width=weight)
    for x in (x0,x1):draw.line([(x,y-tick//2),(x,y+tick//2)],fill=fill,width=weight)
    font=_annotation_font(max(12,round(min(nx,ny)*.035)))
    text=f'{bar_nm:g} nm' if bar_nm>=.001 else f'{bar_nm*1000:g} pm'
    w=draw.textbbox((0,0),text,font=font)[2]
    draw.text((int((x0+x1-w)/2),y+max(3,round(ny*.012))),text,fill=fill,font=font)


def lattice_draw(base,basis_local,geometry,*,origin_px=None,colors=('#16d8f5','#fbb748'),legend_corner='top_left'):
    """High-quality full-resolution overlay; no thick stroke/black text borders.

    Text uses a scalable font and the physical scale is derived from the same
    geometry as ordinary SPM export. If the image is oversampled, geometry's
    size_nm stays fixed while pixel_size_nm changes to maintain exact lengths.
    """
    canvas=base.convert('RGB').copy()
    draw=ImageDraw.Draw(canvas)
    nx=canvas.width;ny=canvas.height
    dx,dy=float(geometry['size_nm'][0])/nx,float(geometry['size_nm'][1])/ny
    if origin_px is None:origin_px=((nx-1)/2,(ny-1)/2)
    from PIL import ImageColor
    colors=tuple(ImageColor.getrgb(str(c)) for c in colors)
    if legend_corner not in ('top_left','top_right','bottom_left','bottom_right'):
        raise ValueError('Invalid vector legend corner')
    basis=np.asarray(basis_local,float)
    for i in range(2):
        vec=basis[:,i]
        endpoint=(origin_px[0]+vec[0]/dx,origin_px[1]-vec[1]/dy)
        draw.line([origin_px,endpoint],fill=colors[i],width=max(2,round(nx/280)))
        angle=math.atan2(endpoint[1]-origin_px[1],endpoint[0]-origin_px[0])
        length=max(8,min(28,max(nx,ny)/34))
        left=(endpoint[0]-length*math.cos(angle-0.42),endpoint[1]-length*math.sin(angle-0.42))
        right=(endpoint[0]-length*math.cos(angle+0.42),endpoint[1]-length*math.sin(angle+0.42))
        draw.polygon([endpoint,left,right],fill=colors[i])
    a,b=basis.T
    gamma=math.degrees(math.acos(np.clip(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)),-1,1)))
    # Only an arc between the vector arrows; gamma's numeric value is shown
    # once in the chosen corner legend. Construct it in physical coordinates,
    # not pixels, so non-square scanner pixels cannot distort the angle.
    theta_a=math.atan2(a[1],a[0]);theta_b=math.atan2(b[1],b[0])
    sweep=(theta_b-theta_a)%(2*math.pi)
    if sweep>math.pi:
        theta_a,theta_b=theta_b,theta_a
        sweep=2*math.pi-sweep
    radius_nm=.35*min(np.linalg.norm(a),np.linalg.norm(b))
    arc_points=[(origin_px[0]+radius_nm*math.cos(theta_a+sweep*i/40)/dx,
                 origin_px[1]-radius_nm*math.sin(theta_a+sweep*i/40)/dy)
                for i in range(41)]
    draw.line(arc_points,fill='white',width=max(2,round(nx/450)),joint='curve')
    lines=[(f'a = {np.linalg.norm(a)*10:.2f} Å',colors[0]),
           (f'b = {np.linalg.norm(b)*10:.2f} Å',colors[1]),
           (f'γ = {gamma:.1f}°','white')]
    font=_annotation_font(max(13,round(min(nx,ny)*.040)))
    pad=max(7,round(min(nx,ny)*.027))
    line_height=max(17,round(min(nx,ny)*.060))
    for i,(text,color) in enumerate(lines):
        box=draw.textbbox((0,0),text,font=font)
        tw=box[2]-box[0]
        xx=pad if legend_corner.endswith('left') else nx-pad-tw
        yy=pad+i*line_height if legend_corner.startswith('top') else ny-pad-(3-i)*line_height
        # No stroke_width and no dark outline: user-requested clean labels.
        draw.text((xx,yy),text,fill=color,font=font)
    _scale_bar(draw,(nx,ny),float(geometry['size_nm'][0]),fill='white')
    return canvas
