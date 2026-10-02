/**
 * @file
 * @brief Drp::Gpu::Detector, the base of the GPU DRP detectors, the NamesId indices they use, and the createDetector() factory declaration.
 */
#pragma once

#include "drp/Detector.hh"

#include "MemPool.hh"                   // Needed for the base class
#include "psdaq/service/range.hh"
#include "psdaq/aes-stream-drivers/GpuAsyncUser.h"

#include <cuda_runtime.h>

namespace Drp {
  namespace Gpu {

/** Panel limit used to space the NamesId indices below. */
enum { MaxPnlsPerNode = 10  /**< Maximum number of panels per node, 10 (per the code comment, taken from BEBDetector.hh). */ };       // From BEBDetector.hh
/** NamesId indices for the xtc names of the GPU DRP (per the code comment). */
enum { ConfigNamesIndex = Drp::NamesIndex::BASE, /**< Drp::NamesIndex::BASE. */ 
       EventNamesIndex  = unsigned(ConfigNamesIndex) + unsigned(MaxPnlsPerNode), /**< ConfigNamesIndex plus MaxPnlsPerNode. */ 
       FexNamesIndex    = unsigned(EventNamesIndex)  + unsigned(MaxPnlsPerNode), /**< EventNamesIndex plus MaxPnlsPerNode. */ 
       ReducerNamesIndex  /**< FexNamesIndex plus 1; the reducers register the names of the reduced data under it. */ };         // index for xtc NamesId

// Not working:
//typedef void CalibrateFn_t(float*    const calib,
//                           uint16_t* const raw,
//                           unsigned  const nElements);

/** Base of the GPU DRP detectors (Drp::Gpu::Detector). The transition methods forward to a wrapped Drp::Detector for the PGP device when one was created with _initialize(); the pure virtual methods give the Reader calibration kernel its constants. */
class Detector : public Drp::Detector
{
public:
  /** Pass para and pool to Drp::Detector; no wrapped detector until _initialize() is called. */
  Detector(Parameters* para, MemPoolGpu* pool) :
    Drp::Detector(para, pool),
    m_det(nullptr)
  {}
  /** Delete the wrapped detector, if any. */
  virtual ~Detector() { if (m_det)  delete m_det; }

  /** Return this object. */
  Gpu::Detector* gpuDetector() override { return this; }

  /** Return the wrapped detector's connectionInfo(msg), or a default-constructed (null) JSON value if there is no wrapped detector. */
  nlohmann::json connectionInfo(const nlohmann::json& msg) override;
  /** Call connectionShutdown() on the wrapped detector, if any. */
  void connectionShutdown() override;
  /** If there is a wrapped detector, copy nodeId to it and call its connect(connect_json, collectionId). */
  void connect(const nlohmann::json& connect_json, const std::string& collectionId) override;
  /** Call configure() on the wrapped detector, logging an error if it returns non-zero. Returns its result, or 0 if there is no wrapped detector. */
  unsigned configure(const std::string& config_alias, XtcData::Xtc& xtc, const void* bufEnd) override;
  /** Call beginrun() on the wrapped detector, logging an error if it returns non-zero. Returns its result, or 0 if there is no wrapped detector. */
  unsigned beginrun (XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& runInfo) override;
  /** Call beginstep() on the wrapped detector, logging an error if it returns non-zero. Returns its result, or 0 if there is no wrapped detector. */
  unsigned beginstep(XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& stepInfo) override;
  /** Call enable() on the wrapped detector, logging an error if it returns non-zero. Returns its result, or 0 if there is no wrapped detector. */
  unsigned enable   (XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& info) override;
  /** Call disable() on the wrapped detector, logging an error if it returns non-zero. Returns its result, or 0 if there is no wrapped detector. */
  unsigned disable  (XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& info) override;
  using Drp::Detector::event;
  /** Call shutdown() on the wrapped detector, if any. */
  void shutdown() override;

  // @todo: What to do about these?
  //// Scan methods.  Default is to fail.
  //unsigned configureScan(const nlohmann::json& stepInfo, XtcData::Xtc& xtc, const void* bufEnd) override {return 1;};
  //unsigned stepScan     (const nlohmann::json& stepInfo, XtcData::Xtc& xtc, const void* bufEnd) override {return 1;};

  /** Return the address just past the DmaDsc at the start of host write buffer index of the MemPoolGpu (hostWrtBufs()), as a TimingHeader pointer. */
  Pds::TimingHeader* getTimingHeader(uint32_t index) const override
  {
    auto       memPool    = m_pool->getAs<MemPoolGpu>();
    const auto dmaBuffers = memPool->hostWrtBufs();
    const auto cnt        = memPool->hostWrtBufsSize()/sizeof(*dmaBuffers);
    auto       dmaDsc     = (DmaDsc*)&dmaBuffers[index * cnt];
    return reinterpret_cast<Pds::TimingHeader*>(&dmaDsc[1]);
  }

  //// Device methods can't be virtual due to the vtable not containing device pointers
  //__device__ void calibrate(float*    const calib,
  //                          uint16_t* const raw,
  //                          unsigned  const count,
  //                          unsigned  const rangeOffset,
  //                          unsigned  const rangeBits) const;
  /** Pure virtual: return the bit position of the gain range field in a raw 16-bit value. The Reader calibration kernel uses the bits below it as the data value. */
  virtual unsigned     rangeOffset() const = 0;
  /** Pure virtual: return the width in bits of the gain range field. */
  virtual unsigned     rangeBits()   const = 0;
  /** Pure virtual: return the device array of pedestals, one set per gain range of one value per pixel. The Reader kernel computes (data - pedestal) * gain. */
  virtual float const* pedestals_d() const = 0;
  /** Pure virtual: return the device array of gains, laid out like pedestals_d(). */
  virtual float const* gains_d()     const = 0;

  //virtual void recordGraph(cudaStream_t          stream,
  //                         const unsigned&       index_d,
  //                         uint16_t const* const data) = 0;
  //virtual CalibrateFn_t* getCalibFn() const { return nullptr; } // Not working

  /** Start phase 2 of a transition; PGPDetectorApp calls it after phase 1 only in simulator mode (device /dev/null). Does nothing here. */
  virtual void issuePhase2(XtcData::TransitionId::Value) {} // Used in simulator mode only
  /** Return device buffers of reference calibrated data for checking (used in simulator mode only, per the code comment); null here. */
  virtual float const* referenceBuffers() const { return nullptr; } // Used in simulator mode only
  /** Return the number of reference buffers; 0 here. */
  virtual unsigned     referenceBufCnt()  const { return 0; }       // Used in simulator mode only
protected:
  template<typename T>
  void _initialize(Parameters& para, MemPoolGpu& pool) {
    // Create a Drp::Detector for the panel/PGP device
    m_det = new T(&para, &pool);
  }
protected:
  Drp::Detector* m_det;
};

  } // Gpu
} // Drp


extern "C"
{
  /** Type of createDetector(). */
  typedef Drp::Gpu::Detector* DetectorFactoryFn_t(Drp::Parameters&, Drp::Gpu::MemPoolGpu&);

  /** Factory function defined by each GPU detector library (AreaDetector, EpixUHRemu, EpixUHRsim): return a new detector. PGPDetectorApp's DetectorFactory loads it from the library named for the detector type. */
  Drp::Gpu::Detector* createDetector(Drp::Parameters& para, Drp::Gpu::MemPoolGpu& pool);
}
