/**
 * @file
 * @brief Drp::Gpu::AreaDetector, the GPU DRP detector registered for detType fakecam.
 */
#pragma once

#include "Detector.hh"

#include "drp/AreaDetector.hh"          // Detector implementation
#include "drp/drp.hh"

namespace Drp {
  namespace Gpu {

/** GPU DRP detector for detType fakecam (registered in PGPDetectorApp). It wraps an XpmDetector-based detector and sizes the calibration buffers; its pedestal and gain arrays are not implemented yet. */
class AreaDetector : public Gpu::Detector
{
public:
  /** Create the wrapped XpmDetector-based detector and the calibration buffers for the pixel count: twice the sim_length kwarg, or 1024 by default. Asserts that the pixels fit in a DMA buffer after the DMA descriptor and TimingHeader. */
  AreaDetector(Parameters& para, MemPoolGpu& pool);
  /** Destroy the calibration buffers. */
  virtual ~AreaDetector() override;
public:
  /** Call configure on the wrapped XpmDetector, logging an error if it fails, and return 0 in every case. No event names are added (that code is disabled). */
  unsigned configure(const std::string& config_alias, XtcData::Xtc&, const void* bufEnd) override;
  /** Log an info message; does nothing else (data handling is a TODO in the code). */
  void event(XtcData::Dgram& dgram, const void* bufEnd, PGPEvent* event, uint64_t count) override;
  using Gpu::Detector::event;
public:
//  __device__ void calibrate(float*    const calib,
//                            uint16_t* const raw,
//                            unsigned  const count) const;
  /** Return 14: the gain range is in bits 15-14 and the data value in bits 13-0. */
  unsigned     rangeOffset() const override { return 14; }
  /** Return 2. */
  unsigned     rangeBits()   const override { return 2; }
  /** Return null; not implemented yet (per the TODO comment in the code). */
  float const* pedestals_d() const override { return nullptr; }; // @todo: TBD
  /** Return null; not implemented yet (per the TODO comment in the code). */
  float const* gains_d()     const override { return nullptr; }; // @todo: TBD

//  void recordGraph(cudaStream_t          stream,
//                   const unsigned&       index,
//                   uint16_t const* const data) override;
private:
  unsigned m_nPixels;
};

  } // Gpu
} // Drp
