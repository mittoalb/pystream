"""APS-U-scale undulator at 32-ID (illustrative parameters).

Shows a typical white-beam spectrum through a 1x1 mm slit at 30 m with
the standard APS front-end (Be window + CVD diamond) plus a 100 um Al
filter for imaging.
"""
import numpy as np

from xraysource import Undulator, FilterStack, Slit, Beamline

und = Undulator(
    E_GeV=7.0,
    current_A=0.200,       # APS-U at 200 mA
    period_mm=33.0,        # APS U33 short-period undulator
    N_periods=72,          # ~2.37 m device
    K=2.5,                 # tune with the taper/gap
    energy_spread=9.5e-4,  # APS-U rms
    max_harmonic=15,
)

slit = Slit(distance_m=30.0, h_mm=1.0, v_mm=1.0)

stack = FilterStack()
stack.add("Be", 500.0)      # front-end Be window
stack.add("diamond", 300.0) # CVD diamond filter
stack.add("Al", 100.0)      # user attenuator

bl = Beamline(source=und, slit=slit, filters=stack, n_theta=11)

print(und.describe())
print(f"Fundamental E_1 = {und.E1_keV:.3f} keV")
print("harmonic table (n, E_n [keV], on-axis brightness, central-cone flux):")
for n, En, peak, cone in und.harmonic_table():
    print(f"  n={n:2d}  E_n={En:7.3f} keV  peak={peak:.2e}  cone={cone:.2e}")

E = np.geomspace(1.0, 60.0, 400)
E_arr, F, T, F0 = bl.spectrum(1.0, 60.0, n=400, log=True)
peak = int(np.nanargmax(F))
P = bl.power_W(1.0, 60.0)
print(f"\nPeak filtered flux: {F[peak]:.3e} ph/s/0.1%BW @ {E_arr[peak]:.2f} keV")
print(f"Integrated power (1-60 keV): {P*1e3:.1f} mW")
