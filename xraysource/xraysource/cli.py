"""Command-line front-end.

Examples
--------
    xraysource undulator --E-GeV 7 --I-mA 200 --period-mm 33 --N 72 --K 2.5 \
        --slit-dist 30 --slit-h 1 --slit-v 1 \
        --filter Be:500 --filter diamond:300 --filter Al:100 \
        --Emin 1 --Emax 60 --n 800 --out spectrum.csv

    xraysource bm --E-GeV 7 --I-mA 100 --B 0.6 --slit-dist 25 \
        --slit-h 4 --slit-v 1 --filter Be:500

    xraysource wiggler --E-GeV 7 --I-mA 100 --period-mm 85 --N 28 --B 1.5

If matplotlib is available, --plot pops up a figure.
"""
from __future__ import annotations

import argparse
import sys
import numpy as np

from .bending_magnet import BendingMagnet
from .wiggler import Wiggler
from .undulator import Undulator
from .filters import Filter, FilterStack
from .slits import Slit
from .beamline import Beamline
from .logger import configure_logging, get_logger

_log = get_logger("xraysource.cli")


def _parse_filter(spec: str) -> Filter:
    """Parse "material:thickness_um[:density]" into a Filter."""
    parts = spec.split(":")
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(
            f"Filter spec must be 'material:thickness_um[:density]', got {spec!r}")
    name = parts[0]
    t_um = float(parts[1])
    rho = float(parts[2]) if len(parts) > 2 else None
    return Filter(name, t_um, rho)


def _add_common_args(p):
    p.add_argument("--E-GeV", type=float, required=True, help="Electron energy (GeV)")
    p.add_argument("--I-mA", type=float, required=True, help="Ring current (mA)")

    p.add_argument("--slit-dist", type=float, default=30.0, help="Slit distance (m)")
    p.add_argument("--slit-h", type=float, default=1.0, help="Slit H (mm)")
    p.add_argument("--slit-v", type=float, default=1.0, help="Slit V (mm)")
    p.add_argument("--slit-hoff", type=float, default=0.0, help="Slit H offset (mm)")
    p.add_argument("--slit-voff", type=float, default=0.0, help="Slit V offset (mm)")
    p.add_argument("--slit-n", type=int, default=11, help="Integration pts/axis")

    p.add_argument("--filter", action="append", default=[], type=_parse_filter,
                   help="Filter 'material:thickness_um[:density]', repeatable")

    p.add_argument("--Emin", type=float, default=1.0, help="Min energy (keV)")
    p.add_argument("--Emax", type=float, default=100.0, help="Max energy (keV)")
    p.add_argument("--n", type=int, default=800, help="Number of energy points")
    p.add_argument("--linear", action="store_true", help="Linear energy axis")

    p.add_argument("--out", type=str, default=None,
                   help="Write E, flux_at_slit, transmission, filtered_flux to CSV")
    p.add_argument("--plot", action="store_true",
                   help="Show matplotlib plot")


def _build_bl(source, args):
    slit = Slit(distance_m=args.slit_dist, h_mm=args.slit_h, v_mm=args.slit_v,
                h_offset_mm=args.slit_hoff, v_offset_mm=args.slit_voff)
    stack = FilterStack()
    for f in args.filter:
        stack.filters.append(f)
    return Beamline(source=source, slit=slit, filters=stack, n_theta=args.slit_n)


