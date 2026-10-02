/**
 * @file
 * @brief CuSZpReducer, a ReducerAlgo plugin for the GPU DRP; its .cu file defines the createReducer() factory.
 */
#pragma once

#include "ReducerAlgo.hh"

#include <cuSZp.h>

namespace Drp {
  namespace Gpu {

/** Reducer that compresses each calibrated buffer with cuSZp (cuSZp_compress_1D_plain_f32) using an error bound of 1.2e-4 (absolute, per the code comment). It runs through reduce(), not a graph. */
class CuSZpReducer : public ReducerAlgo
{
public:
  /** Set the error bound to 1.2e-4. */
  CuSZpReducer(const Parameters& para, const MemPoolGpu& pool, Detector& det);
  /** Does nothing; empty body. */
  virtual ~CuSZpReducer() {}

  /** Return false: compression runs through reduce(), not a CUDA graph. */
  bool   hasGraph()    const override { return false; }
  /** Return the calibrated buffer size. */
  size_t payloadSize() const override { return m_pool.calibBufsSize(); }
  /** Does nothing; empty body. */
  void   recordGraph(cudaStream_t       stream,
                     unsigned*    const state,
                     unsigned*    const index,
                     float const* const calibBuffers,
                     size_t       const calibBufsCnt,
                     uint8_t*     const dataBuffers,
                     size_t       const dataBufsCnt) override;
  /** Compress calibrated buffer index into data buffer index on stream with cuSZp, then set *dataSize to the compressed size and *retCode to 0. The graph argument is not used. */
  void     reduce   (cudaGraphExec_t,
                     cudaStream_t,
                     unsigned  index,
                     size_t*   dataSize,
                     unsigned* retCode) override;
  /** Return 0; nothing is configured. */
  int      configure(const nlohmann::json& configureMsg,
                     const nlohmann::json& connectMsg,
                     size_t                collectionId) override { return 0; }
  /** Add the names of the reduced data (algorithm cuSZp, one UINT8 array named cuSZp) under ReducerNamesIndex and register them in the detector's names lookup; returns 0. */
  unsigned configure(XtcData::Xtc&, const void* bufEnd) override;
  /** Set the shape of the cuSZp array to dataSize elements in the data description; the data itself stays on the GPU. */
  void     event    (XtcData::Xtc&, const void* bufEnd, unsigned dataSize) override;
private:
  double m_errorBound;
};

  } // Gpu
} // Drp
