# MatMul Implementation in GPU DRP

This document describes the implementation of matrix multiplication (MatMul) kernels in the LCLS2 GPU Data Reduction Pipeline (DRP) as a learning exercise for inserting custom algorithms.

## Overview

We have implemented MatMul functionality in two phases:

1. **Phase 1**: Modified existing `NoOpReducer` to include MatMul capability
2. **Phase 2**: Created dedicated `MatMulReducer` with full production architecture

## Phase 1: NoOpReducer with MatMul

### Files Modified:
- `NoOpReducer.cu` - Added MatMul kernels and logic
- Environment variable control: `ENABLE_MATMUL_TEST=1`

### Features:
- Simple MatMul kernel for verification
- Test data initialization on GPU
- Environment variable switching between NoOp and MatMul modes
- 4x4 matrix test to fit within existing buffer constraints

### Usage:
```bash
export ENABLE_MATMUL_TEST=1
# Run with existing NoOpReducer
```

## Phase 2: Dedicated MatMulReducer

### Files Created:
- `MatMulReducer.hh` - Class declaration and interface
- `MatMulReducer.cu` - Full implementation with optimized kernels
- `CMakeLists.txt` - Updated build configuration
- `test_matmul_config.sh` - Test configuration script

### Architecture Features:

#### 1. Kernel Implementations
- **Naive Kernel**: Simple O(N³) for verification
- **Optimized Kernel**: Shared memory tiling (16x16 tiles)
- **Initialization Kernel**: Multiple test matrix patterns

#### 2. Memory Management
- Automatic matrix size calculation based on buffer capacity
- Support for matrices up to 512x512 (memory permitting)
- Efficient layout: [Matrix A][Matrix B][Matrix C][Metadata]

#### 3. XTC Integration
- Complete data format definitions for all matrices
- Proper shape descriptions for 2D matrices
- Metadata including timing, kernel type, and status

#### 4. Configuration Options
- `MATMUL_USE_NAIVE=1` - Switch to naive kernel
- `MATMUL_TEST_TYPE=N` - Select test pattern:
  - 0: Identity × Sequential (easy verification)
  - 1: All ones (result = N for each element)
  - 2: Row/Col indices (structured pattern)
  - 3: Custom incremental values

## Technical Implementation Details

### Kernel Optimization Strategy

#### Naive Implementation:
```cuda
// Simple per-thread computation
int row = blockIdx.y * blockDim.y + threadIdx.y;
int col = blockIdx.x * blockDim.x + threadIdx.x;
float sum = 0.0f;
for (int k = 0; k < N; k++) {
    sum += A[row * N + k] * B[k * N + col];
}
C[row * N + col] = sum;
```

#### Optimized Implementation:
```cuda
// Shared memory tiling for better cache utilization
__shared__ float As[16][16];
__shared__ float Bs[16][16];
// Load tiles, compute partial results, accumulate
```

### Memory Access Patterns
- **Naive**: Poor cache locality, multiple global memory accesses
- **Optimized**: Coalesced memory access, shared memory reuse
- **Expected Speedup**: 2-10x depending on matrix size

### Buffer Management
- Calculates optimal matrix size based on available GPU memory
- Ensures 3×N² + metadata fits within calibration buffer
- Supports dynamic sizing from 2×2 to 512×512 matrices

## Build System Integration

### CMake Configuration:
```cmake
add_library(MatMulReducer SHARED MatMulReducer.cu)
target_link_libraries(MatMulReducer
    xtcdata::xtc
    CUDA::cudart
    CUDA::cuda_driver)
set_target_properties(MatMulReducer PROPERTIES CUDA_ARCHITECTURES "86")
```

### Dependencies:
- CUDA Toolkit (nvcc compiler)
- XtcData library for data formatting
- GPU DRP base libraries
- A100/H100 GPU (Architecture 86)

## Usage Examples

### Building:
```bash
cd /path/to/lcls2/psdaq/build
make MatMulReducer  # Build the library
```

