/**
 * @file
 * @brief Drp::Gpu::TrgInpGen, which runs the trigger primitive on the GPU for each received buffer and checks the buffer headers on the host for the collector.
 */
#pragma once

#include <cstddef>
#include <vector>
#include <atomic>
#include <thread>

#include <cuda_runtime.h>
#include <cuda/std/atomic>

#include "MemPool.hh"
#include "RingIndex_DtoD.hh"
#include "RingIndex_DtoH.hh"
#include "drp/spscqueue.hh"
#include "psdaq/trigger/src/TriggerPrimitive.hh"
#include "xtcdata/xtc/TransitionId.hh"

namespace Pds {
  class MetricExporter;
  class TimingHeader;
}

namespace Drp {
  namespace Gpu {

class Reader;

/** Counters of TrgInpGen, exported by TrgInpGen::setupMetrics(). The first three are in pinned host memory for the kernels, which update them only if DBG is enabled in TrgInpGen.cu. */
struct TrgInpGenMetrics
{
  uint64_t* state    {nullptr};  ///< Kernel state monitor (DRP_tigState).
  uint64_t* rcvWtCtr {nullptr};  ///< Buffers taken from the reader queues (DRP_tigRcv).
  uint64_t* fwdWtCtr {nullptr};  ///< Buffers passed to the device-to-host queue (DRP_tigFwd).

  uint64_t  pndWtCtr     {0};  ///< Buffers popped by the receiver thread (DRP_colRcv).
  uint64_t  pidWtCtr     {0};  ///< Exported as DRP_pidWtCtr but never incremented.

  uint64_t  nEvents      {0};  ///< Buffers accepted by the receiver thread (DRP_evtCtr and drp_event_rate).
  uint64_t  nDmaRet      {0};  ///< Buffers accepted in the last pass of the receiver loop (drp_num_dma_ret).
  uint64_t  nHdrMismatch {0};  ///< Not used.
  uint64_t  dmaSize      {0};  ///< Size in bytes of the last DMA (drp_dma_size).
  uint64_t  dmaBytes     {0};  ///< Total DMA bytes (drp_pgp_byte_rate).
  uint64_t  latency      {0};  ///< TimingHeader latency in microseconds, updated when the pulse ID has advanced by more than 1300000/14 (about 10 Hz, per the code comment) (drp_th_latency).
  uint64_t  nDmaErrors   {0};  ///< DMAs with error bits set in the descriptor header (drp_num_dma_errors).
  uint64_t  nNoComRoG    {0};  ///< Buffers without this DRP's readout group (drp_num_no_common_rog).
  uint64_t  nMissingRoGs {0};  ///< SlowUpdates missing readout groups of rogMask (drp_num_missing_rogs).
  uint64_t  nTmgHdrError {0};  ///< TimingHeaders with the error bit set (drp_num_th_error).
  uint64_t  nPgpJumps    {0};  ///< Jumps in the TimingHeader event counter (drp_num_pgp_jump).
};

/** Runs the trigger primitive for each received buffer in a self-relaunching CUDA graph, taking buffers from the reader queues in turn and passing them to the host through a ring queue. A receiver thread then checks each buffer's DMA descriptor and TimingHeader, fills in its PGPEvent and tells the collector how many buffers are ready. */
class TrgInpGen
{
public:
  /** Copy the reader queue pointers to the device and create the device-to-host queue, a stream in green_ctx, the device state, index and return-code words and the pinned metric counters. */
  TrgInpGen(const Parameters&, MemPoolGpu&, const std::shared_ptr<Reader>&,
            Pds::Trg::TriggerPrimitive*, cudaExecutionContext_t,
            const std::atomic<bool>& terminate, const cuda::std::atomic<unsigned>& terminate_d);
  /** Destroy the graph and free what the constructor allocated. */
  ~TrgInpGen(); // = default;
  /** Reset the counters and add the DRP_tigState, DRP_tigRcv, DRP_tigFwd, DRP_colRcv, DRP_pidWtCtr, DRP_colQueOcc, DRP_evtCtr and drp_* metrics to exporter; returns 0. */
  int setupMetrics(const std::shared_ptr<Pds::MetricExporter>,
                   std::map<std::string, std::string>& labels);
  /** Record, instantiate and upload the graph. Returns true on failure, else false. */
  bool setup();
  /** Reset the event counter check and launch the graph. Returns false. */
  bool startup();
  /** Start the receiver thread, which pushes the number of ready buffers to collectorQueue after each pass and shuts the queue down when it exits. */
  void start(SPSCQueue<unsigned>& collectorQueue);
  /** Join the receiver thread, which exits once the terminate flag is set. */
  void shutdown();
  /** Does nothing; empty body. */
  void handleBrokenEvent(const PGPEvent&) {}
  /** Reset the last event counter used by the jump check to 0 (per the code comment, an EvtCounter reset); called by startup() and on BeginRun. */
  void resetEventCounter() { m_lastComplete = 0; } // EvtCounter reset
private:
  int _setupGraph();
  cudaGraph_t _recordGraph(cudaStream_t);
  void _receiver(SPSCQueue<unsigned>& collectorQueue);
private:
  MemPoolGpu&                        m_pool;
  Pds::Trg::TriggerPrimitive*        m_triggerPrimitive;
  const std::atomic<bool>&           m_terminate;
  const cuda::std::atomic<unsigned>& m_terminate_d;
  unsigned*                          m_retCode_d;
  unsigned*                          m_state_d;
  unsigned*                          m_index_d;
  cudaStream_t                       m_stream;
  cudaGraphExec_t                    m_graphExec;
  const std::shared_ptr<Reader>&     m_reader;
  RingIndexDtoD**                    m_readerQueues_d;
  Ptr<RingIndexDtoH>                 m_trgInpGenQueue;
  std::thread                        m_receiverThread;
  uint64_t                           m_lastPid;
  uint64_t                           m_latPid;
  uint32_t                           m_lastComplete;
  XtcData::TransitionId::Value       m_lastTid;
  uint32_t                           m_lastData[6];
  const Parameters&                  m_para;
  TrgInpGenMetrics                   m_metrics;
};

  } // Gpu
} // Drp
