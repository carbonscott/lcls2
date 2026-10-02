#
#  This code needs validation checks:
#  1.  arguments do not exceed the bit depth of the implementation
#  2.  consistent use of the branch counters (same counter isn't used within a nested loop)
#
"""Sequence-engine instruction classes, their 32-bit word encodings and a simple execution model, plus macro expansion helpers.

The header comment notes the code "needs validation checks" for argument bit depth and
conditional-counter use. Rate tables come from `psdaq.configdb.tsdef`.
"""
from psdaq.configdb.tsdef import *
import math
import logging

verbose = False
#verbose = True

def factor(n):
    """Unfinished helper: return `n` if it is at most `Instruction.maxocc` (0xfff).

    Raises ValueError if `n` exceeds maxocc squared. Otherwise it prints the prime factors
    it found and returns None.
    """
    if n <= Instruction.maxocc:
        return (n)

    if n > Instruction.maxocc * Instruction.maxocc:
        raise ValueError('factor failed: argument too large')

    primes = []
    rem = n
    for i in range(2,int(math.sqrt(n)+1)):
        while rem%i == 0:
            primes.append(i)
            rem = rem//i
        if rem == 1:
            break

    print(f'primes of {n} are {primes}')

    # Can we make two factors each less than Instruction.maxoc

class Instruction(object):

    """Base class holding the instruction argument tuple `args` (opcode first); `maxocc` is 0xfff and `maxcc` is 4."""
    maxocc = 0xfff   # max value of loop counters
    maxcc  = 4       # number of conditional counters

    def __init__(self, args):
        self.args = args

    def encoding(self):
        """Return a 7-element list: number of arguments after the opcode, then the arguments, zero-padded."""
        args = [0]*7
        args[0] = len(self.args)-1
        args[1:len(self.args)+1] = self.args
        return args

    def print_(self):
        """Return the first argument formatted as hex."""
        return f'{self.args[0]:x}'

    def __str__(self):
        return self.print_()

    # In subclasses that need address relocation
    #def address(self): 
    #def _word(self,a):

class FixedRateSync(Instruction):

    """Wait for `occ` markers of fixed-rate `marker` (a key of `FixedIntvsDict` or an index into `FixedIntvs`).

    Raises ValueError if `occ` exceeds `Instruction.maxocc`.
    """
    opcode = 0

    def __init__(self, marker, occ):
        if occ > Instruction.maxocc:
            raise ValueError('FixedRateSync called with occ={}'.format(occ))
        if marker in FixedIntvsDict:
            mk     = marker
            marker = FixedIntvsDict[mk]['marker']
            self.intv = FixedIntvsDict[mk]['intv']
        else:
            self.intv = FixedIntvs[marker]
        super(FixedRateSync, self).__init__( (self.opcode, marker, occ) )

    def _word(self):
        return int((2<<29) | ((self.args[1]&0xf)<<16) | (self.args[2]&Instruction.maxocc))
    
    def print_(self):
        """Return 'FixedRateSync(<rate name>) # occ(<occ>)'."""
        return 'FixedRateSync({}) # occ({})'.format(fixedRates[self.args[1]],self.args[2])

    def execute(self,engine):
        """Simulate: advance the instruction pointer and move `engine.frame` to the `occ`-th next multiple of the interval.

        If the frame moved, `engine.request` is cleared; bit 0 of `engine.modes` is set.
        """
        intv = self.intv
        engine.instr += 1
        step = intv*self.args[2]-(engine.frame%intv)
        if step>0:
            engine.frame  += step
            engine.request = 0
        engine.modes |= 1

