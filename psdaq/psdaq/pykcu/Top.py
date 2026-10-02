#!/usr/bin/env python3
##############################################################################
## This file is part of 'EPIX'.
## It is subject to the license terms in the LICENSE.txt file found in the 
## top-level directory of this distribution and at: 
##    https://confluence.slac.stanford.edu/display/ppareg/LICENSE.html. 
## No part of 'EPIX', including this file, 
## may be copied, modified, propagated, or distributed except according to 
## the terms contained in the LICENSE.txt file.
##############################################################################

"""pyrogue device classes for the KCU register map used by `psdaq.pykcu.pykcu`."""
import time
import struct

import rogue
import rogue.hardware.axi

import pyrogue as pr
import surf.axi                     as axi

class TDetSemi(pr.Device):
    """pyrogue Device with one 128-bit read-only register 'rttBlock' at offset 0x50."""
    def __init__(self,
                 name        = 'TDetSemi',
                 description = 'Fake camera',
                 **kwargs):
        super().__init__(
            name        = name,
            description = description,
            **kwargs
        )

        self.add(pr.RemoteVariable(
            name      = 'rttBlock',
            offset    = 0x50,
            bitSize   = 32*4,
            mode      = 'RO'
        ))

    def getRTT(self):
        """Read 'rttBlock' and return four pairs, one per 32-bit word (lane 0-3).

        Returns
        -------
        tuple of tuple
            ``((bits 0-15, bits 16-27), ...)`` of each word; `psdaq.pykcu.pykcu` stores them as
            'FullTT' and 'nFullTT'.
        """
        v = self.rttBlock.get()

        def fullToTrig(lane,v=v):
            return (v>>(32*lane))&0xffff
        def nfullToTrig(lane,v=v):
            return (v>>(32*lane+16))&0xfff

        return ( (fullToTrig(0),nfullToTrig(0)),
                 (fullToTrig(1),nfullToTrig(1)),
                 (fullToTrig(2),nfullToTrig(2)),
                 (fullToTrig(3),nfullToTrig(3)) )

class TDetTiming(pr.Device):
    """pyrogue Device with 32-bit read-only registers 'rxRefClk' (offset 0x10) and 'txRefClk' (offset 0x28)."""
    def __init__(self,
                 name        = 'TDetTiming',
                 description = 'Template timed detector',
                 **kwargs):
        super().__init__(
            name        = name,
            description = description,
            **kwargs
        )

        self.add(pr.RemoteVariable(
            name      = 'rxRefClk',
            offset    = 0x10,
            bitSize   = 32,
            mode      = 'RO'
        ))

        self.add(pr.RemoteVariable(
            name      = 'txRefClk',
            offset    = 0x28,
            bitSize   = 32,
            mode      = 'RO'
        ))

    def getClkRates(self):
        """Read 'rxRefClk' and 'txRefClk', sleep 1 s, read them again and return the scaled differences.

        Returns
        -------
        tuple of float
            ``((tx_after - tx_before) * 16e-6, (rx_after - rx_before) * 16e-6)``; counter wrap-around
            is not handled.
        """
        rxp = self.rxRefClk.get()
        txp = self.txRefClk.get()
        time.sleep(1)
        rxn = self.rxRefClk.get()
        txn = self.txRefClk.get()
        return ( (txn-txp)*16.e-6, (rxn-rxp)*16.e-6 )

