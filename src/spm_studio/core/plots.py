"""Shared Matplotlib output formatting, lazy-loaded in the module subprocess."""
from contextlib import contextmanager
from .plot_settings import validate_plot, DEFAULT_PLOT, display_cmap

@contextmanager
def plot_style(preset=None):
    import matplotlib
    matplotlib.use('Agg',force=True)
    import matplotlib.pyplot as plt
    p=validate_plot(preset or DEFAULT_PLOT)
    rc={
      'font.family':p['font_family'],'font.size':p['font_size'],
      'axes.labelsize':p['label_size'],'axes.titlesize':p['title_size'],
      'xtick.labelsize':p['tick_size'],'ytick.labelsize':p['tick_size'],
      'legend.fontsize':p['legend_size'],
      'lines.linewidth':p['line_width'],'lines.markersize':p['marker_size'],
      'axes.grid':p['grid'],'savefig.dpi':p['dpi'],
      'savefig.facecolor':p['background'], 'figure.facecolor':p['background'],
      'axes.facecolor':p['background'],'pdf.fonttype':42,'svg.fonttype':'none',
      'image.interpolation':p['image_interpolation'],
      # v29 journal convention (Nature-style figures): closed frame, inward ticks
      # on all four sides, minor ticks, frameless legends.
      'axes.linewidth':0.9,'axes.edgecolor':'black',
      'xtick.direction':'in','ytick.direction':'in',
      'xtick.top':bool(p['journal_frame']),'ytick.right':bool(p['journal_frame']),
      'xtick.minor.visible':bool(p['journal_frame']),'ytick.minor.visible':bool(p['journal_frame']),
      'xtick.major.size':4.0,'ytick.major.size':4.0,'xtick.minor.size':2.2,'ytick.minor.size':2.2,
      'xtick.major.width':0.8,'ytick.major.width':0.8,'xtick.minor.width':0.6,'ytick.minor.width':0.6,
      'legend.frameon':False,'savefig.bbox':'tight','savefig.pad_inches':0.01,
      'figure.dpi':110,
    }
    with plt.rc_context(rc):
        yield plt


def style_axes(fig,preset):
    from matplotlib.ticker import MaxNLocator,ScalarFormatter, FixedLocator
    p=validate_plot(preset or DEFAULT_PLOT)
    for ax in fig.axes:
        if not hasattr(ax,'spines') or _is_colorbar_axes(ax):continue
        if p['journal_frame']:
            for spine in ax.spines.values():
                spine.set_visible(True);spine.set_color('black');spine.set_linewidth(0.9)
        else:
            for name,spine in ax.spines.items():
                spine.set_visible(name in p['axes_spines'])
        ax.grid(p['grid'])
        for axis in (ax.xaxis,ax.yaxis):
            if not isinstance(axis.get_major_locator(), FixedLocator):
                axis.set_major_locator(MaxNLocator(nbins=p['max_ticks']))
            if p['scientific_notation'] and axis.get_scale()=='linear':
                fmt=ScalarFormatter(useMathText=True)
                fmt.set_powerlimits((-3,4))
                axis.set_major_formatter(fmt)
        if p['auto_limits']:
            ax.relim()
            ax.autoscale_view(tight=False)
        if p['journal_frame']:
            apply_journal_ticks(ax)


def style_image(ax,arr,channel,profile,*,extent=None):
    p=validate_plot(profile or DEFAULT_PLOT)
    from .plot_settings import viewer_limits
    limits=viewer_limits(p,channel,arr) or (None,None)
    im=ax.imshow(arr,cmap=display_cmap(channel,p),origin='upper',
                 interpolation=p['image_interpolation'],aspect=p['image_aspect'],
                 extent=extent,vmin=limits[0],vmax=limits[1])
    if p['image_colorbar']:
        ax.figure.colorbar(im,ax=ax)
    return im


# ---------------------------------------------------------------------------
# v29 — journal axes + automatic a, b, c … panel letters for multi-plot figures
# ---------------------------------------------------------------------------
PUBLICATION_MIN_DPI = 600


def publication_dpi(value=None):
    """Raster exports are never written below 600 DPI."""
    try: v=int(value or 0)
    except (TypeError,ValueError): v=0
    return max(PUBLICATION_MIN_DPI,v)


def _is_colorbar_axes(ax):
    return (ax.get_label()=='<colorbar>' or getattr(ax,'_colorbar',None) is not None
            or getattr(ax,'_spm_colorbar',False))


