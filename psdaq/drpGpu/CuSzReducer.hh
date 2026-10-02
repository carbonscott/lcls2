/**
 * @file
 * @brief CuSzReducer, a ReducerAlgo plugin for the GPU DRP; its .cu file defines the createReducer() factory.
 */
#pragma once

#include "ReducerAlgo.hh"

#include <api_v2.h>
#include <cusz.h>
#include <cusz/type.h>

namespace Drp {
  namespace Gpu {

/** Reducer that compresses each calibrated buffer with cuSZ (Lorenzo predictor, relative error bound 1.2e-4, Huffman coding). It runs through reduce(), not a graph; its library targets are commented out in CMakeLists.txt and meson.build. */
class CuSzReducer : public ReducerAlgo
{
public:
  /** Select the Lorenzo predictor, relative mode and error bound 1.2e-4; the cuSZ resource manager is created by the first reduce(). */
  CuSzReducer(const Parameters& para, const MemPoolGpu& pool, Detector& det);
  /** Release the cuSZ resource manager if one was created. */
  virtual ~CuSzReducer();

  /** Return false: compression runs through reduce(), not a CUDA graph. */
  bool   hasGraph()    const override { return false; }
  /** Return the calibrated buffer size. */
  size_t payloadSize() const override { return m_pool.calibBufsSize(); }
  /** Not implemented: logs a critical message and aborts. */
  void   recordGraph(cudaStream_t       stream,
                     unsigned*    const state,
                     unsigned*    const index,
                     float const* const calibBuffers,
                     size_t       const calibBufsCnt,
                     uint8_t*     const dataBuffers,
                     size_t       const dataBufsCnt) override;
  /** Compress calibrated buffer index with cuSZ (creating the resource manager on first use) and copy the result into data buffer index with a blocking cudaMemcpy. Sets *dataSize to the compressed length and *retCode to 0; the graph argument is not used. */
  void     reduce   (cudaGraphExec_t,
                     cudaStream_t,
                     unsigned  index,
                     size_t*   dataSize,
                     unsigned* retCode) override;
  /** Return 0; nothing is configured. */
  int      configure(const nlohmann::json& configureMsg,
                     const nlohmann::json& connectMsg,
                     size_t                collectionId) override { return 0; }
  /** Add the names of the reduced data (algorithm cuSZ, one UINT8 array named cuSZ) under ReducerNamesIndex and register them in the detector's names lookup; returns 0. */
  unsigned configure(XtcData::Xtc&, const void* bufEnd) override;
  /** Set the shape of the cuSZ array to dataSize elements in the data description; the data itself stays on the GPU. */
  void     event    (XtcData::Xtc&, const void* bufEnd, unsigned dataSize) override;
private:
  psz_predtype  m_predictor;
  psz_mode      m_mode;
  double        m_eb;
  psz_header    m_header;
  psz_resource* m_m;
};

  } // Gpu
} // Drp
