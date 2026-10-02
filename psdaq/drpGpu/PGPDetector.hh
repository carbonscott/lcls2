/**
 * @file
 * @brief The GPU DRP: PGPDrp, which connects Reader, TrgInpGen and Reducer, and its TebReceiver, which records the reduced events.
 */
#pragma once

#include <memory>
#include <thread>
#include <atomic>
#include <cuda_runtime.h>
#include <cuda/std/atomic>
#include <nlohmann/json.hpp>
#include "drp/DrpBase.hh"
#include "drp/spscqueue.hh"
#include "Reader.hh"
#include "TrgInpGen.hh"
#include "Reducer.hh"
#include "FileWriter.hh"

class ZmqContext;

namespace XtcData {
  class Dgram;
  class Timestamp;
}
namespace Pds {
  class MetricExporter;
  namespace Eb {
    class TebContributor;
    class ResultDgram;
  }
}

namespace Drp {
  namespace Gpu {

class Detector;
class MemPoolGpu;

/** Counters of the GPU TebReceiver, exported by TebReceiver::setupMetrics(). */
struct TebReceiverMetrics
{
  uint64_t cmpCtr          {0};  ///< Results passed to complete() (DRP_cmpCtr).
  uint64_t recCtr          {0};  ///< Results taken by the recorder thread (DRP_recCtr).
  uint64_t reducerStarts   {0};  ///< Events handed to a reducer (DRP_redStarts).
  uint64_t reducerReceives {0};  ///< Reducer results received by the recorder (DRP_redRcvs).
  uint64_t freeCtr         {0};  ///< Pebbles released by the recorder (DRP_evFrCtr).
};

/** Buffer index and TEB result, queued by TebReceiver::complete() for the recorder thread. */
using ResultTuple = std::tuple<unsigned, const Pds::Eb::ResultDgram*>;

/** TebReceiver of the GPU DRP. complete() queues each result for a recorder thread and starts a reducer for events to be persisted or monitored. The recorder waits for the reduced data, writes datagrams from GPU memory with cuFile and small data with SmdWriter, posts monitored events and frees the buffers. */
class TebReceiver: public Drp::TebReceiverBase
{
public:
  /** Store the parameters, the DRP and the terminate flag; setup() creates the writers and the recorder thread. */
  TebReceiver(const Parameters&, DrpBase&, const std::atomic<bool>& terminate);
  /** Destroy the recorder stream if one exists and stop the recorder thread (teardown()). */
  ~TebReceiver() override;
  /** Return the cuFile FileWriter created by setup() (not valid before setup()). */
  FileWriterBase& fileWriter() override { return *m_fileWriter; }
  /** Return the SmdWriter created by setup() (not valid before setup()). */
  SmdWriterBase& smdWriter() override { return *m_smdWriter; };
  /** Create a cuFile FileWriter with a 32 MiB buffer and O_DIRECT and an SmdWriter, then start the recorder thread, which creates its stream in green_ctx. */
  void setup(cudaExecutionContext_t green_ctx);
  /** Shut down the record queue and join the recorder thread. */
  void teardown();
protected:
  int setupMetrics(const std::shared_ptr<Pds::MetricExporter>,
                   std::map<std::string, std::string>& labels) override;
  void complete(unsigned index, const Pds::Eb::ResultDgram&) override;
private:
  void _recorder(cudaExecutionContext_t green_ctx);
  void _writeDgram(XtcData::Dgram*, void* devPtr);
private:
  Pds::Eb::MebContributor&         m_mon;
  const std::atomic<bool>&         m_terminate;
  cudaStream_t                     m_stream;
  //std::unique_ptr<FileWriterAsync> m_fileWriter;
  std::unique_ptr<FileWriter>      m_fileWriter;
  std::unique_ptr<Drp::SmdWriter>  m_smdWriter;
  unsigned                         m_worker;      // For cycling through reducers
  SPSCQueue<ResultTuple>           m_recordQueue;
  std::shared_ptr<TrgInpGen>       m_trgInpGen;
  std::thread                      m_recorderThread;
  const Parameters&                m_para;
  TebReceiverMetrics               m_metrics;
};

/** DRP for the GPU detectors (Drp::Gpu::PGPDrp). Configure creates the Reader, TrgInpGen and Reducer, which run in green contexts that each hold part of the GPU's SMs. A collector thread builds the EbDgrams and TEB inputs for the buffers that TrgInpGen reports. */
class PGPDrp : public DrpBase
{
public:
  /** Set the DMA lane and virtual channel mask (aborting on failure), split the GPU into three green contexts (6 SMs or the minimum partition size if larger, 40 SMs, and the rest), allocate the device terminate flag and install the GPU TebReceiver. */
  PGPDrp(Parameters&, MemPoolGpu&, Detector&, ZmqContext&);
  /** Free the device terminate flag. */
  virtual ~PGPDrp();
  /** Run DrpBase::configure(), clear the terminate flags, create the Reader and TrgInpGen in the first green context and the Reducer in the second, and configure the Reducer with the message body and the Connect message. Returns an error message, empty on success. */
  std::string configure(const nlohmann::json& msg);
  /** Run DrpBase::unconfigure(), set the host and device terminate flags, shut down the Reducer, stop the recorder and collector threads, and destroy the Reducer, TrgInpGen and Reader. Returns 0. */
  unsigned unconfigure();
  /** Run DrpBase::startup(), set up the Reader, TrgInpGen and Reducer, start the collector thread and the recorder (third green context), then start the Reader, TrgInpGen and Reducer. Returns an error message, empty on success. */
  std::string startup(XtcData::Xtc& xtc, const void* be);
  /** Queue buffer index to reducer worker wkr (Reducer::start()); returns false if its input queue is full. */
  bool reducerStart(unsigned wkr, unsigned& index) const
    { return m_reducer->start(wkr, index); }
  /** Get the next result of reducer worker wkr (Reducer::receive()). */
  bool reducerReceive(unsigned wkr, ReducerTuple* items) const
    { return m_reducer->receive(wkr, items); }
  /** Let the Reducer describe sz of reduced data in xtc (Reducer::event()). */
  void reducerEvent(XtcData::Xtc& xtc, const void* be, size_t sz)
    { m_reducer->event(xtc, be, sz); }
  /** Release the DMA buffer of the event in pebble buffer idx, found through the event counter in its TimingHeader (Reader::freeDma()). */
  void freeBuffers(unsigned idx);
  /** Print the Reducer queue states (Reducer::dump()). */
  void reducerDump() const
    { m_reducer->dump(); }
private:
  int _setupMetrics(const std::shared_ptr<Pds::MetricExporter>);
  void _setupGreenContexts(MemPoolGpu& memPool);
  void _collector();
private:
  const Parameters&            m_para;
  Detector&                    m_det;
  cudaExecutionContext_t       m_green_ctx[3];
  std::atomic<bool>            m_terminate;
  cuda::std::atomic<unsigned>* m_terminate_d;
  std::shared_ptr<Reader>      m_reader;
  std::unique_ptr<TrgInpGen>   m_trgInpGen;
  std::unique_ptr<Reducer>     m_reducer;
  std::thread                  m_collectorThread;
  uint64_t                     m_nNoTrDgrams;
};

  } // Gpu
} // Drp
