"""APS-scale bending magnet example."""
import numpy as np
from xraysource import BendingMagnet, FilterStack, Slit, Beamline

bm = BendingMagnet(E_GeV=7.0, current_A=0.100, B_T=0.60)

slit = Slit(distance_m=25.0, h_mm=4.0, v_mm=1.0)

stack = FilterStack()
stack.add("Be", 500.0)

bl = Beamline(source=bm, slit=slit, filters=stack)
print(bm.describe())
print(f"Critical energy: {bm.epsilon_c_keV:.2f} keV")
print(f"Gamma = {bm.gamma:.1f}, natural vertical divergence ~ 1/gamma = "
      f"{1e3/bm.gamma:.3f} mrad")

E, F, T, F0 = bl.spectrum(1.0, 100.0, n=400, log=True)
print(f"Peak filtered flux: {F.max():.3e} ph/s/0.1%BW @ {E[F.argmax()]:.2f} keV")
print(f"Power (1-100 keV): {bl.power_W(1.0, 100.0)*1e3:.1f} mW")
