
"""Example: pass numpy arrays to compiled test functions of the module ``ndarray`` (``test_nda_fused_v2``, ``test_nda_fused``, ``py_ctest_vector``, ``py_ndarray_double``); the functions themselves are not visible here."""
import numpy as np

def test_01() :
    """Call ``ndarray.test_nda_fused_v2`` with a 2x4 int16 array."""
    from ndarray import test_nda_fused_v2
    print(50*'_', '\nTest of templated function test_nda_fused_v2')
    nda = np.arange(10, 2, -1, dtype=np.int16)
    nda.shape = (2,4)
    test_nda_fused_v2(nda)

def test_templ(nda) :
    """Call ``ndarray.test_nda_fused(nda)`` and print ``nda`` afterwards."""
    from ndarray import test_nda_fused
    test_nda_fused(nda)
    print('In test_nda_fused returned array:\n', nda)

def test_02() :
    """Call ``test_templ`` with arrays of ones (times 1, 2, 3) of dtypes float64, int16 and uint16."""
    print(50*'_', '\nTest of templated function test_nda')
    test_templ(1*np.ones((2,3), dtype=np.float64))
    test_templ(2*np.ones((2,4), dtype=np.int16))
    test_templ(3*np.ones((2,5), dtype=np.uint16))

def test_03() :
    """Call ``ndarray.py_ctest_vector`` with 1-d float64, float32 and int32 ranges."""
    print(50*'_', '\nTest of py_ctest_vector')
    from ndarray import py_ctest_vector

    py_ctest_vector(np.arange(0, 10, 1, dtype=np.float64))
    py_ctest_vector(np.arange(1, 10, 1, dtype=np.float32))
    py_ctest_vector(np.arange(10, 1,-1, dtype=np.int32))

def test_04() :
    """Create a ``ndarray.py_ndarray_double`` object and call its ``set_nda`` with a 2x3 float64 array of ones."""
    print(50*'_', '\nTest of py_ndarray')
    from ndarray import py_ndarray_double
    a = py_ndarray_double()
    a.set_nda(np.ones((2,3), dtype=np.float64))

def usage(tname):
    """Return the usage text, listing all tests for ``tname`` '0' or only the selected one."""
    s = '\nUsage: python psana/psana/hexanode/examples/ex-00-np-to-cpp-ndarray.py <test-number>'
    if tname in ('0',)    : s+='\n 0 - test ALL'
    if tname in ('0','1') : s+='\n 1 - templated function test_nda_fused_v2'
    if tname in ('0','2') : s+='\n 2 - templated function test_nda'
    if tname in ('0','3') : s+='\n 3 - test of py_ctest_vector'
    if tname in ('0','4') : s+='\n 4 - test of py_ndarray'
    return s

if __name__ == "__main__" :
    import sys; global sys
    import numpy as np; global np
    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    s = 'End of Test %s' % tname
    print('%s' % usage(tname))
    print(50*'_', '\nTest %s' % tname)
    if tname in ('0','1') : test_01()
    if tname in ('0','2') : test_02()
    if tname in ('0','3') : test_03()
    if tname in ('0','4') : test_04()
    print('%s' % usage(tname))
    sys.exit(s)

# EOF
