"""Helpers to choose a center and radius in an image, fold selected image quadrants into one quadrant, and unfold a quadrant back into a full image."""
import numpy as np

def GetCenterR(img,X0=None,Y0=None,Rmax=None):

    """Return ``(X0, Y0, Rmax)``: the given values, or by default the image center (integer half of each dimension) and the largest radius that fits from the center to the right and bottom edges."""
    if X0 is None:
        X0 = img.shape[1]//2
    if Y0 is None:
        Y0 = img.shape[0]//2   
    if Rmax is None:      
        Rmax = min(img.shape[1]-X0, img.shape[0]-Y0)
            
    return X0, Y0, Rmax


def GetQuadrant(img,X0,Y0,Rmax,s=[1,1,1,1]):

    """Return the sum of the selected image quadrants around (``X0``, ``Y0``), each flipped into a common orientation and of size Rmax x Rmax, flipped up-down at the end.

    ``s`` holds four 0/1 flags for the upper-right, upper-left, lower-left and lower-right quadrants; the slices differ by one pixel for odd and even image widths.
    """
    i = 0
    Qs = np.zeros((s[0]+s[1]+s[2]+s[3], Rmax, Rmax))
    
    if img.shape[1] % 2 == 1:
        if s[0] == 1:
            Qs[i] = img[Y0-Rmax+1:Y0+1,X0:X0+Rmax]; i += 1
        if s[1] == 1:
            Qs[i] = np.fliplr(img[Y0-Rmax+1:Y0+1,X0-Rmax+1:X0+1]); i += 1
        if s[2] == 1:
            Qs[i] = np.flipud(np.fliplr(img[Y0:Y0+Rmax,X0-Rmax+1:X0+1])); i += 1            
        if s[3] == 1:
            Qs[i] = np.flipud(img[Y0:Y0+Rmax,X0:X0+Rmax])
        
    elif img.shape[1] % 2 == 0:
        if s[0] == 1:
            Qs[i] = img[Y0-Rmax:Y0,X0:X0+Rmax]; i += 1 
        if s[1] == 1:
            Qs[i] = np.fliplr(img[Y0-Rmax:Y0,X0-Rmax:X0]); i += 1
        if s[2] == 1:
            Qs[i] = np.flipud(np.fliplr(img[Y0:Y0+Rmax,X0-Rmax:X0])); i += 1   
        if s[3] == 1:
            Qs[i] = np.flipud(img[Y0:Y0+Rmax,X0:X0+Rmax])        

    Q = np.flipud(Qs.sum(axis=0))
        
    return Q
    
def Quadrant2img(Q):
    """Return a full image built from quadrant ``Q``: ``Q`` is flipped up-down, mirrored left-right next to itself and then mirrored up-down below."""
    Q = np.flipud(Q)
    Q = np.concatenate((np.fliplr(Q),Q),axis=1)
    img = np.concatenate((Q,np.flipud(Q)),axis=0)  
    return img
      
    
    
    
    
    
