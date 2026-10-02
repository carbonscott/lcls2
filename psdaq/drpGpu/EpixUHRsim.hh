/**
 * @file
 * @brief Drp::Gpu::EpixUHRsim, the simulated GPU DRP detector registered for detType epixuhrsim, with the ePixUHR geometry and gain range constants.
 */
#pragma once

#include "Detector.hh"

#include "xtcdata/xtc/TransitionId.hh"
#include "drp/AreaDetector.hh"          // Detector implementation
#include "drp/drp.hh"

namespace Drp {
  namespace Gpu {

/** Simulated GPU DRP detector for detType epixuhrsim (registered in PGPDetectorApp). It wraps a SimDetector that replays 10 randomly generated events with random gain ranges, sets random pedestals and gains at BeginRun, and keeps reference calibrated results for checking. */
class EpixUHRsim : public Gpu::Detector
{
public:
  /** Create the wrapped simulator and generate its 10 events, create the calibration buffers for NPixels pixels and device arrays of NRanges times NPixels pedestals and gains. Asserts that NPixels 16-bit values fit in a DMA buffer after the DMA descriptor and TimingHeader. */
  EpixUHRsim(Parameters& para, MemPoolGpu& pool);
  /** Free the pedestal and gain arrays and destroy the calibration buffers. */
  virtual ~EpixUHRsim() override;

public:  // ePixUHR parameters:
  static const unsigned NumAsics   {   6 };  ///< Number of ASICs (6).
  static const unsigned NumRows    { 192 };  ///< Rows per ASIC (192).
  static const unsigned NumCols    { 168 };  ///< Columns per ASIC (168).
  static const unsigned NPixels    { NumAsics*NumRows*NumCols };  ///< Total number of pixels, NumAsics * NumRows * NumCols (193536).
  static const unsigned RangeOffset{  14 };  ///< Bit position of the gain range field in a raw 16-bit value (14); the bits below it hold the data value.
  static const unsigned RangeBits  {   2 };  ///< Width of the gain range field (2 bits).
  static const unsigned NRanges    {   4 };  ///< Number of gain ranges with their own pedestal and gain arrays (4).
public:
  unsigned configure  (const std::string& config_alias, XtcData::Xtc&, const void* bufEnd) override;
  unsigned beginrun   (XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& info) override;
  void event(XtcData::Dgram& dgram, const void* bufEnd, PGPEvent* event, uint64_t count) override;
  using Gpu::Detector::event;
public:
//  __device__ void calibrate(float*    const calib,
//                            uint16_t* const raw,
//                            unsigned  const count) const;
  /** Return RangeOffset (14). */
  unsigned     rangeOffset() const override { return RangeOffset; }
  /** Return RangeBits (2). */
  unsigned     rangeBits()   const override { return RangeBits; }
  /** Return the device pedestal array (NRanges sets of NPixels values); beginrun() fills it with random values below 2^14. */
  float const* pedestals_d() const override { return m_pedsVec_d; };
  /** Return the device gain array, laid out like pedestals_d(); beginrun() fills it with random values below 2^14. */
  float const* gains_d()     const override { return m_gainsVec_d; };

//  void recordGraph(cudaStream_t          stream,
//                   const unsigned&       index,
//                   uint16_t const* const data) override;

  /** Forward the transition to the wrapped simulator, which queues it for its event thread. */
  void issuePhase2(XtcData::TransitionId::Value tid) override;
  /** Return the simulator's device buffers of reference calibrated data, one per generated event, computed at BeginRun. */
  float const* referenceBuffers() const override;
  /** Return the number of reference buffers (the 10 generated events). */
  unsigned     referenceBufCnt()  const override;
private:
  float* m_pedsVec_d;                   // [NRanges * NPixels]
  float* m_gainsVec_d;                  // [NRanges * NPixels]
};

  } // Gpu
} // Drp
