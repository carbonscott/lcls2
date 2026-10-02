/**
 * @file
 * @brief EipReducer, a ReducerAlgo plugin for the GPU DRP; its .cu file defines the createReducer() factory.
 */
#pragma once

#include "ReducerAlgo.hh"

#include <eip/Compressor.hh>

namespace Drp {
  namespace Gpu {

/** Reducer that compresses each calibrated buffer with EIP::Compressor. hasGraph() returns false although recordGraph() and reduce() work with a graph; its library targets are commented out in CMakeLists.txt and meson.build. */
class EipReducer : public ReducerAlgo
{
public:
  /** Construct the compressor with the calibrated buffer size and the value 3.0. */
  EipReducer(const Parameters& para, const MemPoolGpu& pool, Detector& det);
  /** Does nothing; empty body. */
  virtual ~EipReducer();

  /** Return false, so Reducer neither records nor launches a graph for this reducer. */
  bool   hasGraph()    const override { return false; }
  /** Return the calibrated buffer size. */
  size_t payloadSize() const override { return m_pool.calibBufsSize(); }
  /** Let the compressor record its kernels into the captured stream (EIP::Compressor::updateGraph()) for the state, index, calibrated and data buffers, with buffer sizes given in bytes. */
  void   recordGraph(cudaStream_t       stream,
                     unsigned*    const state,
                     unsigned*    const index,
                     float const* const calibBuffers,
                     size_t       const calibBufsCnt,
                     uint8_t*     const dataBuffers,
                     size_t       const dataBufsCnt) override;
  /** Launch graph on stream and queue an asynchronous copy of the reduced size, stored just before data buffer index, to *dataSize; *retCode is set to 0. Reducer::_worker passes a null graph because hasGraph() is false. */
  void     reduce   (cudaGraphExec_t,
                     cudaStream_t,
                     unsigned  index,
                     size_t*   dataSize,
                     unsigned* retCode) override;
  /** Return 0; nothing is configured. */
  int      configure(const nlohmann::json& configureMsg,
                     const nlohmann::json& connectMsg,
                     size_t                collectionId) override { return 0; }
  /** Add the names of the reduced data (algorithm eip, one UINT8 array named eip) under ReducerNamesIndex and register them in the detector's names lookup; returns 0. */
  unsigned configure(XtcData::Xtc&, const void* bufEnd) override;
  /** Set the shape of the eip array to dataSize elements in the data description; the data itself stays on the GPU. */
  void     event    (XtcData::Xtc&, const void* bufEnd, unsigned dataSize) override;
private:
  EIP::Compressor m_compressor;
};

  } // Gpu
} // Drp
