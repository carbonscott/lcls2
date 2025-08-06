#include "MatMulReducer.hh"

#include "GpuAsyncLib.hh"
#include "MemPool.hh"
#include "Detector.hh"
#include "drp/drp.hh"
#include "xtcdata/xtc/VarDef.hh"
#include "xtcdata/xtc/DescData.hh"
#include "psalg/utils/SysLog.hh"
#include <cstring>
#include <cstdlib>

using logging = psalg::SysLog;
using namespace XtcData;
using namespace Drp::Gpu;

namespace Drp {
  namespace Gpu {

// Data definition for MatMul results
class MatMulReducerDef : public VarDef
{
public:
  enum index { 
    matrixA,    // Input matrix A
    matrixB,    // Input matrix B  
    matrixC,    // Result matrix C = A * B
    metadata    // Metadata (size, timing, etc.)
  };

  MatMulReducerDef(int N)
  {
    NameVec.push_back({"matrixA", Name::FLOAT, 2, {N, N}});
    NameVec.push_back({"matrixB", Name::FLOAT, 2, {N, N}});
    NameVec.push_back({"matrixC", Name::FLOAT, 2, {N, N}});
    NameVec.push_back({"metadata", Name::UINT32, 1, {4}});  // [N, timing, kernel_type, status]
  }
};

  } // Gpu
} // Drp

// Naive matrix multiplication kernel
// Simple O(n^3) algorithm for verification purposes
static __global__ void _matmulKernelNaive(const float* __restrict__ A,
                                          const float* __restrict__ B,
                                          float* __restrict__ C,
                                          int N)
{
  int row = blockIdx.y * blockDim.y + threadIdx.y;
  int col = blockIdx.x * blockDim.x + threadIdx.x;
  
  if (row < N && col < N) {
    float sum = 0.0f;
    for (int k = 0; k < N; k++) {
      sum += A[row * N + k] * B[k * N + col];
    }
    C[row * N + col] = sum;
    
    // Debug output for small matrices
    if (N <= 8 && row < 2 && col < 2) {
      printf("### MatMul Naive: C[%d,%d] = %f\n", row, col, sum);
    }
  }
}

// Optimized matrix multiplication kernel using shared memory
// Uses 16x16 tiles for better memory coalescing and cache utilization  
static __global__ void _matmulKernelOptimized(const float* __restrict__ A,
                                              const float* __restrict__ B,
                                              float* __restrict__ C,
                                              int N)
{
  const int TILE_SIZE = 16;
  
  // Shared memory for tiles
  __shared__ float As[TILE_SIZE][TILE_SIZE];
  __shared__ float Bs[TILE_SIZE][TILE_SIZE];
  
  int bx = blockIdx.x; 
  int by = blockIdx.y;
  int tx = threadIdx.x; 
  int ty = threadIdx.y;
  
  int Row = by * TILE_SIZE + ty;
  int Col = bx * TILE_SIZE + tx;
  
  float Csub = 0.0f;
  
  // Loop over the tiles of A and B required to compute the block of C
  for (int m = 0; m < (N + TILE_SIZE - 1) / TILE_SIZE; ++m) {
    // Load tiles into shared memory
    if (Row < N && (m * TILE_SIZE + tx) < N) {
      As[ty][tx] = A[Row * N + m * TILE_SIZE + tx];
    } else {
      As[ty][tx] = 0.0f;
    }
      
    if (Col < N && (m * TILE_SIZE + ty) < N) {
      Bs[ty][tx] = B[(m * TILE_SIZE + ty) * N + Col];
    } else {
      Bs[ty][tx] = 0.0f;
    }
      
    __syncthreads();
    
    // Compute partial result using shared memory
    for (int k = 0; k < TILE_SIZE; ++k) {
      Csub += As[ty][k] * Bs[k][tx];
    }
      
    __syncthreads();
  }
  
  // Write result to global memory
  if (Row < N && Col < N) {
    C[Row * N + Col] = Csub;
    
    // Debug output for small matrices
    if (N <= 8 && Row < 2 && Col < 2) {
      printf("### MatMul Optimized: C[%d,%d] = %f\n", Row, Col, Csub);
    }
  }
}