def apply_journal_ticks(ax, *, inset=False):
    """Closed black frame, inward major+minor ticks on all four sides, no grid."""
    from matplotlib.ticker import AutoMinorLocator, FixedLocator, NullLocator
    if _is_colorbar_axes(ax):return
    for spine in ax.spines.values():
        spine.set_color('black');spine.set_linewidth(0.75 if inset else 0.9)
    has_lines=bool(ax.lines or ax.collections or ax.containers or ax.patches)
    pure_image=bool(ax.images) and not ax.lines
    major=2.8 if inset else 4.0
    ax.tick_params(axis='both',which='major',direction='in',top=True,right=True,
                   length=major,width=0.8,color='black')
    ax.tick_params(axis='both',which='minor',direction='in',top=True,right=True,
                   length=major*.55,width=0.6,color='black')
    if pure_image or not has_lines:
        ax.minorticks_off();return
    for axis in (ax.xaxis,ax.yaxis):
        if axis.get_scale()!='linear':continue
        if isinstance(axis.get_major_locator(),(FixedLocator,NullLocator)):continue
        axis.set_minor_locator(AutoMinorLocator(2))


def is_panel_axes(ax):
    """True for a real plot/image panel; False for colourbars, insets and legend boxes."""
    if getattr(ax,'_spm_no_panel_label',False) or getattr(ax,'_spm_inset',False):return False
    if not ax.get_visible() or _is_colorbar_axes(ax):return False
    if not (ax.lines or ax.images or ax.collections or ax.patches or ax.containers):return False
    fig=ax.figure
    pos=ax.get_position()
    w=pos.width*fig.get_figwidth();h=pos.height*fig.get_figheight()
    if w<=0 or h<=0 or min(w,h)/max(w,h)<.12:return False   # strip-like colourbar
    return True


def _renderer(fig):
    try:return fig.canvas.get_renderer()
    except AttributeError:pass
    if hasattr(fig,'_get_renderer'):return fig._get_renderer()
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    return FigureCanvasAgg(fig).get_renderer()


def _reading_order(fig,axes,order):
    items=[(ax,ax.get_position()) for ax in axes]
    if order=='columns':
        items.sort(key=lambda t:(round(t[1].x0,2),-t[1].y1));return [a for a,_ in items]
    items.sort(key=lambda t:-t[1].y1)
    rows=[]
    for ax,pos in items:
        for row in rows:
            ref=row[0][1]
            if abs(ref.y1-pos.y1)<.5*min(ref.height,pos.height):
                row.append((ax,pos));break
        else:rows.append([(ax,pos)])
    result=[]
    for row in rows:result.extend(a for a,_ in sorted(row,key=lambda t:t[1].x0))
    return result


def add_panel_labels(fig, *, order='rows', fontsize=None, start=0, force=False):
    """Add bold a, b, c … letters at the top-left of every panel of a multi-panel figure.

    Letters are placed left of the y-axis label (outside the frame, like Nature
    figures).  Single-panel figures are left unlabelled unless ``force`` is True.
    Calling it again replaces earlier letters (safe for live previews).
    """
    if getattr(fig,'_spm_panel_labels',True) is False:return []
    for t in list(fig.texts):
        if getattr(t,'_spm_panel_label',False):t.remove()
    panels=[ax for ax in fig.axes if is_panel_axes(ax)]
    if len(panels)<2 and not force:return []
    import matplotlib as mpl
    renderer=_renderer(fig)
    inv=fig.transFigure.inverted()
    size=fontsize or (float(mpl.rcParams.get('axes.labelsize',10)) if not isinstance(
        mpl.rcParams.get('axes.labelsize'),str) else 10.)+3
    pad=3/72/fig.get_figheight()
    created=[]
    for i,ax in enumerate(_reading_order(fig,panels,order)):
        try:
            bb=ax.get_tightbbox(renderer)
            x0=inv.transform((bb.x0,bb.y0))[0]
        except Exception:
            x0=ax.get_position().x0-.04
        top=ax.get_position().y1
        # a colourbar placed above this panel: the letter goes above the bar
        for cax in fig.axes:
            cb=getattr(cax,'_colorbar',None)
            if cb is not None and getattr(cb.mappable,'axes',None) is ax and cax.get_visible():
                cpos=cax.get_position()
                if cpos.y0>=top-1e-3:top=max(top,cpos.y1)
        y=top+pad
        letter=chr(ord('a')+((start+i)%26))
        txt=fig.text(max(.002,x0),y,letter,fontsize=size,fontweight='bold',
                     ha='left',va='bottom',color='black')
        txt._spm_panel_label=True
        created.append(txt)
    return created


