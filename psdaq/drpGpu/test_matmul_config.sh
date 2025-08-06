#!/bin/bash

# Test configuration script for MatMulReducer
# This script demonstrates how to configure and use the MatMulReducer

echo "====== MatMul Reducer Test Configuration ======"

# Environment variables for MatMul configuration
export ENABLE_MATMUL_TEST=1      # Enable matmul in NoOpReducer (Phase 1)
export MATMUL_USE_NAIVE=0        # Use optimized kernel (set to 1 for naive)
export MATMUL_TEST_TYPE=0        # Test type: 0=identity*sequential, 1=ones, 2=indices

echo "Configuration:"
echo "  ENABLE_MATMUL_TEST = $ENABLE_MATMUL_TEST"
echo "  MATMUL_USE_NAIVE   = $MATMUL_USE_NAIVE"
echo "  MATMUL_TEST_TYPE   = $MATMUL_TEST_TYPE"

# Expected results for different test types
case $MATMUL_TEST_TYPE in
    0)
        echo "  Test Type: Identity * Sequential"
        echo "  Expected: C = B (since A is identity matrix)"
        echo "  Example: C[0,0] = 1.0, C[0,1] = 2.0, C[1,0] = 5.0, C[1,1] = 6.0"
        ;;
    1)
        echo "  Test Type: All Ones"
        echo "  Expected: C[i,j] = N for all elements (where N is matrix size)"
        echo "  Example for 4x4: All elements should be 4.0"
        ;;
    2)
        echo "  Test Type: Row/Col Indices"
        echo "  Expected: C[i,j] = sum over k of (i * k) for each position"
        echo "  Example: C[0,j] = 0, C[1,j] = (0+1+2+3)*1, etc."
        ;;
    *)
        echo "  Test Type: Custom incremental"
        ;;
esac

echo ""
echo "Usage Instructions:"
echo "1. Phase 1 (NoOpReducer with matmul):"
echo "   - Set ENABLE_MATMUL_TEST=1"
echo "   - Run: drp_gpu -l <reducer_lib> -r NoOpReducer"
echo ""
echo "2. Phase 2 (Dedicated MatMulReducer):"
echo "   - Run: drp_gpu -l <reducer_lib> -r MatMulReducer"
echo ""
echo "Build Commands (when CUDA is available):"
echo "   cd /path/to/lcls2/psdaq/build"
echo "   make NoOpReducer      # For Phase 1"
echo "   make MatMulReducer    # For Phase 2"
echo ""

# Performance expectations
echo "Performance Notes:"
echo "  - Naive kernel: O(N^3) with poor memory access patterns"
echo "  - Optimized kernel: Uses 16x16 shared memory tiles"
echo "  - Expected speedup: 2-10x depending on matrix size and GPU"
echo "  - Memory usage: 3 * N^2 * sizeof(float) + metadata"
echo ""

# Validation checks
echo "Validation Checklist:"
echo "  [ ] Matrices initialized correctly"
echo "  [ ] Kernel launches without errors"  
echo "  [ ] Results match expected values"
echo "  [ ] XTC data format contains all matrices"
echo "  [ ] Metadata includes timing and kernel type"
echo "  [ ] No memory leaks or CUDA errors"
echo ""

echo "====== End Configuration ======"