// Kernel to initialize test matrices
static __global__ void _initializeMatrices(float* A, float* B, int N, int testType)
{
  int idx = blockIdx.x * blockDim.x + threadIdx.x;
  int totalElements = N * N;
  
  if (idx < totalElements) {
    int row = idx / N;
    int col = idx % N;
    
    switch (testType) {
      case 0: // Identity * Sequential
        A[idx] = (row == col) ? 1.0f : 0.0f;  // Identity matrix
        B[idx] = idx + 1.0f;                  // Sequential values
        break;
        
      case 1: // All ones (easy to verify: result should be N for each element)
        A[idx] = 1.0f;
        B[idx] = 1.0f;
        break;
        
      case 2: // Row/Col indices (A[i,j] = i, B[i,j] = j)
        A[idx] = (float)row;
        B[idx] = (float)col;
        break;
        
      default: // Simple incremental
        A[idx] = idx * 0.1f;
        B[idx] = (totalElements - idx) * 0.1f;
        break;
    }
  }
}

// Constructor
MatMulReducer::MatMulReducer(const Parameters& para, const MemPoolGpu& pool, Detector& det) :
  ReducerAlgo(para, pool, det),
  _calibSize(pool.calibBufSize()),
  _useOptimized(true)
{
  // Determine matrix size based on available buffer space
  // We need space for 3 matrices (A, B, C) plus metadata
  size_t availableFloats = _calibSize / sizeof(float);
  size_t metadataFloats = 4;  // metadata array size
  
  // Solve: 3*N^2 + metadata <= availableFloats
  size_t maxMatrixElements = (availableFloats - metadataFloats) / 3;
  _matrixSize = (size_t)sqrt((double)maxMatrixElements);
  
  // Ensure reasonable bounds
  if (_matrixSize < 2) _matrixSize = 2;      // Minimum 2x2
  if (_matrixSize > 512) _matrixSize = 512;  // Maximum 512x512 for memory
  
  _resultSize = 3 * _matrixSize * _matrixSize * sizeof(float) + metadataFloats * sizeof(uint32_t);
  
  // Check environment variable for kernel selection
  const char* useNaive = getenv("MATMUL_USE_NAIVE");
  _useOptimized = !(useNaive && strcmp(useNaive, "1") == 0);
  
  logging::info("MatMulReducer: Matrix size %zux%zu, optimized=%s, buffer=%zu bytes", 
                _matrixSize, _matrixSize, _useOptimized ? "true" : "false", _resultSize);
}