class ACRateSync(Instruction):

    """Wait for `occ` AC-rate markers in the timeslots selected by bitmask `timeslotm` (at most 0x3f).

    Raises ValueError if `occ` exceeds maxocc or `timeslotm` exceeds 0x3f.
    """
    opcode = 1

    def __init__(self, timeslotm, marker, occ):
        if occ > Instruction.maxocc:
            raise ValueError('ACRateSync called with occ={}'.format(occ))
        if timeslotm > 0x3f:
            raise ValueError('ACRateSync called with timeslotm={}'.format(timeslotm))
        if marker in ACIntvsDict:
            mk     = marker
            marker = ACIntvsDict[mk]['marker']
            self.intv = ACIntvsDict[mk]['intv']
        else:
            self.intv = ACIntvs[marker]
        super(ACRateSync, self).__init__( (self.opcode, timeslotm, marker, occ) )

    def _word(self):
        return int((3<<29) | ((self.args[1]&0x3f)<<23) | ((self.args[2]&0xf)<<16) | (self.args[3]&Instruction.maxocc))

    def print_(self):
        """Return 'ACRateSync(<rate name>/0x<timeslot mask>) # occ(<occ>)'."""
        return 'ACRateSync({}/0x{:x}) # occ({})'.format(acRates[self.args[2]],self.args[1],self.args[3])
    
    def execute(self,engine):
        """Simulate: for `occ` repetitions advance `engine.frame` over AC frames until one whose timeslot is in the mask and whose ``(acframe/6) % intv`` is 0.

        Then clears `engine.request` and sets bit 1 of `engine.modes`.
        """
        intv = self.intv
        engine.instr += 1
        mask = self.args[1]&0x3f
#        print('ACRateSync: args {:}  mask {:x}  intv {:}'.format(self.args,mask,intv))
        for i in range(self.args[3]):
            while True:
                acphase = engine.frame % FixedToACFids
                engine.frame += FixedToACFids - acphase
                acframe = int(engine.frame/FixedToACFids)
                ts = acframe % 6
#                print('  frame {:}  ts {:}'.format(engine.acframe,ts))
                if ((1<<ts)&mask)!=0 and (int(acframe/6)%intv)==0:
                    break
#                engine.frame += FixedToACFids

        engine.request = 0
        engine.modes  |= 2

class Jump(Instruction):

    """Branch instruction: unconditional (opcode, line) or conditional (opcode, line, counter, value).

    Raises ValueError if the counter exceeds 3 or the value exceeds maxocc.
    """
    opcode = 2

    def __init__(self, args):
        if len(args)>2:
            if args[2] > 0x3:
                raise ValueError('Jump called with ctr={}'.format(args[2]))
            if args[3] > Instruction.maxocc:
                raise ValueError('Jump called with occ={}'.format(args[3]))
        super(Jump, self).__init__(args)

    def _word(self, a = None):
        if a is None:
            w = self.args[1] & 0x7ff
        else:
            w = a & 0x7ff
        if len(self.args)>2:
            w = ((self.args[2]&0x3)<<27) | (1<<24) | ((self.args[3]&Instruction.maxocc)<<12) | w
        return int(w)

    @classmethod
    def unconditional(cls, line):
        """Return an unconditional `Jump` to `line`."""
        return cls((cls.opcode, line))

    @classmethod
    def conditional(cls, line, counter, value):
        """Return a `Jump` to `line` that repeats until conditional counter `counter` equals `value`."""
        return cls((cls.opcode, line, counter, value))

    def address(self):
        """Return the target line."""
        return self.args[1]

    def print_(self):
        """Return 'Jump unconditional to line N' or 'Jump to line N until ctrC=V'."""
        if len(self.args)==2:
            return 'Jump unconditional to line {}'.format(self.args[1])
        else:
            return 'Jump to line {} until ctr{}={}'.format(self.args[1],self.args[2],self.args[3])

    def execute(self,engine):
        """Simulate the branch.

        Unconditional: jump to the target (and set `engine.done` if it targets itself).
        Conditional: if the counter equals the value, reset it and continue; else increment
        it and jump.
        """
        if len(self.args)==2:
            if engine.instr==self.args[1]:  # branch to self
                engine.done = True
            engine.instr = self.args[1]
        else:
            if engine.ccnt[self.args[2]]==self.args[3]:
                engine.instr += 1
                engine.ccnt[self.args[2]] = 0
            else:
                engine.instr = self.args[1]
                engine.ccnt[self.args[2]] += 1
    
