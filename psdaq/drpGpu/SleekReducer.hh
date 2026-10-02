/**
 * @file
 * @brief SleekReducer, a ReducerAlgo plugin for the GPU DRP; its .cu file defines the createReducer() factory.
 */
#pragma once

#include "ReducerAlgo.hh"

#include <SingleCompressorLossy.hh>

namespace Drp {
  namespace Gpu {

/** Reducer that compresses each calibrated buffer with SLEEK::SingleCompressorLossy, recorded into the Reducer graph. */
class SleekReducer : public ReducerAlgo
{
public:
  /** Construct the compressor with the calibrated buffer size and the value 3.0; print its banner if verbose is set. */
  SleekReducer(const Parameters& para, const MemPoolGpu& pool, Detector& det);
  /** Does nothing; empty body. */
  virtual ~SleekReducer() {}

  /** Return true: the compressor is recorded into the Reducer graph. */
  bool   hasGraph()    const override { return true; }
  /** Return the maximum compressed size reported by the compressor (maxSize()). */
  size_t payloadSize() const override { return m_compressor.maxSize(); }
  /** Let the compressor record its kernels into the captured stream (SLEEK::SingleCompressorLossy::updateGraph()) for the state, index, calibrated and data buffers, with buffer sizes given in bytes. */
  void   recordGraph(cudaStream_t       stream,
                     unsigned*    const state,
                     unsigned*    const index,
                     float const* const calibBuffers,
                     size_t       const calibBufsCnt,
                     uint8_t*     const dataBuffers,
                     size_t       const dataBufsCnt) override;
  /** Launch graph on stream and queue an asynchronous copy of the reduced size, stored just before data buffer index, to *dataSize; *retCode is set to 0. */
  void     reduce   (cudaGraphExec_t,
                     cudaStream_t,
                     unsigned  index,
                     size_t*   dataSize,
                     unsigned* retCode) override;
  /** Return 0; nothing is configured. */
  int      configure(const nlohmann::json& configureMsg,
                     const nlohmann::json& connectMsg,
                     size_t                collectionId) override { return 0; }
  /** Add the names of the reduced data (algorithm sleek, one UINT8 array named sleek) under ReducerNamesIndex and register them in the detector's names lookup; returns 0. */
  unsigned configure(XtcData::Xtc&, const void* bufEnd) override;
  /** Set the shape of the sleek array to dataSize elements in the data description; the data itself stays on the GPU. */
  void     event    (XtcData::Xtc&, const void* bufEnd, unsigned dataSize) override;
private:
  SLEEK::SingleCompressorLossy m_compressor;
};

  } // Gpu
} // Drp
