"""Smooth bounded growth interpolation."""
import numpy as np

def ease(x):
    x=np.clip(x,0.,1.)
    return x*x*x*(x*(x*6-15)+10)
