/**
 * @file
 * @brief NoOpReducer, a ReducerAlgo plugin for the GPU DRP; its .cu file defines the createReducer() factory.
 */
#pragma once

#include "ReducerAlgo.hh"


namespace Drp {
  namespace Gpu {

/** Reducer that copies the calibrated floats unchanged into the output buffer, using its own CUDA kernel. */
class NoOpReducer : public ReducerAlgo
{
public:
  /** If detType is epixuhrsim and the sim_l1_verify kwarg is non-zero, keep the detector's reference buffers (the check that uses them is commented out). Allocate and zero a device return-code word. */
  NoOpReducer(const Parameters& para, const MemPoolGpu& pool, Detector& det);
  /** Free the device return-code word. */
  virtual ~NoOpReducer();

  /** Return true, since NoOpReducer.cu defines HAS_GRAPH. */
  bool   hasGraph()    const override; // { return true; }
  /** Return the calibrated buffer size, since the output is a copy. */
  size_t payloadSize() const override { return m_pool.calibBufsSize(); }
  /** Record one launch of the copy kernel. In builds without HOST_LAUNCHED_REDUCERS it acts when *state is 1: it copies calibrated buffer *index to its data buffer, then the last block stores the size in bytes just before the data, writes 0 to the return code and sets *state to 2. The grid size depends on the threads per multiprocessor (1536 or 2048; other values abort). */
  void   recordGraph(cudaStream_t       stream,
                     unsigned*    const state,
                     unsigned*    const index,
                     float const* const calibBuffers,
                     size_t       const calibBufsCnt,
                     uint8_t*     const dataBuffers,
                     size_t       const dataBufsCnt) override;
  /** Launch graph on stream and queue asynchronous copies of the reduced size, stored just before data buffer index, and of the return code to *dataSize and *retCode. */
  void     reduce   (cudaGraphExec_t,
                     cudaStream_t,
                     unsigned  index,
                     size_t*   dataSize,
                     unsigned* retCode) override;
  /** Log a message and return 0. */
  int      configure(const nlohmann::json& configureMsg,
                     const nlohmann::json& connectMsg,
                     size_t                collectionId) override;
  /** Add the names of the reduced data (algorithm noOp, one UINT8 array named noOp) under ReducerNamesIndex and register them in the detector's names lookup; returns 0. */
  unsigned configure(XtcData::Xtc&, const void* bufEnd) override;
  /** Set the shape of the noOp array to dataSize elements in the data description; the data itself stays on the GPU. */
  void     event    (XtcData::Xtc&, const void* bufEnd, unsigned dataSize) override;
private:
  float const* m_refBufs_d;
  unsigned     m_refBufCnt;
  unsigned*    m_retCode_d;
};

  } // Gpu
} // Drp