// Record the CUDA graph for matrix multiplication
void MatMulReducer::recordGraph(cudaStream_t& stream,
                                const unsigned& index,
                                float** const calibBuffers,
                                uint8_t** const dataBuffers,
                                unsigned* extent)
{
  logging::debug("MatMulReducer::recordGraph: Processing matrices %zux%zu", _matrixSize, _matrixSize);
  
  // Get buffer pointers
  float* dataBuffer = (float*)(dataBuffers[index]);
  
  // Layout in buffer: [A matrices][B matrices][C matrices][metadata]
  float* A = dataBuffer;
  float* B = dataBuffer + _matrixSize * _matrixSize;
  float* C = dataBuffer + 2 * _matrixSize * _matrixSize;
  uint32_t* metadata = (uint32_t*)(dataBuffer + 3 * _matrixSize * _matrixSize);
  
  // Initialize matrices with test data
  int testType = 0;  // Use identity * sequential test
  const char* testTypeEnv = getenv("MATMUL_TEST_TYPE");
  if (testTypeEnv) {
    testType = atoi(testTypeEnv);
  }
  
  int totalElements = _matrixSize * _matrixSize;
  dim3 initBlock(256);
  dim3 initGrid((totalElements + initBlock.x - 1) / initBlock.x);
  
  _initializeMatrices<<<initGrid, initBlock, 0, stream>>>(A, B, _matrixSize, testType);
  
  // Launch matrix multiplication kernel
  if (_useOptimized) {
    // Use optimized shared memory kernel with 16x16 blocks
    dim3 blockSize(16, 16);
    dim3 gridSize((_matrixSize + blockSize.x - 1) / blockSize.x,
                  (_matrixSize + blockSize.y - 1) / blockSize.y);
    
    _matmulKernelOptimized<<<gridSize, blockSize, 0, stream>>>(A, B, C, _matrixSize);
  } else {
    // Use naive kernel with 16x16 blocks  
    dim3 blockSize(16, 16);
    dim3 gridSize((_matrixSize + blockSize.x - 1) / blockSize.x,
                  (_matrixSize + blockSize.y - 1) / blockSize.y);
                  
    _matmulKernelNaive<<<gridSize, blockSize, 0, stream>>>(A, B, C, _matrixSize);
  }
  
  // Initialize metadata on device
  uint32_t hostMetadata[4] = {
    (uint32_t)_matrixSize,
    0,  // Timing placeholder (would need CUDA events for real timing)
    _useOptimized ? 1 : 0,  // Kernel type
    0   // Status (0 = success)
  };
  
  chkError(cudaMemcpyAsync(metadata, hostMetadata, 4 * sizeof(uint32_t), 
                           cudaMemcpyHostToDevice, stream));
  
  *extent = _resultSize;
  
  logging::debug("MatMulReducer: Launched %s kernel for %zux%zu matrices", 
                 _useOptimized ? "optimized" : "naive", _matrixSize, _matrixSize);
}

// Configure XTC data format
unsigned MatMulReducer::configure(Xtc& xtc, const void* bufEnd)
{
  // Set up the names for L1Accept data  
  Alg alg("matmul", 1, 0, 0);
  NamesId namesId(m_det.nodeId, ReducerNamesIndex);
  Names& names = *new(xtc, bufEnd) Names(bufEnd,
                                         m_para.detName.c_str(), alg,
                                         m_para.detType.c_str(), m_para.serNo.c_str(), 
                                         namesId, m_para.detSegment);
  
  MatMulReducerDef reducerDef(_matrixSize);
  names.add(xtc, bufEnd, reducerDef);
  m_det.namesLookup()[namesId] = NameIndex(names);
  
  logging::info("MatMulReducer configured for %zux%zu matrices", _matrixSize, _matrixSize);
  return 0;
}

// Handle event data formatting
void MatMulReducer::event(Xtc& xtc, const void* bufEnd, unsigned dataSize)
{
  logging::debug("MatMulReducer event: xtc %p, extent %u, size %u", &xtc, xtc.extent, dataSize);
  
  // Data contains the result matrices
  NamesId namesId(m_det.nodeId, ReducerNamesIndex);
  
  CreateData data(xtc, bufEnd, m_det.namesLookup(), namesId);
  
  // Set up array shapes for matrices
  unsigned matrixShape[2] = { (unsigned)_matrixSize, (unsigned)_matrixSize };
  unsigned metadataShape[1] = { 4 };
  
  data.set_array_shape(MatMulReducerDef::matrixA, matrixShape);
  data.set_array_shape(MatMulReducerDef::matrixB, matrixShape);
  data.set_array_shape(MatMulReducerDef::matrixC, matrixShape);
  data.set_array_shape(MatMulReducerDef::metadata, metadataShape);
  
  logging::debug("MatMulReducer: Event formatted for %zux%zu matrices", _matrixSize, _matrixSize);
}

// Class factory function
extern "C" Drp::Gpu::ReducerAlgo* createReducer(const Drp::Parameters& para,
                                                const Drp::Gpu::MemPoolGpu& pool,
                                                Drp::Gpu::Detector& det)
{
  return new Drp::Gpu::MatMulReducer(para, pool, det);
}