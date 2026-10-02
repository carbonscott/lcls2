"""Example that prints a small instruction list before and after macro expansion with `preproc`."""
from psdaq.seq.seq import *

def main():
    """Build a list of Wait/ControlRequest/Branch instructions, print it, run `preproc` and print the result."""
    instrset = [Wait('1H',1),  
                ControlRequest([0]), 
                Wait('910kH',20000), 
                ControlRequest([1]), 
                Wait('910kH',40000), 
                Branch.conditional(3,0,5),
                Branch.unconditional(1)]
    print(f'instrset')
    for line,instr in enumerate(instrset):
        print(f'{line}: {instr}')
    print(f'---')

    newinstr = preproc(instrset)
    print(f'newinstr')
    for line,instr in enumerate(newinstr):
        print(f'{line}: {instr}')
    print(f'---')

if __name__ == "__main__":
    main()