class CheckPoint(Instruction):

    """Checkpoint instruction (encoded as ``1 << 29``)."""
    opcode = 3
    
    def __init__(self):
        super(CheckPoint, self).__init__((self.opcode,))

    def _word(self):
        return int((1<<29))

    def print_(self):
        """Return 'CheckPoint'."""
        return 'CheckPoint'

    def execute(self,engine):
        """Simulate: advance the instruction pointer only."""
        engine.instr += 1

class BeamRequest(Instruction):

    """Request instruction carrying a `charge` value (encoded as ``(4 << 29) | charge``)."""
    opcode = 4
    
    def __init__(self, charge):
        super(BeamRequest, self).__init__((self.opcode, charge))

    def _word(self):
        return int((4<<29) | self.args[1])

    def print_(self):
        """Return 'BeamRequest charge <charge>'."""
        return 'BeamRequest charge {}'.format(self.args[1])

    def execute(self,engine):
        """Simulate: set ``engine.request = (charge << 16) | 1`` and advance."""
        engine.request = (self.args[1]<<16) | 1
        engine.instr += 1

class ControlRequest(Instruction):

    """Request instruction with a bit word; a list argument is converted to a word with those bits set."""
    opcode = 5
    
    def __init__(self, word):
        if isinstance(word,list):
            v = 0
            for w in word:
                v |= (1<<w)
        else:
            v = word
        super(ControlRequest, self).__init__((self.opcode, v))
 
    def _word(self):
        return int((4<<29) | self.args[1])

    def print_(self):
        """Return 'ControlRequest word 0x<word> [<set bit numbers>]'."""
        codes = []
        w = self.args[1]
        code = 0
        while w:
            if w&1:
                codes.append(code)
            w >>= 1
            code += 1

        return f'ControlRequest word 0x{self.args[1]:x} {codes}'

    def execute(self,engine):
        """Simulate: set `engine.request` to the word and advance."""
        engine.request = self.args[1]
        engine.instr += 1

class Call(Instruction):

    """Subroutine call to `line` (encoded as ``(5 << 29) | (addr & 0x7ff)``)."""
    opcode = 6
    
    def __init__(self, line):
        super(Call, self).__init__((self.opcode,line))

    def _word(self,a):
        return int((5<<29) | (a&0x7ff))

    def address(self):
        """Return the call target line."""
        return self.args[1]

    def print_(self):
        """Return 'Call 0x<line>'."""
        return f'Call 0x{self.args[1]:x}'

    def execute(self,engine):
        """Simulate: save the next instruction as `engine.returnaddr` and jump to the target."""
        engine.returnaddr = engine.instr+1
        engine.instr = self.args[1]

class Return(Instruction):

    """Subroutine return (encoded as ``(5 << 29) | (1 << 12)``)."""
    opcode = 7

    def __init__(self):
        super(Return, self).__init__((self.opcode,))
 
    def _word(self):
        return int((5<<29) | (1<<12))

    def print_(self):
        """Return 'Return'."""
        return f'Return'

    def execute(self,engine):
        """Simulate: jump to `engine.returnaddr` and clear it; raises ValueError if it is None."""
        if engine.returnaddr is None:
            raise ValueError(f'engine.returnaddr is None')
        engine.instr = engine.returnaddr
        engine.returnaddr = None

class Upper(Instruction):

    """Instruction carrying the upper address bits of `line` (encoded as ``(6 << 29) | (addr >> 11)``)."""
    opcode = 8

    def __init__(self, line):
        super(Upper, self).__init__((self.opcode, line))
 
    def address(self):
        """Return the stored line."""
        return self.args[1]

    def _word(self, a=None):
        if a is None:
            w = int((6<<29) | (self.args[1]>>11))
        else:
            w = int((6<<29) | (a>>11))
        return w

    def print_(self):
        """Return 'Upper <line >> 11 in hex>'."""
        return f'Upper {(self.args[1]>>11):x}'

    def execute(self,engine):
        #  Simulation doesn't really do anything with this
        """Simulate: store the line in `engine.upper` and advance."""
        engine.upper = self.args[1]
        engine.instr += 1