def _run(bl, args):
    E, F, T, F0 = bl.spectrum(E_min_keV=args.Emin, E_max_keV=args.Emax,
                                n=args.n, log=not args.linear)
    P = bl.power_W(E_min_keV=max(0.1, args.Emin), E_max_keV=args.Emax, n=1000)
    peak = int(np.nanargmax(F))
    print(f"Source: {bl.source.describe()}")
    print(f"Slit  : {bl.slit.h_mm}x{bl.slit.v_mm} mm at {bl.slit.distance_m} m "
          f"({bl.slit.h_accept_mrad()*1e3:.1f} x {bl.slit.v_accept_mrad()*1e3:.1f} µrad)")
    print(f"Filters:")
    for f in bl.filters:
        print(f"  {f}")
    print()
    print(f"Peak filtered flux : {F[peak]:.3e} ph/s/0.1%BW  @ {E[peak]:.3f} keV")
    print(f"Integrated power   : {P*1e3:.2f} mW  ({args.Emin}..{args.Emax} keV)")
    if args.out:
        arr = np.column_stack([E, F0, T, F])
        np.savetxt(args.out, arr, delimiter=",",
                    header="E_keV,flux_at_slit,transmission,filtered_flux",
                    comments="")
        print(f"Wrote {args.out}")
    if args.plot:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not installed; skipping plot", file=sys.stderr)
            return
        fig, ax1 = plt.subplots(figsize=(9, 5))
        ax1.loglog(E, np.maximum(F0, 1e-30), label="flux @ slit", color="#0064b4")
        ax1.loglog(E, np.maximum(F, 1e-30), label="filtered flux", color="#c82828")
        ax1.set_xlabel("Photon energy [keV]"); ax1.set_ylabel("Flux [ph/s/0.1%BW]")
        ax1.grid(True, which="both", alpha=0.3)
        ax2 = ax1.twinx(); ax2.plot(E, T, color="#1e8c1e", linestyle="--",
                                     label="transmission")
        ax2.set_ylabel("Filter transmission"); ax2.set_ylim(0, 1.05)
        ax1.legend(loc="upper left"); ax2.legend(loc="upper right")
        plt.tight_layout(); plt.show()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xraysource",
                                  description="X-ray source spectrum calculator")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL",
                             "debug", "info", "warning", "error", "critical"],
                    help="Terminal log level (default INFO)")
    ap.add_argument("--no-color", action="store_true",
                    help="Disable ANSI colours in the log output")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_bm = sub.add_parser("bm", help="Bending magnet")
    p_bm.add_argument("--B", type=float, default=None, help="Field (T)")
    p_bm.add_argument("--R", type=float, default=None, help="Radius (m)")
    _add_common_args(p_bm)

    p_wg = sub.add_parser("wiggler", help="Multi-pole wiggler")
    p_wg.add_argument("--period-mm", type=float, required=True)
    p_wg.add_argument("--N", type=int, required=True, help="Number of periods")
    p_wg.add_argument("--B", type=float, default=None, help="Peak field (T)")
    p_wg.add_argument("--K", type=float, default=None, help="Deflection parameter")
    _add_common_args(p_wg)

    p_un = sub.add_parser("undulator", help="Planar undulator")
    p_un.add_argument("--period-mm", type=float, required=True)
    p_un.add_argument("--N", type=int, required=True, help="Number of periods")
    p_un.add_argument("--B", type=float, default=None, help="Peak field (T)")
    p_un.add_argument("--K", type=float, default=None, help="Deflection parameter")
    p_un.add_argument("--energy-spread", type=float, default=1e-3)
    p_un.add_argument("--max-harmonic", type=int, default=15)
    _add_common_args(p_un)

    args = ap.parse_args(argv)
    configure_logging(level=args.log_level,
                       use_colour=False if args.no_color else None)
    _log.debug("parsed args: %s", vars(args))
    I = args.I_mA * 1e-3

    if args.cmd == "bm":
        if args.B is None and args.R is None:
            ap.error("bm: give --B or --R")
        src = BendingMagnet(E_GeV=args.E_GeV, current_A=I, B_T=args.B, radius_m=args.R)
    elif args.cmd == "wiggler":
        if (args.B is None) == (args.K is None):
            ap.error("wiggler: give exactly one of --B or --K")
        src = Wiggler(E_GeV=args.E_GeV, current_A=I,
                      period_mm=args.period_mm, N_periods=args.N,
                      B_T=args.B, K=args.K)
    else:
        if (args.B is None) == (args.K is None):
            ap.error("undulator: give exactly one of --B or --K")
        src = Undulator(E_GeV=args.E_GeV, current_A=I,
                        period_mm=args.period_mm, N_periods=args.N,
                        B_T=args.B, K=args.K,
                        energy_spread=args.energy_spread,
                        max_harmonic=args.max_harmonic)

    bl = _build_bl(src, args)
    _run(bl, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
