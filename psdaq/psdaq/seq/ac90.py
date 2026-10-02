"""Sequence description 'AC90': after an AC sync on timeslot 2 (marker 4, comment '1Hz AC'), issue ControlRequest(1) on timeslots 6, 4 and 2 in turn and loop.

Defines `instrset`, `descset` (['90Hz']) and `title`.
"""
from psdaq.seq.seq import *

sync_marker = 4  # 1Hz AC
    
instrset = []
#  Insert global sync instruction for timeslot 1
instrset.append(ACRateSync(timeslotm=(1<<1),marker=sync_marker,occ=1))

instrset.append(ControlRequest(1))
instrset.append(ACRateSync(timeslotm=(1<<5),marker=0,occ=1))
instrset.append(ControlRequest(1))
instrset.append(ACRateSync(timeslotm=(1<<3),marker=0,occ=1))
instrset.append(ControlRequest(1))
instrset.append(ACRateSync(timeslotm=(1<<1),marker=0,occ=1))
instrset.append(Branch.unconditional(line=1))

descset = ['90Hz']

title = 'AC90'
