/**
 * @file
 * @brief Jungfrau, the DRP detector class for Jungfrau modules controlled through the sls library.
 */
#pragma once

#include "BEBDetector.hh"
#include "JungfrauDetectorId.hh"
#include "psalg/alloc/Allocator.hh"
#include "xtcdata/xtc/NamesId.hh"
#include "xtcdata/xtc/Xtc.hh"

#include "sls/sls_detector_defs.h"

/** Namespace of the external sls detector library (headers under sls/); only sls::Detector is forward-declared here. */
namespace sls
{
  class Detector;
} // namespace sls

namespace Drp
{

class JungfrauIdLookup;

/** BEBDetector for one or more Jungfrau modules (one per PGP lane), controlled through sls::Detector and assembled from per-packet UDP data. */
class Jungfrau : public BEBDetector
{
public:
    /** Count the modules from laneMask, read segNums and slsHosts (aborting if they are missing or do not match the module count), connect sls::Detector to the hosts (stopping a running detector first if needed), initialize the BEBDetector with the epics_prefix kwarg and install a one-shot handler for SIGINT, SIGABRT and SIGTERM. A timebase kwarg of 119M sets the extra event-batcher level. */
    Jungfrau(Parameters* para, MemPool* pool);
    /** Clear the global pointer used by the signal handler and call cleanup(). */
    virtual ~Jungfrau();

    unsigned configureScan(const nlohmann::json& scanKeys, XtcData::Xtc& xtc, const void* bufEnd) override;
    unsigned stepScan(const nlohmann::json& stepInfo, XtcData::Xtc& xtc, const void* bufEnd) override;
    unsigned beginrun (XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& runInfo) override;
    unsigned enable (XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& info) override;
    unsigned disable(XtcData::Xtc& xtc, const void* bufEnd, const nlohmann::json& info) override;
    /** If the sls detector exists, stop it, destroy it and free its shared memory. */
    void cleanup();

private:
    void _connectionInfo(PyObject*) override;
    unsigned _configure(XtcData::Xtc&, const void* bufEnd, XtcData::ConfigIter&) override;
    void _event(XtcData::Xtc&, const void* bufEnd, uint64_t l1count, std::vector<XtcData::Array<uint8_t>>&) override;
    std::string _buildDetId(uint64_t sensor_id,
                            uint64_t board_id,
                            uint64_t firmware,
                            std::string software,
                            std::string hostname);
    uint32_t _countNumHotPixels(size_t mod, uint16_t* rawData, uint16_t hotPixelThreshold, uint32_t numPixels);
    void _loadConfigEnums(size_t mod, XtcData::Names& configNames, XtcData::ConfigIter& configo);
    bool _configueDAC(size_t mod, sls::defs::dacIndex dac, int value, bool mV = false);
    void _configure_module_thread(size_t mod,
                                  XtcData::Names& configNames,
                                  XtcData::ConfigIter& configo,
                                  std::atomic<unsigned>& numFailed);
    unsigned _configure_module(size_t mod, XtcData::Names& configNames, XtcData::ConfigIter& configo);

private:
    unsigned m_nModules { 0 };
    uint16_t m_hotPixelThreshold { 15000 };
    uint32_t m_maxHotPixels { 3400 };
    std::vector<bool> m_inFixedGain; // Need to know if in fixed gain for hot pixel calc.
    std::vector<unsigned> m_segNos;
    std::vector<std::string> m_serNos;
    std::vector<std::string> m_slsHosts;
    std::vector<uint16_t> m_modIds;
    std::unique_ptr<sls::Detector> m_slsDet;
    std::unordered_map<std::string, std::unordered_map<uint32_t, std::string>> m_configEnums;
    JungfrauIdLookup m_idLookup;
};

} // namespace Drp
