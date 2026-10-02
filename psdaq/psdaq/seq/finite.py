"""Sequence description 'BurstTest' that runs the burst groups once, then a CheckPoint and a branch to itself.

For i in 0-3: ControlRequest masks 0xf, 0xe, 0xc, 0x8 shifted by 4*i, each with
FixedRateSync(marker=0, occ=i+1) and conditional repeats 1, 1, 3, 7. The instructions are
printed at import.
"""
from psdaq.seq.seq import *

sync_marker = 6
    
instrset = []
#  Insert global sync instruction (1Hz?)
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

#  Notify
instrset.append(CheckPoint())

#  Loop here indefinitely
b0 = len(instrset)
instrset.append(Branch.unconditional(line=b0))

descset = []
for j in range(16):
    descset.append('%d x %fus'%(2**(1+(j%4)),1.08*(j/4)))

i=0
for instr in instrset:
    print('Put instruction(%d): '%i),
    print(instr.print_())
    i += 1

title = 'BurstTest'
    
