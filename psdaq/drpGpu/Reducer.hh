/**
 * @file
 * @brief Reducer, which runs the loaded ReducerAlgo instances (one per worker) on calibrated GPU buffers and returns the reduced sizes.
 */
#pragma once

#include <cstddef>
#include <vector>
#include <thread>
#include <atomic>
#include <string>
#include <map>
#include <memory>

#include <cuda_runtime.h>
#include <cuda/std/atomic>

#include "MemPool.hh"
#include "RingQueue_DtoH.hh"
#include "RingQueue_HtoD.hh"
#include "ReducerAlgo.hh"
#include "drp/spscqueue.hh"
#include "psdaq/service/Dl.hh"
#include <nlohmann/json.hpp>
#include "psdaq/service/fast_monotonic_clock.hh"


namespace Pds {
  class MetricExporter;
}

namespace XtcData {
  class Xtc;
}

namespace Drp {
  namespace Gpu {

class Detector;

/** Per-worker counters in pinned host memory, exported by Reducer::setupMetrics(). */
struct ReducerMetrics
{
  std::vector<uint64_t*> state;  ///< Kernel state monitors, exported as DRP_redState; the kernel writes to them are commented out, so they stay 0.
  std::vector<uint64_t*> inpWtCtr;  ///< Input counters, exported as DRP_inpWtCtr; the kernel increment is commented out.
  std::vector<uint64_t*> outWtCtr;  ///< Output counters, exported as DRP_outWtCtr; the kernel increment is commented out.
};

/** Runs the data reduction on the GPU for PGPDrp: loads the reducer library named by the reducer kwarg, creates one ReducerAlgo per worker, and passes buffer indices in and ReducerTuple results out through per-worker queues. With graph algorithms, and without HOST_LAUNCHED_REDUCERS, each worker is a self-relaunching CUDA graph fed by device ring queues. */
class Reducer
{
public:
  /** Create one stream per worker in green_ctx and load the algorithms (aborting on failure). Then create the reduce buffers (header space plus the larger of payloadSize() and maxTrSize less the header) and the per-worker queues, state and return-code words and metric counters. */
  Reducer(const Parameters&, MemPoolGpu&, Detector&,
          cudaExecutionContext_t             green_ctx,
          const std::atomic<bool>&           terminate_h,
          const cuda::std::atomic<unsigned>& terminate_d);
  /** Free the per-worker device and pinned memory, stop the host queues and threads, destroy the graphs and algorithms, close the library, and destroy the reduce buffers and streams. */
  ~Reducer();
  /** Add the per-worker DRP_redState, DRP_inpWtCtr, DRP_outWtCtr, DRP_inputQueue and DRP_outputQueue metrics and DRP_reduceTime to exporter; returns 0. */
  int setupMetrics(const std::shared_ptr<Pds::MetricExporter>,
                   std::map<std::string, std::string>& labels);
  /** If the algorithms use graphs, call ReducerAlgo::configure() with the Configure and Connect messages on every instance. Returns -1 if one fails, else 0. */
  int configure(const nlohmann::json& configureMsg,
                const nlohmann::json& connectMsg,
                size_t                collectionId);
  /** If the algorithms use graphs, call ReducerAlgo::configure(xtc, be) on every instance and record, instantiate and upload one graph per worker. Returns true on failure, else false. */
  bool setup(XtcData::Xtc& xtc, const void* be);
  /** Launch the worker graphs if the algorithms use them; in builds with HOST_LAUNCHED_REDUCERS, start one host worker thread per worker instead. Returns false. */
  bool startup();
  /** Shut down the host input and output queues if the algorithms do not use graphs; otherwise does nothing. */
  void shutdown();
  /** Print the head and tail of each worker's input and output ring queues if the algorithms use graphs. */
  void dump() const;
  /** Queue buffer index for worker. Returns false only when the device input ring queue is full (graph algorithms without HOST_LAUNCHED_REDUCERS); host queue pushes return true. */
  bool start(unsigned worker, unsigned index) {
#ifdef HOST_LAUNCHED_REDUCERS
    m_inputQueues[worker].push(index);  return true;
#else
    //printf("*** Reducer::start: wkr %u, idx %u\n", worker, index);
    if (m_algos[0]->hasGraph()) { return m_inputQueues2[worker].h->push(index);    }
    else                        { m_inputQueues[worker].push(index);  return true; }
#endif
  }
  /** Pop the next result of worker into items. With the device ring queue, returns false if none is ready; with a host queue, blocks until one arrives and returns false after shutdown. */
  bool receive(unsigned worker, ReducerTuple* items) {
#ifdef HOST_LAUNCHED_REDUCERS
    return m_outputQueues[worker].pop(*items);
#else
    return m_algos[0]->hasGraph() ? m_outputQueues2[worker].h->pop(items)
                                  : m_outputQueues[worker].pop(*items);
#endif
  }
  /** Let the first algorithm instance describe dataSize of reduced data in xtc (ReducerAlgo::event()); does nothing if no algorithm is loaded. */
  void event(XtcData::Xtc& xtc, const void* bufEnd, size_t dataSize)
    { if (m_algos.size())  m_algos[0]->event(xtc, bufEnd, dataSize); }
private:
  bool        _setupAlgos(Detector&);
  int         _setupGraph(unsigned instance);
  cudaGraph_t _recordGraph(unsigned instance);
  void        _worker(unsigned instance);
private:
  using timePoint_t = std::chrono::time_point<Pds::fast_monotonic_clock>;
  MemPoolGpu&                                     m_pool;
  Pds::Dl                                         m_dl;
  std::vector<ReducerAlgo*>                       m_algos;
  std::atomic<bool> const&                        m_terminate;
  cuda::std::atomic<unsigned> const&              m_terminate_d;
  std::vector<unsigned*>                          m_retCode_d;
  std::vector<unsigned*>                          m_state_d;
  std::vector<SPSCQueue<unsigned> >               m_inputQueues;
  std::vector<SPSCQueue<ReducerTuple> >           m_outputQueues;
  std::vector<Ptr<RingQueueHtoD<unsigned> > >     m_inputQueues2;
  std::vector<Ptr<RingQueueDtoH<ReducerTuple> > > m_outputQueues2;
  std::vector<std::thread>                        m_threads;
  std::vector<cudaStream_t>                       m_streams;
  std::vector<timePoint_t>                        m_t0;
  std::vector<cudaGraphExec_t>                    m_graphExecs;
  std::vector<unsigned*>                          m_indices;
  uint64_t                                        m_reduce_us;
  Parameters const&                               m_para;
  ReducerMetrics                                  m_metrics;
};

  } // Gpu
} // Drp
