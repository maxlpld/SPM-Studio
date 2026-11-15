# Molecule placement — SVG / PNG (v14)

1. Open your SXM/GWY scan. Run **Lattice measurements** on the desired area to
   save its `lattice_result.json`. The result is found automatically from the
   current scan under `SPM_Studio_Results/<scan>/Data/`.
2. Under **Tools**, select **Molecule placement — SVG / PNG**.
   Studio switches the right sidebar to **Tool settings** automatically.
3. At the top of Tool settings, click **Load molecule SVG / PNG…**.
   Choose your actual molecule file. Its filename and artwork thumbnail appear
   *immediately*, independent of lattice-result availability.
4. Enter physical **Molecule WIDTH** and **HEIGHT** in nanometers, select
   automatic alignment to a (or manual orientation), adjust **rotation** in
   degrees and **number of molecules** (`0` places every eligible lattice site).
5. The lattice-registered live preview is updated as settings change. Click
   **Run analysis** for PNG, PDF, GWY and reproducible placement JSON results.

Images are placed in calibrated real-space coordinates, not in arbitrary pixel
size. Placement is a geometric hypothesis; it does not model adsorption energy.
Existing user tool files are backed up before v14 replaces them.
