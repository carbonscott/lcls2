/**
 * @file
 * @brief Drp::Gpu::Reader, which receives the FPGA DMA buffers on the GPU, copies their headers to host memory and calibrates their payloads.
 */
#pragma once

#include <cstddef>
#include <vector>
#include <atomic>
#include <string>
#include <map>
#include <memory>

#include <cuda_runtime.h>
#include <cuda/std/atomic>

#include "drp/drp.hh"
#include "MemPool.hh"                   // For Ptr
#include "RingIndex_HtoD.hh"
#include "RingIndex_DtoD.hh"

namespace Pds {
  class MetricExporter;
  class TimingHeader;
  namespace Trg {
    class TriggerPrimitive;
  }
}

namespace Drp {
  namespace Gpu {

class Detector;

/** Per-reader counters in pinned host memory, exported by Reader::setupMetrics(); the kernels update them only if DBG is enabled in Reader.cu. */
struct ReaderMetrics
{
  std::vector<uint64_t*> states;  ///< Kernel state monitors (DRP_readerState).
  std::vector<uint64_t*> pblWtCtrs;  ///< Counts of pebble indices taken (DRP_pblWtCtr).
  std::vector<uint64_t*> dmaWtCtrs;  ///< Counts of DMA completions seen (DRP_dmaWtCtr).
  std::vector<uint64_t*> fwdWtCtrs;  ///< Counts of buffers passed to the reader queue (DRP_rdrFwd).
};

/** Receives the FPGA DMA buffers on the GPU. Each of nReaders streams runs a self-relaunching CUDA graph that, in turn with the other streams, waits for a DMA, takes the next pebble index, copies the DMA descriptor and TimingHeader to the pinned host write buffer and calibrates the payload into the calibration buffer. It then passes the buffer on through its reader queue and gives the DMA buffer back to the FPGA. */
class Reader
{
public:
  /** Read the nReaders kwarg (default 1; aborts unless it is a power of 2 that divides the DMA buffer count). Create the per-reader indices, queues, streams (in green_ctx, lowest priority), states and metric counters, the pebble queue (starting full) and the host write buffers (DMA descriptor, TimingHeader and trgPrimitiveSize bytes each). */
  Reader(const Parameters&, MemPoolGpu&, Detector&, size_t trgPrimitiveSize,
         const cudaExecutionContext_t&, const cuda::std::atomic<unsigned>& terminate_d);
  /** Destroy the reader graphs and free what the constructor allocated, including the host write buffers. */
  ~Reader();
  /** Add the per-reader DRP_readerState, DRP_pblWtCtr, DRP_dmaWtCtr, DRP_rdrFwd and DRP_rdrQueOcc metrics and DRP_pblQueOcc to exporter; returns 0. */
  int setupMetrics(const std::shared_ptr<Pds::MetricExporter>,
                   std::map<std::string, std::string>& labels);
  /** Record, instantiate and upload one graph per reader. Returns true on failure, else false. */
  bool setup();
  /** Clear the handshake word of every DMA buffer and give it to the FPGA (with gpuSetWriteEn() first in HOST_REARMS_DMA builds), reset the DMA buffer index and launch the reader graphs. Returns true only if gpuSetWriteEn() fails, else false. */
  bool startup();
  /** Clear the event mask and advance the pebble queue head so that the readers can reuse a pebble buffer; RingIndexHtoD::push() ignores the buffer index passed to it. */
  void freeDma(PGPEvent*);
  /** Free the DMA buffers of all events whose mask is still set, then flush the pebble pool. */
  void flush();
public:
  /** Return the memory pool. */
  auto& pool()         const { return m_pool; }
  /** Return the per-reader queues (host and device pointers). */
  auto& readerQueues() const { return m_readerQueues; }
  /** Return the number of reader streams. */
  auto  nReaders()     const { return m_nReaders; }
private:
  int         _setupGraph(unsigned reader);
  cudaGraph_t _recordGraph(unsigned reader);
private:
  MemPoolGpu&                        m_pool;
  Detector&                          m_det;
  const cudaExecutionContext_t&      m_ctx;
  const cuda::std::atomic<unsigned>& m_terminate_d;
  std::vector<cudaStream_t>          m_streams;
  std::vector<unsigned*>             m_dmaBufferIdxes;
  std::vector<unsigned*>             m_pebbleIdxes;
  std::vector<cudaGraphExec_t>       m_graphExecs;
  Ptr<RingIndexHtoD>                 m_pebbleQueue;
  std::vector< Ptr<RingIndexDtoD> >  m_readerQueues;
  std::vector<unsigned*>             m_states_d;
  CUdeviceptr*                       m_dmaBuffers;    // [dmaCount][maxDmaSize]
  CUdeviceptr*                       m_fpgaRegs;
  unsigned                           m_nReaders;
  const Parameters&                  m_para;
  ReaderMetrics                      m_metrics;
};

  } // Gpu
} // Drp
