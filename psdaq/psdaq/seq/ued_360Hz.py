# UED 360Hz Hz setup
"""Sequence description (header comment: "UED 360Hz Hz setup") defining `seqcodes` and `instrset`.

The file has no imports; it uses `ACRateSync`, `FixedRateSync`, `ControlRequest` and
`Branch` from `psdaq.seq.seq`. Instructions: ACRateSync(0x3f, '60H', 1), 463 '500kH'
markers, ControlRequest([0]), 463 '500kH' markers, branch to line 0.
"""
seqcodes = {0: '360 Hz VTS1'}

instrset = []
instrset.append( ACRateSync( 0x3f, "60H", occ=1) )
instrset.append( FixedRateSync( marker="500kH", occ=463 ) )
instrset.append( ControlRequest([0]) )
instrset.append( FixedRateSync( marker="500kH", occ=463 ) )
instrset.append( Branch.unconditional(0) )
