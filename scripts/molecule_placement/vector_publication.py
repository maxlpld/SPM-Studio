"""Molecule placement figure, drawn by the Export-panel renderer (v0.8).

The scan, colourbar, scale bar, page size and fonts come from
:mod:`spm_studio.core.script_figures`, i.e. exactly what *Export…* produces for
the same scan.  This module only adds the molecules (true vector objects when
the artwork is an SVG) and the lattice vectors on top of the image rectangle.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np


def raw_view(doc):
    if '_raw_view' in doc:
        return np.asarray(doc['_raw_view'])
    if doc.get('cropped_scan_npy') and Path(doc['cropped_scan_npy']).is_file():
        return np.load(doc['cropped_scan_npy'],mmap_mode='r')
    raise ValueError('Molecule placement requires the original cropped numeric scan; rerun Lattice measurements first')


def display_style_for(doc, plot_config=None):
    """Current viewer display of the lattice channel, else the one stored by the lattice run."""
    from spm_studio.core import script_figures as figures
    channel=str(doc.get('source_channel',''))
    if plot_config and figures._viewer_info(plot_config,channel):
        return figures.scan_display_style(plot_config,channel)
    return figures.style_from_dict(doc.get('display_style')) or figures.scan_display_style(plot_config or {},channel)


def molecule_decorator(doc, artwork_path, fallback_artwork, params, sites, angle_deg):
    """``draw(painter, image_rect)`` placing every molecule at its calibrated site."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    art_path=Path(str(artwork_path or ''))
    svg_art=None
    if art_path.suffix.lower()=='.svg' and not bool(params.get('remove_white_background',False)):
        svg_art=QSvgRenderer(str(art_path))
        if not svg_art.isValid():svg_art=None
    art=fallback_artwork.convert('RGBA')
    art_image=QImage(art.tobytes(),art.width,art.height,4*art.width,QImage.Format.Format_RGBA8888).copy()
    physical_width,physical_height=map(float,doc['roi_geometry']['size_nm'])
    box=[float(v) for v in (params.get('_artwork_content_box') or (0.,0.,1.,1.))]
    opacity=float(params.get('opacity',.9))

    def draw(painter, rect):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
        molecule_width=float(params['molecule_width_nm'])/physical_width*rect.width()
        molecule_height=float(params['molecule_height_nm'])/physical_height*rect.height()
        painter.save()
        painter.setClipRect(rect)
        painter.setOpacity(opacity)
        for cx,cy,_,_ in sites:
            x=rect.left()+(cx/physical_width+.5)*rect.width()
            y=rect.top()+(.5-cy/physical_height)*rect.height()
            painter.save();painter.translate(x,y);painter.rotate(-angle_deg)
            artwork_rect=QRectF(-molecule_width/2,-molecule_height/2,molecule_width,molecule_height)
            if svg_art is not None:
                # The nm size refers to the visible molecule: expand the SVG so its
                # trimmed content box lands exactly on artwork_rect.
                fx0,fy0,fx1,fy1=box
                full_w=molecule_width/max(1e-9,fx1-fx0);full_h=molecule_height/max(1e-9,fy1-fy0)
                painter.save();painter.setClipRect(artwork_rect)
                svg_art.render(painter,QRectF(-molecule_width/2-fx0*full_w,
                                              -molecule_height/2-fy0*full_h,full_w,full_h))
                painter.restore()
            else:
                painter.drawImage(artwork_rect,art_image)
            painter.restore()
        painter.restore()
    return draw


def export_placement(doc, artwork_path, fallback_artwork, params, sites, angle_deg,
                     output_dir, *, dpi=None, width_mm=None, plot_config=None, formats=('svg',),
                     scan_path=None, style=None):
    """Write ``lattice_plus_molecules.<fmt>`` exactly like an Export… of this scan."""
    from spm_studio.core import script_figures as figures
    from spm_studio.core.plot_settings import default_channel_title
    figures.ensure_qt_gui()
    raw=raw_view(doc)
    style=style or display_style_for(doc,plot_config)
    channel=str(doc.get('source_channel','Z'))
    decorate=molecule_decorator(doc,artwork_path,fallback_artwork,params,sites,angle_deg)
    lattice={k:doc[k] for k in ('basis_local_nm','gamma_deg','roi_geometry') if k in doc}
    lattice['vector_colors']=list(doc.get('vector_colors',('#16d8f5','#fbb748')))
    lattice['vector_legend_corner']=doc.get('vector_legend_corner','top_left')
    if not bool(params.get('show_lattice_vectors',True)):lattice=None
    title=str(doc.get('colorbar_title') or '') or figures.colorbar_title(plot_config or {},channel) or default_channel_title(channel)
    side=str(doc.get('colorbar_position','below') or 'below')
    show_bar=bool(doc.get('show_colorbar',True)) and side!='none'
    preset=None
    if dpi or width_mm:
        preset=figures.export_preset(plot_config)
        if dpi:preset['dpi']=int(dpi)
    return figures.export_scan_figure(Path(output_dir)/'lattice_plus_molecules',
        scan_path=scan_path or doc.get('source_scan',''),data=raw,size_nm=doc['roi_geometry']['size_nm'],
        channel=channel,unit=str(doc.get('source_unit','')),plot_config=plot_config or {'schema_version':1},
        formats=formats,style=style,lattice=lattice,decorate=decorate,
        colorbar_position=('below' if side=='none' else side),show_colorbar=show_bar,title=title,
        display_zero=bool(doc.get('colorbar_zero_reference',False)),preset=preset,
        transparent=bool(params.get('_transparent_background',False)) if '_transparent_background' in params else None)
