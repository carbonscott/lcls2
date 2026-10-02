"""Helpers to build a quarter-plane Cartesian grid and a polar grid, find nearest neighbours between them with scikit-learn, and resample values from one grid to the other."""
import sys
import numpy as np
from scipy import interpolate
from sklearn.neighbors import NearestNeighbors

def GenerateCartGrid(Rmax):

    """Return an (Rmax*Rmax, 2) array of the (x, y) pixel-center coordinates ``0.5 ... Rmax-0.5`` of a square Cartesian grid."""
    Xs = np.arange(Rmax)+0.5
    Xs_mesh, Ys_mesh = np.meshgrid(Xs, Xs)
    Xs_mesh = Xs_mesh.flatten()
    Ys_mesh = Ys_mesh.flatten()   
    XYs_cart = np.hstack([Xs_mesh[:,np.newaxis],Ys_mesh[:,np.newaxis]])      
        
    return XYs_cart
    
def GeneratePolarGrid(Rmax):  

    """Build a polar grid over a quarter circle with about ``0.5*pi*r`` points on each radius ``r = Rmax-0.5, ..., 0.5`` (outermost first).

    Returns
    -------
    tuple
        ``(Rarr, num_elms_at_R, num_elms, Rarrs, Angles, XYs_polar)``: the radii, points per radius, total points, per-point radius and angle (radians, centered in equal steps over 0..pi/2), and the (num_elms, 2) array of ``(r*sin(angle), r*cos(angle))``.
    """
    Rarr = np.arange(Rmax)[::-1]+0.5
    num_elms_at_R = (np.round(0.5*np.pi*Rarr)).astype(int)
    angle_incs = 0.5*np.pi/num_elms_at_R 
    num_elms = num_elms_at_R.sum()
               
    Angles = np.zeros((num_elms,))
    Rarrs = np.zeros((num_elms,))        
        
    ind = 0
    for i, num in enumerate(num_elms_at_R):
        Angles[ind:(ind+num)] = np.arange(0,num)*angle_incs[i] + angle_incs[i]/2
        Rarrs[ind:(ind+num)] = np.ones((num,))*Rarr[i]
        ind += num      
                
    Xs = Rarrs*np.sin(Angles)
    Ys = Rarrs*np.cos(Angles)        
    XYs_polar = np.hstack([Xs[:,np.newaxis],Ys[:,np.newaxis]])         
    
    return Rarr, num_elms_at_R, num_elms, Rarrs, Angles, XYs_polar

def FindNbrs(xs,ys,n_neighbors=4,algorithm='ball_tree',metric='euclidean'):

    """Find the ``n_neighbors`` nearest points of ``xs`` for each point of ``ys`` with ``sklearn.neighbors.NearestNeighbors``.

    Returns
    -------
    tuple
        ``(inds, cs)``: neighbour indexes and inverse-distance weights normalized to sum 1 per row (machine epsilon is added to the distances).
    """
    nbrs = NearestNeighbors(n_neighbors=n_neighbors, algorithm=algorithm,metric=metric).fit(xs)        
    ds, inds = nbrs.kneighbors(ys)
    ds += sys.float_info.epsilon
    cs = 1/ds
    cs = cs/(cs.sum(axis=1)[:,np.newaxis])
    
    return inds,cs
    
def Cart2Polar(Q_cart,inds_cart,cs_cart):
    
    """Return values on the polar grid as the weighted sums ``(Q_cart.flatten()[inds_cart] * cs_cart).sum(1)``."""
    Q_cart = Q_cart.flatten()        
    Q_polar = (Q_cart[inds_cart]*cs_cart).sum(1)
    
    return Q_polar
    
def Polar2Cart(Q_polar,inds_polar,cs_polar):
    
    """Return values on the Cartesian grid as the weighted sums ``(Q_polar[inds_polar] * cs_polar).sum(1)``."""
    Q_cart = (Q_polar[inds_polar]*cs_polar).sum(1)

    return Q_cart    
        
def Cart2Polar_interp(Q_cart,XYs_cart,XYs_polar,method='cubic'):

    """Intended to interpolate ``Q_cart`` onto the polar points with ``scipy.interpolate.griddata``.

    The body uses undefined names ``XY_cart`` and ``XY_polar`` (the parameters are ``XYs_cart``, ``XYs_polar``), so calling it raises NameError.
    """
    Q_cart = Q_cart.flatten()
    Q_polar = interpolate.griddata(XY_cart,Q_cart,XY_polar,method=method) 

    return Q_polar         
        
def Polar2Cart_interp(Q_Polar,XYs_polar,XYs_cart,method='cubic'):
            
    """Intended to interpolate polar values onto the Cartesian points with ``scipy.interpolate.griddata``.

    The body uses undefined names ``XY_polar``, ``Q_polar`` and ``XY_cart`` (the parameters are ``Q_Polar``, ``XYs_polar``, ``XYs_cart``), so calling it raises NameError.
    """
    Q_cart = interpolate.griddata(XY_polar,Q_polar,XY_cart,method=method) 
    
    return Q_cart       
    

