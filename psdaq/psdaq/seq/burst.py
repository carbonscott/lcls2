#
# sequence script must create 3 variables {title, descset, instrset}
#
"""Sequence description 'Burst' (defines `title`, `descset`, `instrset`).

For i in 0-3 it adds four ControlRequest/FixedRateSync(marker=0, occ=i+1) groups with
masks 0xf, 0xe, 0xc, 0x8 shifted by 4*i and conditional repeat counts 1, 1, 3, 7, then
branches back to line 0.
"""
from psdaq.seq.seq import *

title = 'Burst'

sync_marker = 6
    
#  Insert global sync instruction (1Hz?)
instrset = []
instrset.append(FixedRateSync(marker=sync_marker,occ=1))

for i in range(4):
    sh = i*4

    b0 = len(instrset)
    instrset.append(ControlRequest(0xf<<sh))
    instrset.append(FixedRateSync(marker=0,occ=i+1))
    instrset.append(Branch.conditional(line=b0, counter=0, value=1))

    b0 = len(instrset)
    instrset.append(ControlRequest(0xe<<sh))
    instrset.append(FixedRateSync(marker=0,occ=i+1))
    instrset.append(Branch.conditional(line=b0, counter=0, value=1))
    
    b0 = len(instrset)
    instrset.append(ControlRequest(0xc<<sh))
    instrset.append(FixedRateSync(marker=0,occ=i+1))
    instrset.append(Branch.conditional(line=b0, counter=0, value=3))

    b0 = len(instrset)
    instrset.append(ControlRequest(0x8<<sh))
    instrset.append(FixedRateSync(marker=0,occ=i+1))
    instrset.append(Branch.conditional(line=b0, counter=0, value=7))

instrset.append(Branch.unconditional(line=0))

descset = []
for j in range(16):
    descset.append('%d x %fus'%(2**(1+(j%4)),1.08*(j/4)))

