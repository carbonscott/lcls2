
"""
Class :py:class:`DoWorkInThread` runs worker in the thread, access status and results 
========================================================================================

Usage ::
    from psdaq.control_gui.DoWorkInThread import DoWorkInThread

See:
    - test example below
    - :class:`CGDaqControl`
    - `graphqt documentation <https://lcls-psana.github.io/graphqt/py-modindex.html>`_.

Created on 2019-02-04 by Mikhail Dubrovin
"""

#import logging
#logger = logging.getLogger(__name__)
#logging.basicConfig(level=logging.DEBUG, format='%(asctime)s (%(threadName)-2s) %(message)s',

import threading

#----------

class DoWorkInThread :
    """Live long and prosper - Peace and long life"""
    def __init__(self, worker, **kwargs) :
        """Run worker in the thread. Input and output parameters are passed using dicio"""
        self.dicio = kwargs.get('dicio', {})
        self.t = threading.Thread(target=worker, args=(self.dicio,))
        self.t.start()

    def is_running(self) :
        """Return ``self.t.isAlive()`` for the worker thread.

        `Thread.isAlive` was removed in Python 3.9, where this raises AttributeError.
        """
        return self.t.isAlive()

    def is_compleated(self) :
        """Intended to return ``not self.is_running()``.

        As written it calls ``self.is_running(self)``, which raises TypeError.
        """
        return not self.is_running(self)

    def dict_io(self) :
        """Return the input/output dict passed to the worker."""
        return self.dicio

#----------
#----------
#----------

if __name__ == "__main__" :

  from random import randint
  from time import time, sleep

  def worker_example(dicio) :
      """Example worker: print ``dicio['input']``, store a random 1-5 in ``dicio['output']`` and sleep that many seconds."""
      print('input:', dicio['input'])
      pause = randint(1,5)
      print('sleep in worker_example for random %d sec'%pause)
      dicio['output'] = pause
      sleep(pause)

  def test_DoWorkInThread() :
      """Run `worker_example` in a `DoWorkInThread` and poll it once per second (up to 10 times), printing the result when done."""
      t0_sec = time()
      #kwargs = {'dicio': {'input':123, 'output':None}}
      #o = DoWorkInThread(worker_example, **kwargs)
      o = DoWorkInThread(worker_example, dicio={'input':123, 'output':None})
      print('worker_example is execution in thread. Submission time = %.6f sec' %(time()-t0_sec))

      for i in range(10) :
          if o.is_running() :
             print('%2d process is still running...' % i)
             sleep(1)
          else :
             print('results:', o.dict_io()['output'])
             break

#----------

  test_DoWorkInThread()

#----------
