"""Write sequence instruction lists as a Python file or as a JSON encoding."""
import json
from psdaq.seq.seq import *

#  The output is only usable by XPM tools
def seq_write_py(instr, output):
    #  Write the python file for direct programming
    """Write each instruction's string form on its own line to '<output>.py' (after a blank first line).

    A code comment says the output "is only usable by XPM tools".
    """
    fname = output+'.py'
    f = open(fname,'w')
    #    f.write('from tools.seq import *\n')
    f.write('\n')

    for i in instr:
        f.write('{}\n'.format(i))

    f.close()

#  The output is usable by TPG tools
def seq_write_json(name, instr, output):

    """Execute the instructions as Python, expand them and write {'title', 'descset': None, 'encoding'} to '<output>.json'.

    The encoding is the instruction count followed by each instruction's `encoding()`.
    The code calls ``preproc(..., isTPG=True)``, but `preproc` takes no `isTPG` argument,
    so this raises TypeError.
    """
    seqstr = 'from psdaq.seq.seq import *\n'
    for i in instr:
        seqstr += f'{i}\n'

    config = {'title':'TITLE', 'descset':None, 'instrset':None, 'seqcodes':None}
    exec(compile(seqstr, name, 'exec'), {}, config)

    instrset = preproc(config['instrset'], isTPG=True)

    encoding = [len(instrset)]
    for i in instrset:
        encoding = encoding + i.encoding()

    #  Populate a new dictionary with only the fields we want
    cc = {'title'   :name,
          'descset' :None,
          'encoding':encoding}

    open(output+'.json','w').write(json.dumps(cc))

