"""Helpers that decode XPM link-ID words into (device type, host/address) names, and encode a local timing transmitter ID."""
import socket
from psdaq.cas.pvedit import *

def atcaIp(v):
    """Return the string '10.0.<(v>>12)&0xf>.<100+((v>>8)&0xf)>' built from bits of `v`."""
    return '10.0.{:}.{:}'.format((v>>12)&0xf,100+((v>>8)&0xf))

def hostName(v):
    """Return a short host name for the IP '172.21.<(v>>8)&0xff>.<v&0xff>'.

    The reverse-DNS name is cut at the first '.' and then at the last '-'; if the lookup
    fails, ``'{:x}'.format(v)`` is returned.
    """
    ip = '172.21.{:d}.{:d}'.format((v>>8)&0xff,(v>>0)&0xff)
    try:
        name = socket.gethostbyaddr(ip)[0].split('.')[0].split('-')[-1]
    except:
        name = '{:x}'.format(v)
    return name

def nameLinkXpm(v):
    """Return ``('XPM:<(v>>16)&0xff>', atcaIp(v))``."""
    return ('XPM:{:}'.format((v>>16)&0xff), atcaIp(v))

def nameLinkDti(v):
    """Return ``('DTI', atcaIp(v))``."""
    return ('DTI', atcaIp(v))

def nameLinkDrp(v):
    """Return ``('TDetSim', hostName(v))``."""
    return ('TDetSim', hostName(v))

def nameLinkHsd(v):
    """Return ``('HSD', '<hostName(v)>.<(v>>16)&0xff as 2 hex digits>')``."""
    return ('HSD', '{:}.{:02X}'.format(hostName(v),(v>>16)&0xff))

def nameLinkTDet(v):
    """Return ``('TDetSim', hostName(v))``."""
    return ('TDetSim', hostName(v))

def nameLinkWave8(v):
    """Return ``('Wave8', hostName(v))``."""
    return ('Wave8', hostName(v))

def nameLinkOpal(v):
    """Return ``('Opal', hostName(v))``."""
    return ('Opal', hostName(v))

def nameLinkTimeTool(v):
    """Return ``('TimeTool', hostName(v))``."""
    return ('TimeTool', hostName(v))

def nameLinkEpixQuad(v):
    """Return ``('EpixQuad', hostName(v))``."""
    return ('EpixQuad', hostName(v))

def nameLinkEpixHR2x2(v):
    """Return ``('EpixHR2x2', hostName(v))``."""
    return ('EpixHR2x2', hostName(v))

def nameLinkEpix100(v):
    """Return ``('Epix100', hostName(v))``."""
    return ('Epix100', hostName(v))

def nameLinkPiranha4(v):
    """Return ``('Piranha4', hostName(v))``."""
    return ('Piranha4', hostName(v))

def nameLinkEpixM320(v):
    """Return ``('ePixM320', hostName(v))``."""
    return ('ePixM320', hostName(v))

def nameLinkEpixUHR(v):
    """Return ``('epixUHR', hostName(v))``."""
    return ('epixUHR', hostName(v))

def nameLinkHREncoder(v):
    """Return ``('HREncoder', hostName(v))``."""
    return ('HREncoder', hostName(v))

def nameLinkJungfrau(v):
    """Return ``('Jungfrau', hostName(v))``."""
    return ('Jungfrau', hostName(v))

def nameLinkEpixUHR3x2(v):
    """Return ``('EpixUHR3x2', hostName(v))``."""
    return ('EpixUHR3x2', hostName(v))

timDevType = {}
timDevType['xpm']        = 0xff
timDevType['dti']        = 0xfe
timDevType['drp']        = 0xfd
timDevType['hsd']        = 0xfc
timDevType['tdet']       = 0xfb
timDevType['wave8']      = 0xfa
timDevType['opal']       = 0xf9
timDevType['timetool']   = 0xf8
timDevType['epixquad']   = 0xf7
timDevType['epixhr2x2']  = 0xf6
timDevType['epix100']    = 0xf5
timDevType['piranha4']   = 0xf4
timDevType['epixm320']   = 0xf3
timDevType['epixUHR']    = 0xf2
timDevType['hrencoder']  = 0xf1
timDevType['jungfrau']   = 0xf0
timDevType['epixuhr3x2'] = 0xef


linkType = {}
linkType[0xff] = nameLinkXpm
linkType[0xfe] = nameLinkDti
linkType[0xfd] = nameLinkDrp
linkType[0xfc] = nameLinkHsd
linkType[0xfb] = nameLinkTDet
linkType[0xfa] = nameLinkWave8
linkType[0xf9] = nameLinkOpal
linkType[0xf8] = nameLinkTimeTool
linkType[0xf7] = nameLinkEpixQuad
linkType[0xf6] = nameLinkEpixHR2x2
linkType[0xf5] = nameLinkEpix100
linkType[0xf4] = nameLinkPiranha4
linkType[0xf3] = nameLinkEpixM320
linkType[0xf2] = nameLinkEpixUHR
linkType[0xf1] = nameLinkHREncoder
linkType[0xf0] = nameLinkJungfrau
linkType[0xef] = nameLinkEpixUHR3x2

def xpmLinkId(value):
    """Decode a link-ID word into a (type, name) tuple.

    The top byte selects a `nameLink*` function from `linkType`; 0x10080 gives
    ('Fanout/', 'Loopback'); anything else gives ('undef', <value in hex>).

    Returns
    -------
    tuple of str
        (type name, host or address string).
    """
    itype = (value>>24)&0xff
    names = None
    if itype in linkType:
        names = linkType[itype](value)
    elif value==0x10080:
        names = ('Fanout/','Loopback')
    else:
        names = ('undef','{:x}'.format(value))
    return names

def timTxId(timDevTypeStr):
    """Return a transmitter ID word for device type `timDevTypeStr` (a key of `timDevType`).

    For type codes below that of 'hsd' the result is ``(code << 24) | (x << 8) | y`` from
    the local host's 172.21.x.y address (from `socket.getaddrinfo`; the last address is
    used if none matches). For 'xpm', 'dti', 'drp' and 'hsd' it returns 0.
    """
    tdt = timDevType[timDevTypeStr]
    if tdt<timDevType['hsd']:
        info = socket.getaddrinfo(socket.gethostname(),None,0,0,socket.IPPROTO_UDP)
        for a in info:
            ip = a[4][0].split('.')
            if ip[0]=='172' and ip[1]=='21':
                break
        return (tdt<<24) | (int(ip[2])<<8) | int(ip[3])
    return 0

