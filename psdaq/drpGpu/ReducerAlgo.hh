/**
 * @file
 * @brief ReducerAlgo, the interface of the GPU data reduction plugins, and ReducerTuple. Safe to include in CPU code (per the file comment).
 */
// This header is safe to include in CPU code.

#pragma once

#include "Detector.hh"                  // For NamesIndex enums
#include "drp/drp.hh"                   // For NamesIndex
#include "xtcdata/xtc/ShapesData.hh"    // For Alg
#include "xtcdata/xtc/NamesLookup.hh"
#include <nlohmann/json.hpp>

#include <cuda_runtime.h>

namespace XtcData {
  class Xtc;
} // XtcData

namespace Drp {
  struct Parameters;

  namespace Gpu {
    class MemPoolGpu;
    template <typename T> class RingQueueHtoD;
    template <typename T> class RingQueueDtoH;

/** Result of reducing one buffer, passed from the reducer back to the recorder. */
struct ReducerTuple
{
  unsigned index;  ///< Index of the buffer that was reduced.
  size_t   dataSize;  ///< Size in bytes of the reduced data.
};

/** Base of the GPU data reduction algorithms. Each one is built as a shared library whose name is lib, the reducer kwarg and .so; Reducer loads it and calls createReducer() once per worker. */
class ReducerAlgo
{
public:
  /** Keep references to the parameters, the memory pool and the detector. */
  ReducerAlgo(const Parameters& para, const MemPoolGpu& pool, Detector& det) : m_para(para), m_pool(pool), m_det(det) {}
  /** Does nothing; empty virtual destructor. */
  virtual ~ReducerAlgo() {}

  /** Pure virtual: return true if the algorithm is recorded into a CUDA graph with recordGraph(). Reducer checks the first instance to choose device ring queues and graphs (true) or host queues (false), and calls the configure() overloads only when it is true. */
  virtual bool   hasGraph()    const = 0;
  /** Pure virtual: return the largest reduced data size in bytes; Reducer sizes the reduce buffers from it, raising it to maxTrSize less the datagram header if that is larger. */
  virtual size_t payloadSize() const = 0;
  /** Pure virtual: record into stream, which is being captured, the kernels that reduce calibrated buffer *index (calibBufsCnt floats each) into data buffer *index (dataBufsCnt bytes each). As NoOpReducer and the Reducer kernels show, the kernels act when *state is 1, store the reduced size in the size_t just before the data, and set *state to 2. */
  virtual void   recordGraph(cudaStream_t       stream,
                             unsigned*    const state,
                             unsigned*    const index,
                             float const* const calibBuffers,
                             size_t       const calibBufsCnt,
                             uint8_t*     const dataBuffers,
                             size_t       const dataBufsCnt) = 0;
  /** Pure virtual: run the reduction of buffer index on stream (launching graph if the algorithm uses one) and return the reduced size and an error code through dataSize and retCode, possibly by asynchronous copies on stream. Called only by Reducer worker threads, which exist in builds with HOST_LAUNCHED_REDUCERS. */
  virtual void     reduce   (cudaGraphExec_t,
                             cudaStream_t,
                             unsigned  index,
                             size_t*   dataSize,
                             unsigned* retCode) = 0;
  /** Pure virtual: configure the algorithm from the Configure and Connect messages (per the code comment, the configDb configuration); return non-zero on failure. */
  virtual int      configure(const nlohmann::json& configureMsg,
                             const nlohmann::json& connectMsg,
                             size_t                collectionId) = 0;                 // Retrieve configDb configuration
  /** Pure virtual: add the names (descriptions) of the reduced data to xtc, without going past bufEnd (per the code comment); return non-zero on failure. */
  virtual unsigned configure(XtcData::Xtc&, const void* bufEnd) = 0;                  // attach descriptions to xtc
  /** Describe dataSize of reduced data in the event xtc (per the code comment, fill the xtc data description); does nothing in this base class. */
  virtual void     event    (XtcData::Xtc&, const void* bufEnd, unsigned dataSize) {} // fill xtc data description
protected:
  const Parameters& m_para;
  const MemPoolGpu& m_pool;
  Detector&         m_det;
};

  } // Gpu
} // Drp


extern "C"
{
  /** Type of createReducer(), the factory function that each reducer library exports with C linkage. */
  typedef Drp::Gpu::ReducerAlgo* reducerAlgoFactoryFn_t(const Drp::Parameters&,
                                                        const Drp::Gpu::MemPoolGpu&,
                                                        Drp::Gpu::Detector&);

  /** Factory function defined by each reducer library: return a new instance of its ReducerAlgo. */
  Drp::Gpu::ReducerAlgo* createReducer(const Drp::Parameters&,
                                       const Drp::Gpu::MemPoolGpu&,
                                       Drp::Gpu::Detector&);
}
