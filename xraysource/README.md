# xraysource

X-ray source spectrum calculator: bending magnet, multi-pole wiggler,
planar undulator + material filter stack + slit geometry.

Lightweight standalone tool, comparable in spirit to (but much smaller
than) XOP/OASYS `xoppylib` and `xrt`. No SHADOW / ray-tracing, no wave
optics — this is a spectrum-and-flux calculator.

## What it computes

- **Bending magnet** — full Kim/Schwinger formulas
  (`G_1(y)` for vertical-integrated flux, angle-dependent
  `sigma`/`pi` polarisation split via `K_{1/3}`, `K_{2/3}`).
- **Multi-pole wiggler** — flat-fan (K≫1) superposition: 2N BM poles
  with a smooth `erfc` cutoff at `±K/γ` in horizontal.
- **Planar undulator** — resonance energies `E_n(θ)` with off-axis
  red-shift, planar `F_n(K)` / `Q_n(K)` Bessel formulas, on-axis
  brightness, central-cone integrated flux. Line shape from
  `sinc²(πN·ΔE/E)` broadened by electron energy spread.
- **Material filters** — total attenuation via `xraylib.CS_Total` (or
  compound via `CS_Total_CP`). Aliases for common trade names
  (`kapton`, `diamond`, `mylar`, `sapphire`, …).
- **Rectangular slit** at a chosen source distance, with H/V offsets.
- **Beamline** — composes source + slit + filter stack, integrates
  flux through the aperture and computes total heat load (W).

Units follow the synchrotron convention: photon flux is per **0.1 %
relative bandwidth**; brightness/angular flux add `/mrad` or `/mrad²`.

## Install

```bash
cd xraysource
pip install -e .            # library + CLI
pip install -e .[gui]       # + PyQt5 GUI
pip install -e .[mpl]       # + matplotlib for CLI --plot
```

Requires: `numpy`, `scipy`, `xraylib` (already present in `pystream`
env). Optional: `PyQt5` + `pyqtgraph` for the GUI, `matplotlib` for
CLI plotting.

## GUI

```bash
xraysource-gui
```

Left column selects a machine preset (APS, APS-U, ESRF-EBS, PETRA III,
NSLS-II, SPring-8, MAX IV, Diamond, or Custom) and the source type; the
lower left group sets slit geometry. The middle column is a filter
stack editor (add from a dropdown of common materials, toggle each
row, edit thickness/density in-place). The right column plots
**flux at slit**, **filter transmission**, and **filtered flux** with
log/log axes.

Below the plot: peak filtered flux, its energy, and integrated
beamline power over the plotted energy range.

Export the current spectrum to CSV via the button in the plot toolbar.

## CLI

```bash
# APS-U undulator U33 at 32-ID, 200 mA, 1x1 mm slit at 30 m,
# Be + diamond + Al filters:
xraysource undulator \
    --E-GeV 7 --I-mA 200 \
    --period-mm 33 --N 72 --K 2.5 \
    --slit-dist 30 --slit-h 1 --slit-v 1 \
    --filter Be:500 --filter diamond:300 --filter Al:100 \
    --Emin 3 --Emax 60 --n 800 \
    --out u33_spectrum.csv

# APS bending magnet (0.6 T), 4x1 mm slit at 25 m, 500 um Be:
xraysource bm --E-GeV 7 --I-mA 100 --B 0.6 \
    --slit-dist 25 --slit-h 4 --slit-v 1 \
    --filter Be:500

# 28-pole APS wiggler (85 mm, 1.5 T):
xraysource wiggler --E-GeV 7 --I-mA 100 \
    --period-mm 85 --N 28 --B 1.5 \
    --filter Be:500 --Emin 5 --Emax 200
```

Add `--plot` for a matplotlib figure. `--filter` is
`material:thickness_um[:density_g_cm3]` and repeatable. Materials can
be elements (`Be`, `Al`), compound formulas (`SiO2`, `Al2O3`), or
common aliases (`kapton`, `diamond`, `mylar`, `sapphire`, `pmma`,
`water`, `air`, ...).

## Python API

```python
from xraysource import (
    Undulator, BendingMagnet, Wiggler,
    Filter, FilterStack, Slit, Beamline,
)
import numpy as np

und = Undulator(E_GeV=7.0, current_A=0.2,
                period_mm=33.0, N_periods=72, K=2.5,
                energy_spread=9.5e-4, max_harmonic=15)

slit = Slit(distance_m=30.0, h_mm=1.0, v_mm=1.0)

stack = FilterStack()
stack.add("Be", 500.0)
stack.add("diamond", 300.0)
stack.add("Al", 100.0)

bl = Beamline(source=und, slit=slit, filters=stack)

E = np.geomspace(1.0, 60.0, 800)
E, flux, transmission, flux_at_slit = bl.spectrum(1.0, 60.0, n=800)
power_W = bl.power_W(1.0, 60.0)

# Harmonic table (n, E_n [keV], on-axis brightness, cone flux):
for n, En, peak, cone in und.harmonic_table():
    print(n, En, peak, cone)
```

Each source also exposes lower-level differential quantities:

- `source.angular_flux(E)` — ph/s/mrad/0.1%BW (vertical-integrated)
- `source.flux_density(E, θ_h_mrad, θ_v_mrad)` — ph/s/mrad²/0.1%BW
- `source.flux_through_slit(E, dist_m, h_mm, v_mm, ...)`  — ph/s/0.1%BW

## Physics references

- K.-J. Kim, *Characteristics of Synchrotron Radiation*, AIP Conf.
  Proc. 184 (1989).
- H. Wiedemann, *Synchrotron Radiation*, Springer (2003).
- X-ray Data Booklet (LBNL, rev. 3), §2.1.
- P. Elleaume, in *Undulators, Wigglers and their Applications* (2003).

Filter cross sections come from `xraylib`
(https://github.com/tschoonj/xraylib), which itself packages
EPDL97/NIST photoelectric, Rayleigh, and Compton tables.

## Scope / limitations

- Undulator angular envelope uses the standard central-cone (Gaussian)
  approximation and independent-amplitude off-axis red-shift. It gives
  the peak location and integrated central-cone flux accurately;
  detailed angular emission patterns (relevant only for
  small-aperture, non-central-cone slits) are approximate — use SRW or
  SPECTRA for those.
- Wiggler is treated in the K≫1 flat-fan limit (incoherent
  superposition of BM poles). Interference features at small K are
  not captured; use an undulator model there instead.
- No coherence, no beam emittance convolution, no monochromator
  response, no reflectivity of mirrors. Add them downstream if needed.

## Tests

```bash
python -m pytest tests/
```