def finalize_publication_figure(fig, style=None, *, order='rows'):
    """Journal frame + panel letters; call after layout, just before savefig."""
    p=validate_plot(style or DEFAULT_PLOT)
    sanitize_figure_text(fig)
    if p['journal_frame']:
        for ax in fig.axes:
            if hasattr(ax,'spines') and not _is_colorbar_axes(ax):
                apply_journal_ticks(ax,inset=getattr(ax,'_spm_inset',False))
                for child in getattr(ax,'child_axes',[]):
                    apply_journal_ticks(child,inset=True)
    if p['panel_labels']:
        add_panel_labels(fig,order=order,fontsize=p['label_size']+3)
    return fig


# ---------------------------------------------------------------------------
# v30 — transparent-background figure saving
# ---------------------------------------------------------------------------
def sanitize_figure_text(fig):
    """v34.1: no label may make a figure fail — text whose LaTeX cannot be typeset is repaired."""
    from matplotlib.text import Text
    from .plot_settings import clean_title
    for t in fig.findobj(Text):
        s=t.get_text()
        if s and ('$' in s or '\\\\' in s):
            fixed=clean_title(s)
            if fixed!=s:t.set_text(fixed)
    return fig


def savefig_maybe_transparent(fig, dest, *, transparent=False, background='white', **kwargs):
    """Save a Matplotlib figure with an optional fully transparent background.

    The page and the plot areas become transparent (PNG alpha / PDF / SVG with
    no white rectangle).  Axes marked ``_spm_keep_background`` (insets drawn
    over data) keep their own fill so they stay readable.  JPEG cannot store
    transparency and stays white.
    """
    dest=str(dest)
    sanitize_figure_text(fig)
    jpeg=dest.lower().endswith(('.jpg','.jpeg')) or kwargs.get('format') in ('jpg','jpeg')
    if not transparent or jpeg:
        return fig.savefig(dest,facecolor=background if not jpeg or background!='none' else 'white',**kwargs)
    saved=[(fig.patch,fig.patch.get_facecolor(),fig.patch.get_edgecolor())]
    fig.patch.set_facecolor('none');fig.patch.set_edgecolor('none')
    for ax in fig.axes:
        if getattr(ax,'_spm_keep_background',False):continue
        saved.append((ax.patch,ax.patch.get_facecolor(),ax.patch.get_edgecolor()))
        ax.patch.set_facecolor('none')
    try:
        return fig.savefig(dest,facecolor='none',edgecolor='none',**kwargs)
    finally:
        for patch,face,edge in saved:
            patch.set_facecolor(face);patch.set_edgecolor(edge)


# ---------------------------------------------------------------------------
# v32 — user figure customization applied to every script figure
# ---------------------------------------------------------------------------
def parse_replacements(text):
    pairs=[]
    for line in str(text or '').splitlines():
        for sep in ('=>','→','->'):
            if sep in line:
                old,new=line.split(sep,1)
                if old.strip():pairs.append((old.strip(),new.strip()))
                break
    return pairs


def _replace(s,pairs):
    if not s:return s
    for old,new in pairs:
        if s==old:return new
    for old,new in pairs:
        if old in s:s=s.replace(old,new)
    return s


def _apply_viewer_titles(fig, p):
    """v34: labels that start with a channel name use the title set on the scan.

    Only a label that IS the channel name, or starts with it followed by a unit in
    ( ) or [ ], is changed ("OC M1 Excitation (mV)" → "$V_{exc}$ (mV)").
    """
    import re
    cfg=p.get('viewer_config') or {}
    if not cfg.get('enabled'):return
    rules=[]
    for name,info in (cfg.get('channels') or {}).items():
        from .plot_settings import clean_title
        title=clean_title((info or {}).get('title'))
        if title and title!=name:
            rules.append((re.compile(r'^'+re.escape(name)+r'(?=$|\s*[\(\[])'),title))
    if not rules:return
    def fix(s):
        if not s:return s
        for rx,title in rules:
            if rx.match(s):return rx.sub(lambda m:title,s,count=1)
        return s
    for ax in fig.axes:
        ax.set_xlabel(fix(ax.get_xlabel()));ax.set_ylabel(fix(ax.get_ylabel()))
        if ax.get_title():ax.set_title(fix(ax.get_title()))
        for t in ax.texts:t.set_text(fix(t.get_text()))