#
#  Macro instructions
#
class Macro(Instruction):

    """Base class for macro instructions that must be expanded by `preproc` before encoding."""
    def __init__(self, args):
        super(Macro, self).__init__(args)

    def _word(self):
        raise RuntimeError(f'Attempted encoding of macro Wait({self.args})')
    
    def execute(self,engine):
        """Raise RuntimeError; macros cannot be simulated."""
        raise RuntimeError(f'Attempting to simulate macro Wait({self.args})')


class Wait(Macro):

    """Macro for a fixed-rate wait longer than maxocc; `marker` None selects the marker whose interval is 1."""
    opcode = -1

    def __init__(self, marker, occ):
        if marker is None:
            self.intv = 1
            for k,v in FixedIntvsDict.items():
                if v["intv"]==self.intv:
                    marker = v["marker"]
                    break
        elif marker in FixedIntvsDict:
            mk     = marker
            marker = FixedIntvsDict[mk]['marker']
            self.intv = FixedIntvsDict[mk]['intv']
        else:
            self.intv = FixedIntvs[marker]
        super(Wait, self).__init__( (self.opcode, marker, occ) )

    def print_(self):
        """Return 'Wait(<rate name>) # occ(<occ>)'."""
        return f'Wait({fixedRates[self.args[1]]}) # occ({self.args[2]})'

    #  Create the replacement instructions for this macro
    def replace(self, cc, line):
        """Return the `FixedRateSync` instructions that implement this wait.

        With counter `cc` and at least 3 full blocks: one maxocc sync, an `Upper(line)` and a
        conditional Jump back to `line` repeating n-1 times; otherwise n maxocc syncs. A sync
        for the remainder is appended if non-zero.
        """
        marker = self.args[1]
        occ    = self.args[2]
        n = int(occ/Instruction.maxocc)
        rem = occ - n*Instruction.maxocc
        if cc is None or n < 3:
            l = [FixedRateSync(marker,occ=Instruction.maxocc)]*n
        else:
            l = [FixedRateSync(marker,occ=Instruction.maxocc),
                 Upper(line),
                 Jump.conditional( line, cc, n-1 )]
        if rem > 0:
            l.append(FixedRateSync(marker,occ=rem))
        return l
            
class WaitA(Macro):

    """Macro for an AC-rate wait longer than maxocc; `marker` None selects the marker whose interval is 1.

    Raises ValueError if `timeslotm` exceeds 0x3f.
    """
    opcode = -2

    def __init__(self, timeslotm, marker, occ):
        if timeslotm > 0x3f:
            raise ValueError('WaitA called with timeslotm={}'.format(timeslotm))
        if marker is None:
            self.intv = 1
            for k,v in ACIntvsDict.items():
                if v["intv"]==self.intv:
                    marker = v["marker"]
                    break
        elif marker in ACIntvsDict:
            mk        = marker
            marker    = ACIntvsDict[mk]['marker']
            self.intv = ACIntvsDict[mk]['intv']
        else:
            self.intv = ACIntvs[marker]
        super(WaitA, self).__init__( (self.opcode, timeslotm, marker, occ) )

    def print_(self):
        """Return 'WaitA(0x<mask>,<rate name>) # occ(<occ>)'."""
        return f'WaitA(0x{self.args[1]:x},{acRates[self.args[2]]}) # occ({self.args[3]})'

    #  Create the replacement instructions for this macro
    def replace(self, cc, line):
        """Return the `ACRateSync` instructions that implement this wait (same scheme as `Wait.replace`)."""
        timeslotm = self.args[1]
        marker    = self.args[2]
        occ       = self.args[3]
        n = int(occ/Instruction.maxocc)
        rem = occ - n*Instruction.maxocc
        if cc is None or n < 3:
            l = [ACRateSync(timeslotm,marker,occ=Instruction.maxocc)]*n
        else:
            l = [ACRateSync(timeslotm,marker,occ=Instruction.maxocc),
                 Upper(line),
                 Jump.conditional( line, cc, n-1 )]
        if rem > 0:
            l.append(ACRateSync(timeslotm,marker,occ=rem))
        return l

