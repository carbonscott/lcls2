"""Add Python directories of the '$SUBMODULEDIR/epix-quad/' submodule to the pyrogue library path when imported.

Directories passed to `pr.addLibraryPath`: 'firmware/submodules/axi-pcie-core/python', 'firmware/submodules/surf/python', 'firmware/python', 'software/python'.
The `sys.path` entry it appends is the literal string '%s/firmware/python', because the
code calls ``.format`` on a '%s' template.
"""
import pyrogue as pr
import os
import sys

submoduledir = os.environ["SUBMODULEDIR"]

top_level = submoduledir + "/epix-quad/"

sys.path.append("%s/firmware/python".format(top_level))

pr.addLibraryPath(top_level + 'firmware/submodules/axi-pcie-core/python')
pr.addLibraryPath(top_level + 'firmware/submodules/surf/python')
pr.addLibraryPath(top_level + 'firmware/python')
pr.addLibraryPath(top_level + 'software/python')