def apply_figure_customization(fig, style=None):
    """Colormap override, titles, text renaming, colourbar and legend placement.

    Safe defaults ('auto') leave every script's own layout untouched.  Figures
    flagged ``fig._spm_custom_layout`` keep their bespoke colourbar geometry
    (only hide / colormap / text apply).
    """
    p=validate_plot(style or DEFAULT_PLOT)
    _apply_viewer_titles(fig,p)
    pairs=parse_replacements(p['text_replacements'])
    cmap=p['colormap_override']
    custom_layout=getattr(fig,'_spm_custom_layout',False)
    data_axes=[ax for ax in fig.axes if not _is_colorbar_axes(ax)]
    for ax in data_axes:
        if cmap:
            for im in ax.images:
                arr=im.get_array()
                if arr is not None and getattr(arr,'ndim',2)==2:im.set_cmap(cmap)
            for coll in ax.collections:
                if getattr(coll,'get_array',None) is not None and coll.get_array() is not None \
                   and hasattr(coll,'set_cmap') and type(coll).__name__ in ('QuadMesh','PolyCollection','PathCollection'):
                    try:coll.set_cmap(cmap)
                    except Exception:pass
        if not p['show_titles']:ax.set_title('')
        elif pairs:ax.set_title(_replace(ax.get_title(),pairs))
        if pairs:
            ax.set_xlabel(_replace(ax.get_xlabel(),pairs));ax.set_ylabel(_replace(ax.get_ylabel(),pairs))
            for t in ax.texts:t.set_text(_replace(t.get_text(),pairs))
        leg=ax.get_legend()
        if leg is not None:
            if pairs:
                for t in leg.get_texts():t.set_text(_replace(t.get_text(),pairs))
            mode=p['legend_mode']
            if mode=='hide':leg.remove()
            elif mode!='auto':
                handles,labels=ax.get_legend_handles_labels()
                if pairs:labels=[_replace(l,pairs) for l in labels]
                kw={'frameon':bool(p['legend_frame'])}
                if mode=='outside right':kw.update(loc='upper left',bbox_to_anchor=(1.02,1.),borderaxespad=0.)
                else:kw['loc']=mode
                ax.legend(handles,labels,**kw)
            else:leg.set_frame_on(bool(p['legend_frame']))
    if fig._suptitle is not None:
        if not p['show_titles']:fig._suptitle.set_text('')
        elif pairs:fig._suptitle.set_text(_replace(fig._suptitle.get_text(),pairs))
    if pairs:
        for t in fig.texts:
            if not getattr(t,'_spm_panel_label',False):t.set_text(_replace(t.get_text(),pairs))
    # Colourbars
    mode=p['colorbar_mode']
    for cax in [ax for ax in list(fig.axes) if _is_colorbar_axes(ax)]:
        cb=getattr(cax,'_colorbar',None)
        if pairs and cb is not None:
            cb.ax.set_ylabel(_replace(cb.ax.get_ylabel(),pairs));cb.ax.set_xlabel(_replace(cb.ax.get_xlabel(),pairs))
            for t in cb.ax.texts:t.set_text(_replace(t.get_text(),pairs))
        if mode=='hide':
            cax.set_visible(False)
            continue
        if mode in ('auto',) or custom_layout or cb is None:
            if cmap and cb is not None:
                try:cb.update_normal(cb.mappable)
                except Exception:pass
            continue
        mappable=cb.mappable;parent=getattr(mappable,'axes',None)
        if parent is None:continue
        label=cb.ax.get_ylabel() or cb.ax.get_xlabel()
        try:
            cb.remove()
            new=fig.colorbar(mappable,ax=parent,location=mode,fraction=float(p['colorbar_size_pct'])/100.,pad=.02)
            if label:new.set_label(label)
            if mode=='top' and parent.get_title():
                # keep the plot title above the bar instead of hidden behind it
                new.ax.set_title(parent.get_title(),fontsize=parent.title.get_fontsize(),pad=4)
                parent.set_title('')
        except Exception:
            pass
    return fig