class Branch(Macro):

    """Macro branch (unconditional or conditional) expanded to `Upper` plus `Jump`."""
    opcode = -3

    def __init__(self, args):
        super(Branch, self).__init__(args)

    @classmethod
    def unconditional(cls, line):
        """Return an unconditional `Branch` macro to `line`."""
        return cls((cls.opcode, line))

    @classmethod
    def conditional(cls, line, counter, value):
        """Return a conditional `Branch` macro to `line` on counter `counter` until `value`."""
        return cls((cls.opcode, line, counter, value))

    def print_(self):
        """Return 'Branch(<args after opcode>)'."""
        return f'Branch({self.args[1:]})'

    #  Create the replacement instructions for this macro
    def replace(self):
        """Return [Upper(line), Jump(...)] for this branch and print the replacement."""
        line  = self.args[1]
        l = [Upper(line)]
        if len(self.args)>2:
            cc    = self.args[2]
            value = self.args[3]
            l.append(Jump.conditional(line,cc,value))
        else:
            l.append(Jump.unconditional(line))
        print(f'Branch {self.args} replaced with {l}')
        return l


def decodeInstr(w):
    """Decode a 32-bit instruction word into an instruction object based on bits 29-31.

    Unknown codes give a plain `Instruction([w])`. Code 5 refers to `Subroutine`, which is
    not defined in this module (NameError).
    """
    idw = w>>29
    instr = Instruction([w])
    if idw == 0:  # Branch
        if w&(1<<24):
            instr = Jump.conditional(line=w&0x7ff,counter=(w>>27)&3,value=(w>>12)&Instruction.maxocc)
        else:
            instr = Jump.unconditional(line=w&0x7ff)
    elif idw == 1: # Checkpoint
        instr = CheckPoint()
    elif idw == 2: # FixedRateSync
        instr = FixedRateSync(marker=(w>>16)&0xf,occ=w&Instruction.maxocc)
    elif idw == 3: # ACRateSync
        instr = ACRateSync(timeslotm=(w>>23)&0x3f,marker=(w>>16)&0xf,occ=w&Instruction.maxocc)
    elif idw == 4: # Request (assume ControlRequest)
        instr = ControlRequest(word = w&0xffff)
    elif idw == 5: # Call/Return
        if (w&(1<<12)):
            instr = Subroutine.return_()
        else:
            instr = Subroutine.call(w&0xfff)
    elif idw == 6: # Upper
        instr = Upper(line=w<<11)

    return instr

#  validate the conditional counters in a list of instructions
def validate(filename):
    """Execute the sequence file `filename`, expand it with `preproc` and check conditional-counter use.

    Logs a warning if more than 2048 instructions result. Raises ValueError if loops using
    the same counter overlap.
    """
    config = {'title':'TITLE', 'descset':None, 'instrset':None, 'seqcodes':None, 'repeat':False}
    seq = 'from psdaq.seq.seq import *\n'
    seq += open(filename).read()
    exec(compile(seq, filename, 'exec'), {}, config)
    l = preproc(config['instrset'])

    if len(l) > 2048:
        logging.warning(f'{filename} may be too large.  {len(l)} > 2048.')
    else:
        logging.info(f'{filename} has {len(l)} instructions.')

#    for i,ins in enumerate(l):
#        print(f'{i}: {ins}')

    #  accumulate the branch statement source and targets
    d = {cc:[] for cc in range(Instruction.maxcc)}
    for line,instr in enumerate(l):
        if instr.args[0]==Jump.opcode and len(instr.args)>2:
            cc   = instr.args[2]
            addr = instr.args[1]
            d[cc].append([addr,line])

