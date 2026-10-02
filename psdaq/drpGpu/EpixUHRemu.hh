/**
 * @file
 * @brief Drp::Gpu::EpixUHRemu, the GPU DRP detector registered for detType epixuhremu, with the ePixUHR geometry and gain range constants.
 */
#pragma once

#include "Detector.hh"

#include "drp/AreaDetector.hh"          // Detector implementation
#include "drp/drp.hh"

namespace Drp {
  namespace Gpu {

/** GPU DRP detector for detType epixuhremu (registered in PGPDetectorApp). It wraps an XpmDetector-based detector, allocates the calibration buffers and per-range pedestal and gain arrays, and names the raw data (array raw) in the Configure xtc. */
class EpixUHRemu : public Gpu::Detector
{
public:
  /** Create the wrapped XpmDetector-based detector, the calibration buffers for NPixels pixels and device arrays of NRanges times NPixels pedestals and gains, which beginrun() fills. Asserts that NPixels 16-bit values fit in a DMA buffer after the TimingHeader. */
  EpixUHRemu(Parameters& para, MemPoolGpu& pool);
  /** Free the pedestal and gain arrays and destroy the calibration buffers. */
  virtual ~EpixUHRemu() override;

public:  // ePixUHR parameters:
  static const unsigned NumAsics   {   6 };  ///< Number of ASICs (6).
  static const unsigned NumRows    { 192 };  ///< Rows per ASIC (192).
  static const unsigned NumCols    { 168 };  ///< Columns per ASIC (168).
  static const unsigned NPixels    { NumAsics*NumRows*NumCols };  ///< Total number of pixels, NumAsics * NumRows * NumCols (193536).
  static const unsigned RangeOffset{  14 };  ///< Bit position of the gain range field in a raw 16-bit value (14); the bits below it hold the data value.
  static const unsigned RangeBits  {   2 };  ///< Width of the gain range field (2 bits).
  static const unsigned NRanges    {   4 };  ///< Number of gain ranges with their own pedestal and gain arrays (4).
public:
  unsigned configure(const std::string& config_alias, XtcData::Xtc&, const void* bufEnd) override;
  unsigned beginrun(XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& runInfo) override;
  void event(XtcData::Dgram& dgram, const void* bufEnd, PGPEvent* event, uint64_t count) override;
  using Gpu::Detector::event;
public:
  /** Return RangeOffset (14). */
  unsigned     rangeOffset() const override { return RangeOffset; }
  /** Return RangeBits (2). */
  unsigned     rangeBits()   const override { return RangeBits; }
  /** Return the device pedestal array (NRanges sets of NPixels values); beginrun() sets every pedestal to 0. */
  float const* pedestals_d() const override { return m_pedsVec_d; };
  /** Return the device gain array, laid out like pedestals_d(); beginrun() sets every gain to 1. */
  float const* gains_d()     const override { return m_gainsVec_d; };

  //void recordGraph(cudaStream_t          stream,
  //                 const unsigned&       index,
  //                 uint16_t const* const data) override;
  //CalibrateFn_t* getCalibFn() const override; // Not working
private:
  float* m_pedsVec_d;                   // [NRanges * NPixels]
  float* m_gainsVec_d;                  // [NRanges * NPixels]
};

  } // Gpu
} // Drp
