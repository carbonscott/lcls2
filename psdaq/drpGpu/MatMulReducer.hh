#pragma once

#include "ReducerAlgo.hh"

namespace Drp {
  namespace Gpu {

class MatMulReducer : public ReducerAlgo
{
public:
  MatMulReducer(const Parameters& para, const MemPoolGpu& pool, Detector& det);
  virtual ~MatMulReducer() {}

  void recordGraph(cudaStream_t& stream,
                   const unsigned& index,
                   float** const calibBuffer,
                   uint8_t** const dataBuffer,
                   unsigned* extent) override;
  unsigned configure(XtcData::Xtc&, const void* bufEnd) override;
  void event(XtcData::Xtc&, const void* bufEnd, unsigned dataSize) override;

private:
  size_t _matrixSize;     // Matrix dimensions (N for NxN matrices)
  size_t _calibSize;      // Calibration buffer size
  size_t _resultSize;     // Result buffer size (3 matrices: A, B, C)
  bool   _useOptimized;   // Flag to use optimized shared memory kernel
};

  } // Gpu
} // Drp