#    for i,dd in d.items():
#        print(f'd[{i}] = {dd}')

    #  check none of them overlap for a given conditional counter
    for cc in range(Instruction.maxcc):
        for r in d[cc]:
            addr = r[0]
            for s in d[cc]:
                if addr>s[0] and addr<s[1]:
                    raise ValueError(f'{filename}: CC {cc} found in overlapping loops {r} {s}')

    #  don't know how to validate call/return matches


#  Translate instruction addresses
def relocate(instrset,target,source=0):
    """Return the encoded words of `instrset` with branch/call addresses shifted from `source` to `target`.

    Returns None if any referenced address is beyond ``len(instrset) + source`` or below `source`.
    """
    words = []
    for i in instrset:
        if hasattr(i,'address'):
            jumpto = i.address()
            if jumpto > len(instrset)+source:
                return None
            elif jumpto >= source:
                words.append(i._word(jumpto+target))
            else:
                return None
        else:
            words.append(i._word())

#    for i,ins in enumerate(instrset):
#        print(f'{i}: {ins}')

#    for i,w in enumerate(words):
#        print(f'{i}: {w:x}')

    return words

def preproc(instrset):

    #  Examine bounds of conditional branches to track
    #  conditional counter usage
    #  accumulate the branch statement source and targets
    """Expand macros (`Wait`, `WaitA`, `Branch`) in `instrset` and fix up branch/upper line numbers.

    A free conditional counter is chosen for each wait from the existing backward
    conditional branches; forward conditional branches are only reported with a print.

    Returns
    -------
    list
        The new instruction list.
    """
    d = {cc:[] for cc in range(Instruction.maxcc)}
    for line,instr in enumerate(instrset):
        if instr.args[0]==Jump.opcode and len(instr.args)>2:
            cc   = instr.args[2]
            addr = instr.args[1]
            if line < addr:
                print(f'Preprocessor detected forward conditional branch')
            else:
                d[cc].append([addr,line])

#    print(f'd {d}')

    #  Find a conditional counter not in use at that line #
    def _findcc(line):
        for cc in range(Instruction.maxcc):
            lAvail = True
            for br in d[cc]:
                if line >= br[0] and line < br[1]:
                    lAvail = False
                    break
            if lAvail:
                return cc
        return None

    #  Expand macros with conditional branch usage where possible
    #  Keep the new replacement instructions in a dictionary by line
    reps  = {}
    for line,instr in enumerate(instrset):
        #  Check for macros
        if instr.args[0]==Wait.opcode:
            reps[line] = Wait.replace(instr, _findcc(line), line)
        elif instr.args[0]==WaitA.opcode:
            reps[line] = WaitA.replace(instr, _findcc(line), line)
        elif instr.args[0]==Branch.opcode:
            reps[line] = Branch.replace(instr)

#    print(f'reps {reps}')

    #  Update line number references
    def _target( old ):
        target = old
        for r in reps.keys():
            if r < old:
                target += len(reps[r])-1
        return target

    def _relocate(instr):
        if instr.opcode == Jump.opcode:
            if len(instr.args) > 2:
                return Jump.conditional(_target(instr.args[1]), 
                                        instr.args[2], 
                                        instr.args[3])
            else:
                return Jump.unconditional(_target(instr.args[1]))
        elif instr.opcode == Upper.opcode:
            print(f'Upper relocated from {instr.args[1]} to {_target(instr.args[1])}')
            return Upper(_target(instr.args[1]))

        return instr

    newinstr = []
    for line,instr in enumerate(instrset):
        start = len(newinstr)
        if line in reps:
            for rline,rinstr in enumerate(reps[line]):
                newinstr.append(_relocate(rinstr))
        else:
            newinstr.append(_relocate(instr))

    return newinstr

