
#include "XpmDetector.hh"
#include "XpmInfo.hh"
#include "MemPoolSim.hh"
#include "psalg/utils/SysLog.hh"
#include <unistd.h>
#include <netdb.h>
#include <arpa/inet.h>

using namespace XtcData;
using json = nlohmann::json;
using logging = psalg::SysLog;

namespace Drp {

static PyObject* _check(PyObject* obj) {
    if (!obj) {
        PyErr_Print();
        logging::critical("**** python error");
        abort();
    }
    return obj;
}

XpmDetector::XpmDetector(Parameters* para, MemPool* pool, unsigned len) :
    Detector(para, pool),
    m_xmodule(nullptr),
    m_sim(pool->sim()),
    m_length(len)
{
    // With a simulated device, xpmdet_config programs an emulated timing receiver (the
    // l2si_drp root on psdaq.sim.rogue_dev's in-process registers); MemPoolSim's timing
    // frames come from simxpm
    if (m_sim)  _simInstall();
    _init();
}

void XpmDetector::_simInstall()
{
    PyObject* sim = _check(PyImport_ImportModule("psdaq.sim.rogue_dev"));
    Py_DECREF(_check(PyObject_CallMethod(sim, "install", "ss", m_para->device.c_str(), "xpmdet")));
    Py_DECREF(sim);
    logging::info("XpmDetector: xpmdet_config runs against simulated device %s",
                  m_para->device.c_str());
}

void XpmDetector::_init()
{
    std::map<std::string,std::string>::iterator it = m_para->kwargs.find("timebase");
    const char* timebase = (it != m_para->kwargs.end()) ? it->second.data() : "186M";

    // returns new reference
    m_xmodule = _check(PyImport_ImportModule("psdaq.configdb.xpmdet_config"));

    PyObject* pDict = _check(PyModule_GetDict(m_xmodule));
    PyObject* pFunc = _check(PyDict_GetItemString(pDict, "xpmdet_init"));
    Py_DECREF(_check(PyObject_CallFunction(pFunc,"sisi",
                                           m_para->device.c_str(),
                                           m_para->laneMask,
                                           timebase,
                                           m_para->verbose)));
}

json XpmDetector::connectionInfo(const json& msg)
{
    PyObject* pDict  = _check(PyModule_GetDict(m_xmodule));
    PyObject* pFunc  = _check(PyDict_GetItemString(pDict, "xpmdet_connectionInfo"));
    PyObject* mbytes = _check(PyObject_CallFunction(pFunc,"s",msg.dump().c_str()));
    json result = xpmInfo(PyLong_AsLong(PyDict_GetItemString(mbytes, "paddr")));
    if (m_sim) {                        // The timing link is simxpm's, not the emulated RxId
        unsigned paddr = m_sim->paddr();
        logging::info("XpmDetector: emulated RxId 0x%lx; link id 0x%x from simxpm",
                      PyLong_AsLong(PyDict_GetItemString(mbytes, "paddr")), paddr);
        result = xpmInfo(paddr);
    }
    Py_DECREF(mbytes);
    return result;
}

// setup up device to receive data over pgp
void XpmDetector::connect(const json& connect_json, const std::string& collectionId)
{
    unsigned readoutGroup = connect_json["body"]["drp"][collectionId]["det_info"]["readout"];
    // FIXME make configureable
    std::map<std::string,std::string>::iterator it = m_para->kwargs.find("sim_length");
    if (it != m_para->kwargs.end())
        m_length = stoi(it->second);

    PyObject* pDict  = _check(PyModule_GetDict(m_xmodule));
    PyObject* pFunc  = _check(PyDict_GetItemString(pDict, "xpmdet_connect"));
    Py_DECREF(_check(PyObject_CallFunction(pFunc,"ii",readoutGroup,m_length)));

    if (m_sim) {
        m_connectMsg = connect_json;
        m_sim->connect(readoutGroup, m_length);
    }
}

unsigned XpmDetector::configure(const std::string& config_alias, XtcData::Xtc& xtc, const void* bufEnd)
{
    if (m_sim)  _simConfigure(config_alias);
    return 0;
}

// The sim payload carries one value from the configuration database, so that an edit of
// <detName>_<segment> is visible in the recorded data.  It is optional: when the database
// has no such entry, the 'sim_seed' kwarg (or 0) is used.  The value is written into every
// event (see MemPoolSim.hh), so a reader checks it rather than this log line.
void XpmDetector::_simConfigure(const std::string& config_alias)
{
    unsigned    seed   = 0;
    std::string source = "default";
    auto it = m_para->kwargs.find("sim_seed");
    if (it != m_para->kwargs.end()) {
        seed   = std::stoul(it->second, nullptr, 0);
        source = "kwarg sim_seed";
    }

    PyObject* pModule = PyImport_ImportModule("psdaq.configdb.get_config");
    PyObject* pFunc   = pModule ? PyObject_GetAttrString(pModule, "get_config_json") : nullptr;
    PyObject* pJson   = pFunc ? PyObject_CallFunction(pFunc, "sssi",
                                                      m_connectMsg.dump().c_str(),
                                                      config_alias.c_str(),
                                                      m_para->detName.c_str(),
                                                      m_para->detSegment) : nullptr;
    const char* text = (pJson && PyUnicode_Check(pJson)) ? PyUnicode_AsUTF8(pJson) : nullptr;
    if (text) {
        // Accept the value at the top level or in the 'user' section
        auto lookup = [](const json& j) -> const json* {
            return j.is_object() && j.contains("sim_seed") && j.at("sim_seed").is_number_integer()
                 ? &j.at("sim_seed") : nullptr;
        };
        json cfg = json::parse(text, nullptr, false);
        const json* value = cfg.is_object() && cfg.contains("user") ? lookup(cfg.at("user")) : nullptr;
        if (!value)  value = lookup(cfg);
        if (value) {
            seed   = value->get<unsigned>();
            source = "configdb " + config_alias + "/" + m_para->detName + "_" + std::to_string(m_para->detSegment);
        }
    }
    if (source.rfind("configdb", 0) != 0) {
        if (PyErr_Occurred())  PyErr_Print();
        logging::warning("No integer sim_seed in configdb %s/%s_%u", config_alias.c_str(),
                         m_para->detName.c_str(), m_para->detSegment);
    }
    Py_XDECREF(pJson);
    Py_XDECREF(pFunc);
    Py_XDECREF(pModule);

    m_sim->seed(seed);
    logging::info("Sim payload seed %u (0x%08x) from %s", seed, seed, source.c_str());
}

void XpmDetector::shutdown()
{
    PyObject* pDict  = _check(PyModule_GetDict(m_xmodule));
    PyObject* pFunc  = _check(PyDict_GetItemString(pDict, "xpmdet_unconfig"));
    Py_DECREF(_check(PyObject_CallFunction(pFunc,"")));
}

void XpmDetector::connectionShutdown()
{
    PyObject* pDict  = _check(PyModule_GetDict(m_xmodule));
    PyObject* pFunc  = _check(PyDict_GetItemString(pDict, "xpmdet_connectionShutdown"));
    Py_DECREF(_check(PyObject_CallFunction(pFunc,"")));

    if (m_sim)  m_sim->disconnect();
}
}