class QSFPMonitor(pr.Device):
    """pyrogue Device with the registers 'page', 'TmpVccBlock', 'RxPwrBlock', 'TxBiasBlock', 'BaseIdBlock', 'DateBlock' and 'DiagnType'.

    Each register offset is a byte index shifted left by 2 (e.g. 'page' at ``127<<2``).
    """
    def __init__(self,
                 name        = 'QSFPMonitor',
                 description = 'QSFP monitoring and diagnostics',
                 **kwargs):
        super().__init__(
            name        = name,
            description = description,
            **kwargs
        )

        self.add(pr.RemoteVariable(
            name      = 'page',
            offset    = (127<<2),
            bitSize   = 8,
            verify    = False,
            mode      = 'RW'
        ))

        self.add(pr.RemoteVariable(
            name      = 'TmpVccBlock',
            offset    = (22<<2),
            bitSize   = 32*6,
            mode      = 'RO'
        ))

        self.add(pr.RemoteVariable(
            name      = 'RxPwrBlock',
            offset    = (34<<2),
            bitSize   = 32*8,
            mode      = 'RO'
        ))

        self.add(pr.RemoteVariable(
            name      = 'TxBiasBlock',
            offset    = (42<<2),
            bitSize   = 32*8,
            mode      = 'RO'
        ))

        self.add(pr.RemoteVariable(
            name      = 'BaseIdBlock',
            offset    = (128<<2),
            bitSize   = 32*3,
            mode      = 'RO'
        ))

        self.add(pr.RemoteVariable(
            name      = 'DateBlock',
            offset    = (212<<2),
            bitSize   = 32*6,
            mode      = 'RO'
        ))

        self.add(pr.RemoteVariable(
            name      = 'DiagnType',
            offset    = (220<<2),
            bitSize   = 32,
            mode      = 'RO'
        ))


    def getDate(self):
        """Write 0 to 'page', read 'DateBlock' and return its bytes as a date string.

        Returns
        -------
        str
            'c2c3/c4c5/20c0c1', where cK is the low byte of 32-bit word K taken as a character.
        """
        self.page.set(0)
        v = self.DateBlock.get()
        def toChar(sh,w=v):
            return (w>>(32*sh))&0xff

        r = '{:c}{:c}/{:c}{:c}/20{:c}{:c}'.format(toChar(2),toChar(3),toChar(4),toChar(5),toChar(0),toChar(1))
        return r

    def getRxPwr(self):  #mW
        #self.page.set(0)
        """Read 'RxPwrBlock' and return four values (lanes 0-3); the code comment gives the unit as mW.

        Each value is a 16-bit number made from the low bytes of words 2*lane and 2*lane+1 (via
        ``struct`` with native byte order) times 0.0001.
        """
        v = self.RxPwrBlock.get()

        def word(a,o):
            return (a >> (32*o))&0xff
        def tou16(a,o):
            return struct.unpack('H',struct.pack('BB',word(a,o+1),word(a,o)))[0]
        def pwr(lane,v=v):
            p = tou16(v,2*lane)
            return p * 0.0001
                
        return (pwr(0),pwr(1),pwr(2),pwr(3))


    def getTxBiasI(self):  #mA
        #self.page.set(0)
        """Read 'TxBiasBlock' and return four values (lanes 0-3); the code comment gives the unit as mA.

        Each value is a 16-bit number made from the low bytes of words 2*lane and 2*lane+1 (via
        ``struct`` with native byte order) times 0.002.
        """
        v = self.TxBiasBlock.get()

        def word(a,o):
            return (a >> (32*o))&0xff
        def tou16(a,o):
            return struct.unpack('H',struct.pack('BB',word(a,o+1),word(a,o)))[0]
        def pwr(lane,v=v):
            p = tou16(v,2*lane)
            return p * 0.002
                
        return (pwr(0),pwr(1),pwr(2),pwr(3))

class I2cBus(pr.Device):
    """pyrogue Device with an 8-bit 'select' register at 0x0 and `QSFPMonitor` children 'QSFP0' (offset 0x400) and 'QSFP1' (offset 0x800)."""
    def __init__(self,
                 name        = 'I2cBus',
                 description = 'Local bus',
                 **kwargs):
        super().__init__(
            name        = name,
            description = description,
            **kwargs
        )

        self.add(pr.RemoteVariable(
            name      = 'select',
            offset    = 0x0,
            bitSize   = 8,
            verify    = False,
            mode      = 'RW',
        ))

        self.add(QSFPMonitor(
            name   = 'QSFP0',
            offset = 0x400
        ))

        self.add(QSFPMonitor(
            name   = 'QSFP1',
            offset = 0x800
        ))

    def selectDevice(self, device):
        """Write a bit mask to 'select' built from substrings found in `device`.

        'QSFP0' sets bit 4, 'QSFP1' sets bit 1 and 'SI570' sets bit 2; if none match, 0 is written.

        Parameters
        ----------
        device : str or container of str
            Tested with ``in`` for each name.
        """
        idev = 0
        if 'QSFP0' in device:
            idev |= (1<<4)
        if 'QSFP1' in device:
            idev |= (1<<1)
        if 'SI570' in device:
            idev |= (1<<2)
        self.select.set(idev)

class Top(pr.Device):

    """pyrogue Device (default name 'KCU') holding `TDetSemi` at 0x00A00000, `TDetTiming` at 0x00C00000 and `I2cBus` at 0x00E00000, all on `memBase`."""
    def __init__(   self,       
            name        = "KCU",
            description = "Container for KCU",
            memBase     = 0,
            **kwargs):
        super().__init__(name=name, description=description, **kwargs)
        
        self.add(TDetSemi( 
            memBase = memBase,
            offset  = 0x00A00000, 
            expand  = False,
        ))

        self.add(TDetTiming( 
            memBase = memBase,
            offset  = 0x00C00000, 
            expand  = False,
        ))

        self.add(I2cBus( 
            memBase = memBase,
            offset  = 0x00E00000, 
            expand  = False,
        ))

