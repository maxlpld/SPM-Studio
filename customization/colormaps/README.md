# Colormaps — how to build one for SPM Studio

**Read this before creating or changing a file in this folder** (person or AI assistant).

A colormap is one `.csv` or `.txt` file here: a table of colours from the lowest value (first row)
to the highest (last row). It appears in the colormap list of the Inspector under its file name,
and profiles refer to it by its **file name** (`"colormap": "my_map.csv"`).

## Format

- One colour per row: `R,G,B` or `R,G,B,A`.
- Either all values between 0 and 1, or all between 0 and 255. Do not mix.
- `.csv`: values separated by commas. `.txt`: separated by spaces or tabs.
- At least 2 rows; 256 rows is the usual choice for a smooth map.
- Lines starting with `#` are comments. No header row, no empty columns.

```
# black → teal → white
0,0,0
0.00,0.45,0.42
1,1,1
```

For data, prefer maps whose lightness increases steadily (they stay readable in grey-scale print)
and a diverging map only when zero has a meaning (KPFM bias, frequency shift around a reference).

## Check

```
python -c "import numpy as np; a=np.loadtxt('my_map.csv', delimiter=',', comments='#'); print(a.shape, a.min(), a.max())"
```

The shape must be `(rows, 3)` or `(rows, 4)`. Then **Settings › Library › Colormaps**: listed
without “invalid”, and selectable in the Inspector.

Gwyddion gradients: **Settings › Library › Colormaps › Import Gwyddion gradients…**.

## Share

**Settings › Library › Colormaps › Export…** → one `.zip`; a colleague uses **Import…**.
