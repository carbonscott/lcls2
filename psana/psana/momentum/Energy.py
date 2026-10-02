"""Defines ``CalcEnergy``, a closed-form expression of three momentum components and a mass."""
import numpy as np

def CalcEnergy(m_amu,Px_au,Py_au,Pz_au):
    """Return ``27.2*(Px_au**2 + Py_au**2 + Pz_au**2)/(2*1836.15*m_amu)``.

    The unit suffixes come from the parameter names; the code applies only the constants shown.
    """
    amu2au = 1836.15
    return 27.2*(Px_au**2 + Py_au**2 + Pz_au**2)/(2*amu2au*m_amu)
