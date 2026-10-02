"""Add Python directories of the '$SUBMODULEDIR/epix-hr-single-10k/' submodule to the pyrogue library path when imported.

Directories passed to `pr.addLibraryPath` (an exception adding the ePixViewer path is caught and printed): 'firmware/submodules/axi-pcie-core/python', 'firmware/submodules/epix-hr-core/python', 'firmware/submodules/surf/python', 'firmware/python', 'software/python', 'firmware/submodules/l2si-core/python', 'firmware/submodules/lcls-timing-core/python', 'firmware/submodules/ePixViewer/python'.
The `sys.path` entry it appends is the literal string '%s/firmware/python', because the
code calls ``.format`` on a '%s' template.
"""
import pyrogue as pr
import os
import sys

submoduledir = os.environ["SUBMODULEDIR"]

top_level = submoduledir + "/epix-hr-single-10k/"

sys.path.append("%s/firmware/python".format(top_level))

pr.addLibraryPath(top_level + 'firmware/submodules/axi-pcie-core/python')
pr.addLibraryPath(top_level + 'firmware/submodules/epix-hr-core/python')
pr.addLibraryPath(top_level + 'firmware/submodules/surf/python')
pr.addLibraryPath(top_level + 'firmware/python')
pr.addLibraryPath(top_level + 'software/python')
pr.addLibraryPath(top_level + 'firmware/submodules/l2si-core/python')
pr.addLibraryPath(top_level + 'firmware/submodules/lcls-timing-core/python')
try :
    pr.addLibraryPath(top_level+'firmware/submodules/ePixViewer/python')
except :
    print("pr.addLibraryPath Import ePixViewer failed")
    pass