### Runtime Configuration:
```bash
# Test with identity matrices (easy verification)
export MATMUL_TEST_TYPE=0
export MATMUL_USE_NAIVE=0  # Use optimized kernel

# Launch DRP with MatMul reducer
drp_gpu -l libMatMulReducer.so -r MatMulReducer
```

### Verification:
For identity test (type 0), the result matrix C should equal matrix B:
```
A = [[1,0,0,0], [0,1,0,0], [0,0,1,0], [0,0,0,1]]  # Identity
B = [[1,2,3,4], [5,6,7,8], [9,10,11,12], [13,14,15,16]]  # Sequential
C = B  # Expected result
```

## Performance Characteristics

### Computational Complexity:
- **Operations**: 2×N³ - N² (multiply-adds minus final additions)
- **Memory**: 3×N² floats + metadata
- **Parallelism**: N² threads for naive, optimized tiling for shared memory

### Expected Performance:
- **Small matrices** (N≤64): Memory bandwidth limited
- **Medium matrices** (64<N≤256): Compute bound, good for optimization
- **Large matrices** (N>256): Memory capacity limited

### Optimization Opportunities:
1. **Shared Memory**: 16×16 tiles reduce global memory access
2. **Memory Coalescing**: Proper access patterns for bandwidth
3. **Occupancy**: Balance threads per block vs. shared memory usage
4. **Tensor Cores**: Could use half-precision for modern GPUs

## Integration with LCLS2 Pipeline

### Data Flow:
1. **Input**: Calibration buffers (could contain real detector data)
2. **Processing**: GPU MatMul kernels
3. **Output**: XTC formatted results for downstream analysis
4. **Metadata**: Timing, algorithm info, validation status

### Real-World Applications:
- **Detector Calibration**: Matrix transformations for geometry corrections
- **Signal Processing**: Convolution matrices for filtering
- **Feature Extraction**: PCA transformations for data reduction
- **Reconstruction**: System matrices for tomographic reconstruction

## Learning Outcomes

### GPU DRP Architecture Understanding:
1. **Reducer Pattern**: Plugin-based algorithm integration
2. **Memory Management**: GPU buffer pools and stream processing
3. **XTC Integration**: LCLS2 data format requirements
4. **Build System**: CMake with CUDA compilation
5. **Factory Pattern**: Dynamic library loading

### CUDA Programming Techniques:
1. **Kernel Design**: Naive vs. optimized approaches
2. **Memory Optimization**: Shared memory and coalescing
3. **Launch Configuration**: Block/grid sizing strategies
4. **Error Handling**: Proper CUDA error checking
5. **Stream Processing**: Asynchronous execution

## Troubleshooting

### Common Issues:
1. **CUDA Not Found**: Ensure CUDA toolkit is installed and in PATH
2. **Architecture Mismatch**: Verify GPU supports compute capability 8.6
3. **Memory Errors**: Check buffer sizes and alignment
4. **Kernel Launch Failures**: Verify grid/block dimensions
5. **Linking Errors**: Ensure all CUDA libraries are available

### Debug Output:
The implementation includes extensive printf debugging:
- Matrix initialization verification
- Kernel launch confirmation
- Result validation for small matrices
- Memory layout information

## Extending the Implementation

### Adding New Algorithms:
1. Create new `MyAlgorithmReducer.cu/.hh` files
2. Inherit from `ReducerAlgo` base class
3. Implement required virtual methods
4. Add to CMakeLists.txt build configuration
5. Create factory function `createReducer()`

### Performance Improvements:
1. **Tensor Core Usage**: Use half or mixed precision
2. **Multiple Streams**: Overlap computation and memory transfer
3. **Batching**: Process multiple matrices simultaneously
4. **Graph Capture**: Use CUDA graphs for kernel sequences

This MatMul implementation serves as a comprehensive example of integrating custom GPU algorithms into the LCLS2 data acquisition pipeline, demonstrating both the technical implementation details and the architectural patterns used throughout the system.