/**
 * @file
 * @brief LcReducer, a ReducerAlgo plugin for the GPU DRP; its .cu file defines the createReducer() factory.
 */
#pragma once

#include "ReducerAlgo.hh"

#include <lc-compressor-QUANT_ABS_0_f32-BIT_4-RZE_1.hh>

namespace Drp {
  namespace Gpu {

/** Reducer that compresses each calibrated buffer with an LC framework compressor (the QUANT_ABS_0_f32, BIT_4, RZE_1 pipeline, per the included header name), recorded into the Reducer graph. */
class LcReducer : public ReducerAlgo
{
public:
  /** Construct the compressor with the calibrated buffer size and the value 3; print its banner if verbose is set. */
  LcReducer(const Parameters& para, const MemPoolGpu& pool, Detector& det);
  /** Does nothing; empty body. */
  virtual ~LcReducer() {}

  /** Return true: the compressor is recorded into the Reducer graph. */
  bool   hasGraph()    const override { return true; }
  /** Return the maximum compressed size reported by the compressor (maxSize()). */
  size_t payloadSize() const override { return m_compressor.maxSize(); }
  /** Let the compressor record its kernels into the captured stream (LC_framework::Compressor::updateGraph()) for the state, index, calibrated and data buffers, with buffer sizes given in bytes. */
  void   recordGraph(cudaStream_t       stream,
                     unsigned*    const state_d,
                     unsigned*    const index_d,
                     float const* const calibBuffers_d,
                     size_t       const calibBufsCnt,
                     uint8_t*     const dataBuffers_d,
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
  /** Add the names of the reduced data (algorithm lc, one UINT8 array named lc) under ReducerNamesIndex and register them in the detector's names lookup; returns 0. */
  unsigned configure(XtcData::Xtc&, const void* bufEnd) override;
  /** Set the shape of the lc array to dataSize elements in the data description; the data itself stays on the GPU. */
  void     event    (XtcData::Xtc&, const void* bufEnd, unsigned dataSize) override;
private:
  LC_framework::Compressor m_compressor;
};

  } // Gpu
} // Drp
