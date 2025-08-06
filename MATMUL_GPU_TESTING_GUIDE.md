# MatMul GPU Testing Guide

## Summary of Implementation

We have successfully implemented matrix multiplication (MatMul) kernels in the LCLS2 GPU DRP system as a comprehensive learning exercise for inserting custom algorithms. The implementation is complete and ready for testing on a GPU-enabled node.

## What Was Accomplished

### ✅ Phase 1: NoOpReducer Enhancement
- **Modified**: `psdaq/drpGpu/NoOpReducer.cu`
- **Added**: MatMul kernel with environment variable control
- **Features**: 4x4 test matrices, verification logic, debug output
- **Control**: `ENABLE_MATMUL_TEST=1` environment variable

### ✅ Phase 2: Dedicated MatMulReducer
- **Created**: `psdaq/drpGpu/MatMulReducer.hh` - Complete class interface
- **Created**: `psdaq/drpGpu/MatMulReducer.cu` - Full implementation with:
  - Naive O(N³) kernel for verification
  - Optimized shared memory kernel (16×16 tiles)
  - Multiple test patterns and initialization
  - Complete XTC data format integration
  - Dynamic matrix sizing based on buffer capacity
  - Comprehensive error checking and logging

### ✅ Build System Integration
- **Updated**: `psdaq/drpGpu/CMakeLists.txt`
- **Added**: MatMulReducer library target with proper CUDA linking
- **Architecture**: Targets CUDA compute capability 8.6 (A100/H100)

### ✅ Testing and Documentation
- **Created**: `psdaq/drpGpu/test_matmul_config.sh` - Configuration script
- **Created**: `psdaq/drpGpu/MATMUL_IMPLEMENTATION.md` - Technical documentation
- **Created**: Various investigation and summary documents

## GPU Node Testing Instructions

### Prerequisites
1. **GPU Node Access**: Log into a node with CUDA-capable GPU (A100/H100 preferred)
2. **CUDA Toolkit**: Ensure CUDA 11+ is available (`nvcc --version`)
3. **Environment**: Source the LCLS2 environment setup

### Step 1: Environment Setup
```bash
# Log into GPU node
ssh gpu-node-name

# Source LCLS2 environment
source /path/to/lcls2/setup_env.sh

# Verify CUDA availability
nvcc --version
nvidia-smi
```

### Step 2: Build the Implementation
```bash
cd /cds/home/c/cwang31/software/lcls2/psdaq/build

# Build the MatMul components
make NoOpReducer      # Phase 1 implementation
make MatMulReducer    # Phase 2 implementation

# Verify libraries were created
ls -la drpGpu/libNoOpReducer.so
ls -la drpGpu/libMatMulReducer.so
```

### Step 3: Test Phase 1 (NoOpReducer with MatMul)
```bash
# Run test configuration script
/cds/home/c/cwang31/software/lcls2/psdaq/drpGpu/test_matmul_config.sh

# Set environment for Phase 1 testing
export ENABLE_MATMUL_TEST=1
export MATMUL_TEST_TYPE=0  # Identity × Sequential test

# Test with NoOpReducer (exact command depends on DRP setup)
# This would typically be integrated into the larger DRP system
```

### Step 4: Test Phase 2 (Dedicated MatMulReducer)
```bash
# Test different kernel configurations
export MATMUL_USE_NAIVE=0    # Use optimized shared memory kernel
export MATMUL_TEST_TYPE=1    # All-ones test (easy to verify)

# Test with MatMulReducer
# Integration with full DRP system would require proper configuration
```

### Step 5: Validation Tests

#### Test Pattern Verification:
1. **Identity Test** (`MATMUL_TEST_TYPE=0`):
   - Expected: C = B (since A is identity matrix)
   - Verify: C[0,0]=1, C[0,1]=2, C[1,0]=5, C[1,1]=6

2. **All-Ones Test** (`MATMUL_TEST_TYPE=1`):
   - Expected: All elements of C equal matrix size N
   - Verify: For 4×4 matrices, all C[i,j] = 4.0

3. **Indices Test** (`MATMUL_TEST_TYPE=2`):
   - Expected: Structured pattern based on row/column indices
   - Verify: Mathematical correctness of results

