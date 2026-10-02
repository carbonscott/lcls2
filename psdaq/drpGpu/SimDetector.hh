/**
 * @file
 * @brief Drp::Gpu::SimDetector, the base of simulated GPU DRP detectors that write events into the GPU DMA buffers without a PGP device.
 */
#pragma once

#include "Detector.hh"

#include "xtcdata/xtc/TransitionId.hh"

#include <thread>
#include <chrono>
#include <cuda_runtime.h>

namespace XtcData {
  class Xtc;
  class Dgram;
}

namespace Drp {
  class Parameters;
  class MemPool;
  namespace Gpu {

    /** Base of simulated GPU detectors (EpixUHRsim uses it). A thread started by connectionInfo() writes a TimingHeader, and for L1Accepts the payload from _genL1Payload() (copied only if the sim_l1_verify kwarg is present; its size is always counted), into the GPU DMA buffers for each transition queued by issuePhase2(). After Enable it keeps generating L1Accepts (every sim_l1_delay us, default 1 s) and SlowUpdates (sim_su_rate per second, default 1). */
    class SimDetector : public Gpu::Detector
    {
    protected:
      SimDetector(Parameters* para, MemPoolGpu* pool, unsigned len=100);
      virtual ~SimDetector();
      void shutdown() override;
      nlohmann::json connectionInfo(const nlohmann::json& msg) override;
      void connectionShutdown() override;
      void connect(const nlohmann::json&, const std::string& collectionId) override;
      void issuePhase2(XtcData::TransitionId::Value) override;
    protected:
      virtual size_t _genL1Payload(uint8_t** buffer, size_t index, size_t bufSize) = 0;
    private:
      size_t _genTimingHeader(uint8_t* buffer, XtcData::TransitionId::Value);
      void _trigger(uint8_t* buffer, uint32_t dmaSize) const;
      void _eventSimulator();
    private:
      using ms_t = std::chrono::milliseconds;
      std::atomic<bool>                       m_terminate;
      cudaStream_t                            m_stream;
      unsigned                                m_readoutGroup;
      uint32_t                                m_evtCounter;
      unsigned                                m_length;
      SPSCQueue<XtcData::TransitionId::Value> m_eventQueue;
      std::thread                             m_eventThread;
      unsigned                                m_l1Delay;
      ms_t                                    m_suPeriod;
};

  } // Gpu
} // Drp
