"""Monte-Carlo generation of radial basis function tables (``GenerateRBFs``) from random points projected onto a plane."""
import numpy as np
import pickle

def GenerateRBFs(rmax,num = int(1e6),fnm=None):

    """Return a dict mapping each radius r = 2..rmax to a normalized radial histogram computed from ``num`` random points.

    For each r, the random points of ``UnitSphereAbelProj`` are scaled to radii drawn between r-1 and r (uniform in r**3); the histogram of their projected radius in unit bins 0..r is divided by its last bin and reversed. Progress is printed every 50 radii, and the dict is pickled to ``fnm`` if given.
    """
    rs = np.arange(2,rmax+1)
    randnum = np.random.random(num)
    Xs1,Ys1 = UnitSphereAbelProj(num) 
    
    RBFs = {}   
    for i,r in enumerate(rs):    
        r3 = r**3        
        rs = np.cbrt(r3 - (r3-(r-1)**3)*randnum)    
        Xs = Xs1*rs; Ys = Ys1*rs           
        Rs = np.sqrt(Xs**2+Ys**2)
        
        Rbins = np.arange(0,r+1)             
        RBFs_r,_ = np.histogram(Rs,bins = Rbins)  
        RBFs[r] = ((RBFs_r/RBFs_r[-1])[::-1])
       
        if i%50 ==0:
            print('r = '+str(r)+' finished.')
    
    if fnm is not None:
        with open(fnm,'wb') as f:
            pickle.dump(RBFs,f,protocol=pickle.HIGHEST_PROTOCOL)
     
    return RBFs        
        
def UnitSphereAbelProj(num):
    """Return two arrays of ``num`` random values: ``sqrt(1-c**2)*sin(phi)`` and ``c``, with ``c`` uniform in [0, 1) and ``phi`` uniform in [0, pi/2)."""
    costheta = np.random.random(num)
    phi = np.random.random(num)*np.pi/2
    return np.sqrt(1-costheta**2)*np.sin(phi), costheta
