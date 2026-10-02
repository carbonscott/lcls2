
"""
Class :py:class:`DoCommandInSubprocess` for object with long executing subprocess
===============================================================================

Usage ::
    from psdaq.control_gui.DoCommandInSubprocess import DoCommandInSubprocess

    ### See test example below

See:
    - :class:`CGDaqControl`
    - `graphqt documentation <https://lcls-psana.github.io/graphqt/py-modindex.html>`_.

Created on 2019-02-01 by Mikhail Dubrovin
"""

#----------

#import logging
#logger = logging.getLogger(__name__)

#----------

class DoCommandInSubprocess :
    """Live long and prosper - Peace and long life"""
    def __init__(self, cmd='ls -l', env=None, shell=False) :
        """Launch command cmd in subprocess""" #  and when it is completed puts response in dic_status value for specified key"""
        self.cmd = cmd
        #self.key = key
        #self.dic = dic_status

        #import subprocess
        from subprocess import Popen, PIPE
        self.proc = Popen(cmd.split(), stdout=PIPE, stderr=PIPE, env=env, shell=shell) #, stdin=subprocess.STDIN
        #self.proc.wait() # DO NOT WAIT FOR RESPONSE

    def get_stderr(self) :
        """Return the command string.

        This definition is overridden by the later `get_stderr` in the same class and is never used.
        """
        return self.cmd

    def process_is_running(self) :
        """Return True while the subprocess has not exited (``poll()`` is None)."""
        return self.proc.poll() is None 

    def get_stdout(self) :
        """Read and return the subprocess's entire stdout (bytes); blocks until EOF."""
        return self.proc.stdout.read() # reads entire file

    def get_stderr(self) :
        """Read and return the subprocess's entire stderr (bytes); blocks until EOF."""
        return self.proc.stderr.read() # reads entire file

#----------
#----------
#----------
#----------

if __name__ == "__main__" :
  
  def test_DoCommandInSubprocess() :

      """Run 'ls -l' in a `DoCommandInSubprocess` and poll once per second (up to 10 times), printing stdout/stderr when done."""
      from time import time, sleep

      cmd = 'ls -l'
      t0_sec = time()
      o = DoCommandInSubprocess(cmd)
      print('command: "%s" is execution in subprocess. Submission time = %.6f sec' %(cmd, time()-t0_sec))
      
      for i in range(10) :
          if o.process_is_running() :
             print('%2d process is still running...' % i)
             sleep(1)
          else :
             print('stdout:\n%s' % o.get_stdout())
             print('stderr:\n%s' % o.get_stderr())
             break

#----------

if __name__ == "__main__" :
    test_DoCommandInSubprocess()

#----------
