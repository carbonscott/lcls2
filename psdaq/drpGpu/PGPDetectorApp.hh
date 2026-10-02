/**
 * @file
 * @brief Drp::Gpu::PGPDetectorApp, the collection application of the GPU DRP, and DetectorFactory, which loads the GPU detector libraries.
 */
#pragma once

#include <utility>
#include <memory>
#include <string>
#include <unordered_map>
#include <thread>
#include <Python.h>

#include "drp/drp.hh"
#include "drp/DrpBase.hh"
#include "psdaq/service/Collection.hh"
#include "psdaq/service/Dl.hh"
#include "MemPool.hh"
#include "Detector.hh"

namespace Drp {
  namespace Gpu {

class PGPDrp;

/** Creates GPU detectors from shared libraries: each detector type name is mapped to a library that defines createDetector(). */
class DetectorFactory
{
public:
    /** Map detector type name to library solib (both copied). */
    void register_type(const std::string& name, const std::string& solib);
    /** Load the library registered for name and call its createDetector() with para and pool. Returns null if name is not registered or loading fails. */
    Drp::Gpu::Detector* create(const std::string& name, Parameters& para, MemPoolGpu& pool);
private:
    static
    Drp::Gpu::Detector* _instantiate(Pds::Dl& dl, const std::string& soName,
                                     Parameters& para, MemPoolGpu& pool);
private:
    Pds::Dl m_dl;
    std::unordered_map<std::string, std::string> m_create_funcs;
};

/** Collection application of the GPU DRP: handles the control transitions and drives a Drp::Gpu::PGPDrp and the GPU detector. In simulator mode (device /dev/null) it also starts phase 2 of each transition with Detector::issuePhase2(). */
class PGPDetectorApp : public CollectionApp
{
public:
    /** Join the collection as a drp process, create the GPU memory pool from para, initialize Python and release the GIL. initialize() must be called next. */
    PGPDetectorApp(Parameters& para);
    /** Reset as handleReset() does, delete the detector and finalize Python. */
    virtual ~PGPDetectorApp();
    /** Register the GPU detector types (fakecam, epixuhremu, epixuhrsim) with their libraries, create the detector for detType (throwing a std::string if that fails) and create the PGPDrp. It is separate from the constructor so that the destructor, which finalizes Python, runs if it throws (per the code comment). */
    void initialize();
private:
    nlohmann::json connectionInfo(const nlohmann::json& msg) override;
    void connectionShutdown() override;
    void handleReset(const nlohmann::json& msg) override;
private:
    void handleDealloc(const nlohmann::json& msg) override;
    void handleConnect(const nlohmann::json& msg) override;
    void handleDisconnect(const nlohmann::json& msg) override;
    void handlePhase1(const nlohmann::json& msg) override;
    std::string _disable(XtcData::Xtc& xtc, const void* const bufEnd,
                         const nlohmann::json& phase1Info);
    std::string _endrun(const nlohmann::json& phase1Info);
    void _unconfigure();
    void _disconnect();
private:
    Parameters&             m_para;
    MemPoolGpu              m_pool;
    Detector*               m_det;
    std::unique_ptr<PGPDrp> m_drp;
    bool                    m_unconfigure;
    std::string             m_lastKey;
    PyThreadState*          m_pysave;
    DetectorFactory         m_factory;
};

  } // Gpu
} // Drp