#### Performance Comparison:
```bash
# Test naive kernel
export MATMUL_USE_NAIVE=1
# Run and measure timing

# Test optimized kernel  
export MATMUL_USE_NAIVE=0
# Run and measure timing
# Expected: 2-10× speedup for larger matrices
```

## Expected Outputs

### Console Debug Output:
```
### matmulTest: Initialized 4x4 test matrices
### A[0,0]=1.000000, A[1,1]=1.000000, B[0,0]=1.000000, B[1,1]=6.000000
### matmul: C[0,0] = 1.000000
### matmul: C[0,1] = 2.000000  
### matmul: C[1,0] = 5.000000
### matmul: C[1,1] = 6.000000
### matmulTest: Completed 4x4 matrix multiplication
```

### XTC Data Format:
- Matrix A (input): 2D float array
- Matrix B (input): 2D float array  
- Matrix C (result): 2D float array
- Metadata: [matrix_size, timing, kernel_type, status]

## Performance Benchmarking

### Matrix Sizes to Test:
- **Small**: 16×16 (memory bandwidth limited)
- **Medium**: 128×128 (compute bound, good for optimization comparison)
- **Large**: 512×512 (capacity limited)

### Metrics to Collect:
- **Kernel Launch Time**: CUDA event timing
- **Memory Transfer Time**: Host ↔ Device copying
- **Computation Time**: Pure kernel execution
- **Total Pipeline Time**: End-to-end processing

### Expected Performance:
- **Naive Kernel**: ~1-2 GFLOPS (poor memory locality)
- **Optimized Kernel**: ~50-200 GFLOPS (depending on matrix size)
- **Peak A100**: ~312 TFLOPS FP32 (theoretical maximum)

## Integration with Real Workloads

### Detector Data Processing:
Replace test matrix initialization with real detector data:
```cuda
// Instead of test patterns, use:
float* detectorData = calibBuffers[index];  // Real calibration data
float* systemMatrix = /* load from configuration */;
// Perform: correctedData = systemMatrix × detectorData
```

### Potential Applications:
1. **Geometry Corrections**: Transform detector coordinates
2. **Calibration**: Apply gain/offset matrices
3. **Feature Extraction**: PCA or other linear transformations
4. **Reconstruction**: System matrix operations for tomography

## Troubleshooting

### Build Issues:
- **CUDA Not Found**: Check `CMAKE_CUDA_COMPILER` path
- **Architecture Errors**: Verify GPU compute capability
- **Linking Errors**: Ensure all CUDA libraries available

### Runtime Issues:
- **Kernel Launch Failures**: Check CUDA error output
- **Memory Errors**: Verify buffer sizes and alignment
- **Incorrect Results**: Enable debug prints, verify test patterns

## Next Steps After Validation

1. **Performance Optimization**: Profile and tune for specific hardware
2. **Real Data Integration**: Connect to actual detector streams
3. **Additional Algorithms**: Use as template for other custom kernels
4. **Production Deployment**: Integrate into full LCLS2 DAQ system

## Files Created/Modified Summary

### Implementation Files:
- `psdaq/drpGpu/NoOpReducer.cu` - Modified with MatMul capability
- `psdaq/drpGpu/MatMulReducer.hh` - New dedicated reducer header
- `psdaq/drpGpu/MatMulReducer.cu` - New dedicated reducer implementation
- `psdaq/drpGpu/CMakeLists.txt` - Updated build configuration

### Documentation/Testing:
- `psdaq/drpGpu/test_matmul_config.sh` - Test configuration script
- `psdaq/drpGpu/MATMUL_IMPLEMENTATION.md` - Technical documentation
- `MATMUL_GPU_TESTING_GUIDE.md` - This testing guide
- `matmul_kernel_placement_investigation.md` - Architecture investigation
- `rclaus2_gpu_investigation.md` - Developer history investigation

The implementation is complete and ready for GPU testing. This serves as a comprehensive example of how to integrate custom algorithms into the LCLS2 GPU DRP system, demonstrating both the technical implementation and the architectural patterns used throughout the system.