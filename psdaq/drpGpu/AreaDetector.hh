#pragma once

#include "Detector.hh"

#include "drp/AreaDetector.hh"          // Detector implementation
#include "drp/drp.hh"

namespace Drp {
  namespace Gpu {

class AreaDetector : public Gpu::Detector
{
public:
  AreaDetector(Parameters& para, MemPoolGpu& pool);
  virtual ~AreaDetector() override;
public:
  unsigned configure(const std::string& config_alias, XtcData::Xtc&, const void* bufEnd) override;
  void event(XtcData::Dgram& dgram, const void* bufEnd, PGPEvent* event, uint64_t count) override;
  using Gpu::Detector::event;
public:
  unsigned     rangeOffset() const override { return 14; }
  unsigned     rangeBits()   const override { return 2; }
  // PedGainCalib reads both for every pixel, so they must exist: pedestals of 0 and gains
  // of 1 in every range, which leave the 14-bit value as it is
  float const* pedestals_d() const override { return m_peds_d; };
  float const* gains_d()     const override { return m_gains_d; };

  // Launches the _event kernel template instantiated with PedGainCalib, from
  // this .so, so that the calibration is inlined into the kernel
  void recordEvent(cudaStream_t, unsigned blocks, unsigned threads,
                   const EventKernelArgs&) override;
private:
  unsigned m_nPixels;
  float*   m_peds_d {nullptr};            // [1 << rangeBits()][m_nPixels]
  float*   m_gains_d{nullptr};            // [1 << rangeBits()][m_nPixels]
};

  } // Gpu
} // Drp
