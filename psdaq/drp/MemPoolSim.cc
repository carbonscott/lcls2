#include "MemPoolSim.hh"

#include "psdaq/service/EbDgram.hh"
#include "xtcdata/xtc/TransitionId.hh"
#include "psalg/utils/SysLog.hh"

#include <nlohmann/json.hpp>
#include <zmq.h>
#include <sys/eventfd.h>
#include <sys/prctl.h>
#include <unistd.h>
#include <cstdlib>
#include <cstring>
#include <chrono>

using json = nlohmann::json;
using logging = psalg::SysLog;
using XtcData::TransitionId;

static_assert(sizeof(Pds::TimingHeader) == 32, "TimingHeader layout assumed by MemPoolSim::fill");

namespace Drp {

static const char     SimPrefix[]   = "sim://";
static const uint32_t EvtCtrMask    = 0xffffff;        // As in DrpBase.cc
static const uint32_t Sentinel      = 0xabababab;      // As in MemPoolCpu
static const unsigned DefDmaCount   = 1024;
static const unsigned DefDmaSize    = 0x10000;

static unsigned _kwarg(const Parameters& para, const char* key, unsigned dflt)
{
    auto it = para.kwargs.find(key);
    return it == para.kwargs.end() ? dflt : std::stoul(it->second, nullptr, 0);
}

bool MemPoolSim::isSimDevice(const std::string& device)
{
    return device.rfind(SimPrefix, 0) == 0;
}

size_t MemPoolSim::fill(uint8_t* buffer, const Frame& f, uint32_t evtCounter,
                        unsigned lane, unsigned length, uint32_t seed)
{
    // TimingHeader: pulseId|control, time (ns, s), env, evtCounter, 2 opaque words
    auto th = reinterpret_cast<uint32_t*>(buffer);
    memcpy(buffer, &f.pulseIdAndControl, sizeof(f.pulseIdAndControl));
    th[2] = f.nanoseconds;
    th[3] = f.seconds;
    th[4] = f.env;
    th[5] = evtCounter;
    th[6] = 0;
    th[7] = 0;
    if (length == 0)  return sizeof(Pds::TimingHeader);

    uint64_t pid = f.pulseIdAndControl & ((1ull << 56) - 1);
    uint32_t* w  = th + sizeof(Pds::TimingHeader)/sizeof(uint32_t);
    const uint32_t head[] = { uint32_t(pid), uint32_t(pid >> 32), f.seq, seed };
    for (unsigned k = 0; k < length; ++k) {
        w[k] = k < 4 ? head[k] : seed + uint32_t(pid) + k + (lane << 16);
    }
    return sizeof(Pds::TimingHeader) + length * sizeof(uint32_t);
}

MemPoolSim::MemPoolSim(const Parameters& para) :
    MemPool     (para),
    m_alias     (para.alias),
    m_nLanes    (__builtin_popcount(para.laneMask)),
    m_laneMask  (para.laneMask),
    m_virtChan  (0),
    m_efd       (eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC)),
    m_memory    (nullptr),
    m_terminate (false),
    m_connected (false),
    m_changed   (false),
    m_group     (0),
    m_length    (0),
    m_seed      (0),
    m_registered(false),
    m_paddr     (0),
    m_evtCounter(0),
    m_credit    (0),
    m_nOverruns (0)
{
    std::string rest = para.device.substr(sizeof(SimPrefix) - 1);
    m_endpoint = rest.find("://") == std::string::npos ? "tcp://" + rest : rest;

    if (m_efd < 0) {
        logging::critical("MemPoolSim: eventfd failed: %m");
        abort();
    }

    m_dmaCount = _kwarg(para, "sim_dma_count", DefDmaCount);
    m_dmaSize  = _kwarg(para, "sim_dma_size",  DefDmaSize);
    if (m_nLanes == 0 || m_dmaCount < m_nLanes || m_dmaSize <= sizeof(Pds::TimingHeader)) {
        logging::critical("MemPoolSim: bad geometry: lanes 0x%x, sim_dma_count %u, sim_dma_size %u",
                          para.laneMask, m_dmaCount, m_dmaSize);
        abort();
    }
    if (posix_memalign((void**)&m_memory, 4096, size_t(m_dmaCount) * m_dmaSize)) {
        logging::critical("MemPoolSim: failed to allocate %u x %u B of DMA buffers", m_dmaCount, m_dmaSize);
        abort();
    }
    dmaBuffers = new void*[m_dmaCount];
    m_free.reserve(m_dmaCount);
    for (unsigned i = 0; i < m_dmaCount; ++i) {
        uint8_t* buf = m_memory + size_t(i) * m_dmaSize;
        dmaBuffers[i] = buf;
        *(uint32_t*)(buf + m_dmaSize - sizeof(uint32_t)) = Sentinel;
        m_free.push_back(m_dmaCount - 1 - i);   // Hand out low indices first
    }
    logging::info("Simulated PGP device '%s': timing frames from %s",
                  para.device.c_str(), m_endpoint.c_str());

    _initialize(para);

    m_thread = std::thread(&MemPoolSim::_receiver, this);
}

MemPoolSim::~MemPoolSim()
{
    m_terminate.store(true, std::memory_order_release);
    if (m_thread.joinable())  m_thread.join();
    if (m_nOverruns)  logging::warning("MemPoolSim: %lu frames found no free DMA buffer", m_nOverruns);
    delete [] dmaBuffers;
    free(m_memory);
    close(m_efd);
}

int MemPoolSim::setMaskBytes(uint8_t laneMask, unsigned virtChan)
{
    m_laneMask = laneMask;
    m_nLanes   = __builtin_popcount(laneMask);
    m_virtChan = virtChan;
    return 0;
}

unsigned MemPoolSim::paddr()
{
    std::unique_lock<std::mutex> lock(m_regLock);
    if (!m_regCv.wait_for(lock, std::chrono::seconds(10), [this]{ return m_registered; })) {
        logging::error("MemPoolSim: no WELCOME from simxpm at %s after 10 s; is simxpm running?",
                       m_endpoint.c_str());
        return 0xffffffff;
    }
    return m_paddr;
}

void MemPoolSim::connect(unsigned readoutGroup, unsigned length)
{
    unsigned maxLength = (m_dmaSize - sizeof(Pds::TimingHeader) - sizeof(uint32_t)) / sizeof(uint32_t);
    if (length > maxLength) {
        logging::error("MemPoolSim: sim_length %u does not fit sim_dma_size %u; using %u",
                       length, m_dmaSize, maxLength);
        length = maxLength;
    }
    m_group .store(readoutGroup, std::memory_order_release);
    m_length.store(length,       std::memory_order_release);
    m_connected.store(true,      std::memory_order_release);
    m_changed  .store(true,      std::memory_order_release);
    logging::info("MemPoolSim: readout group %u, %u payload words per lane", readoutGroup, length);
}

void MemPoolSim::disconnect()
{
    m_connected.store(false, std::memory_order_release);
    m_changed  .store(true,  std::memory_order_release);
}

ssize_t MemPoolSim::_readDma(uint32_t count, int32_t* ret, uint32_t* index,
                             uint32_t* flags, uint32_t* errors, uint32_t* dest)
{
    std::lock_guard<std::mutex> lock(m_simLock);
    uint32_t n = 0;
    while (n < count && !m_ready.empty()) {
        const Ready& r = m_ready.front();
        ret[n]   = r.size;
        index[n] = r.index;
        if (flags)   flags[n]  = 0;
        if (errors)  errors[n] = 0;
        if (dest)    dest[n]   = r.dest;
        m_ready.pop_front();
        ++n;
    }
    if (m_ready.empty()) {
        uint64_t value;
        [[maybe_unused]] auto rc = read(m_efd, &value, sizeof(value));    // Not readable until more arrive
    }
    return n;
}

void MemPoolSim::_return(unsigned count, const uint32_t* indices)
{
    std::lock_guard<std::mutex> lock(m_simLock);
    for (unsigned i = 0; i < count; ++i) {
        if (indices[i] < m_dmaCount)  m_free.push_back(indices[i]);
    }
}

ssize_t MemPoolSim::_freeDma(unsigned count, uint32_t* indices)
{
    for (unsigned i = 0; i < count; ++i) {
        auto buffer = (const uint8_t*)dmaBuffers[indices[i]];
        auto word   = (const uint32_t*)(buffer + m_dmaSize - sizeof(uint32_t));
        if (*word != Sentinel) [[unlikely]] {
            logging::error("MemPoolSim: DMA buffer[%u] overrun: %08x vs %08x", indices[i], *word, Sentinel);
        }
    }
    _return(count, indices);
    return 0;
}

ssize_t MemPoolSim::_retDma(unsigned count, uint32_t* indices)
{
    _return(count, indices);
    return 0;
}

int MemPoolSim::_send(void* socket, const std::string& type, const void* data, size_t size)
{
    if (zmq_send(socket, type.data(), type.size(), ZMQ_SNDMORE) < 0)  return -1;
    return zmq_send(socket, data, size, 0);
}

// Turn each frame into DMA buffers, as the timing receiver and TDetSemi firmware would
void MemPoolSim::_frames(const uint8_t* data, size_t size)
{
    bool     connected = m_connected.load(std::memory_order_acquire);
    unsigned length    = m_length.load(std::memory_order_acquire);
    uint32_t seed      = m_seed.load(std::memory_order_acquire);
    size_t   nReady    = 0;

    std::lock_guard<std::mutex> lock(m_simLock);
    for (size_t offset = 0; offset + sizeof(Frame) <= size; offset += sizeof(Frame)) {
        Frame f;
        memcpy(&f, data + offset, sizeof(f));
        if (m_credit)  --m_credit;
        if (!connected)  continue;      // Like a disabled TriggerEventBuffer

        auto tid = TransitionId::Value((f.pulseIdAndControl >> 56) & 0xf);
        if (tid == TransitionId::ClearReadout) {
            m_evtCounter = 0;           // The next event is number 1, as PgpReader expects
            continue;
        }
        m_evtCounter = (m_evtCounter + 1) & EvtCtrMask;

        if (m_free.size() < m_nLanes) [[unlikely]] {
            if (m_nOverruns++ < 5)
                logging::error("MemPoolSim: no free DMA buffer for %s (credit protocol violated)",
                               TransitionId::name(tid));
            continue;
        }
        unsigned len = tid == TransitionId::L1Accept ? length : 0;
        for (unsigned lane = 0; lane < PGP_MAX_LANES; ++lane) {
            if (!(m_laneMask & (1 << lane)))  continue;
            uint32_t idx = m_free.back();
            m_free.pop_back();
            auto sz = fill((uint8_t*)dmaBuffers[idx], f, m_evtCounter, lane, len, seed);
            m_ready.push_back({int32_t(sz), idx, (lane << 8) | m_virtChan});
            ++nReady;
        }
    }
    if (nReady) {
        uint64_t one = 1;
        [[maybe_unused]] auto rc = write(m_efd, &one, sizeof(one));
    }
}

void MemPoolSim::_receiver()
{
    if (prctl(PR_SET_NAME, "drp/SimDma", 0, 0, 0) == -1)  perror("prctl");

    void* context = zmq_ctx_new();
    void* socket  = zmq_socket(context, ZMQ_DEALER);
    int   linger  = 0;
    zmq_setsockopt(socket, ZMQ_LINGER, &linger, sizeof(linger));
    if (zmq_connect(socket, m_endpoint.c_str()) < 0) {
        logging::critical("MemPoolSim: zmq_connect(%s): %s", m_endpoint.c_str(), zmq_strerror(zmq_errno()));
        abort();
    }

    char host[256] = {};
    gethostname(host, sizeof(host) - 1);
    json hello = {{"alias", m_alias}, {"host", host}, {"pid", getpid()},
                  {"lanes", m_nLanes}, {"dmaCount", m_dmaCount}};
    std::string helloStr = hello.dump();
    _send(socket, "HELLO", helloStr.data(), helloStr.size());

    bool             registered = false;
    zmq_pollitem_t   item{socket, 0, ZMQ_POLLIN, 0};
    zmq_msg_t        type, body;
    zmq_msg_init(&type);
    zmq_msg_init(&body);
    while (!m_terminate.load(std::memory_order_acquire)) {
        zmq_poll(&item, 1, 10);         // ms

        // Drain everything that arrived: [type, body] messages
        while (zmq_msg_recv(&type, socket, ZMQ_DONTWAIT) >= 0) {
            std::string kind((const char*)zmq_msg_data(&type), zmq_msg_size(&type));
            if (!zmq_msg_more(&type) || zmq_msg_recv(&body, socket, 0) < 0) {
                logging::error("MemPoolSim: malformed '%s' message from simxpm", kind.c_str());
                continue;
            }
            if (kind == "FRAMES") {
                _frames((const uint8_t*)zmq_msg_data(&body), zmq_msg_size(&body));
            } else if (kind == "WELCOME") {
                json w = json::parse(std::string((const char*)zmq_msg_data(&body), zmq_msg_size(&body)),
                                     nullptr, false);
                if (!w.is_object()) {
                    logging::error("MemPoolSim: malformed WELCOME from simxpm");
                    continue;
                }
                unsigned xpm  = w.value("xpm",  0u);
                unsigned link = w.value("link", 0u);
                logging::info("MemPoolSim: simxpm registered %s as XPM %u link %u",
                              m_alias.c_str(), xpm, link);
                {
                    std::lock_guard<std::mutex> lock(m_regLock);
                    m_paddr      = (xpm << 16) | link;
                    m_registered = true;
                }
                m_regCv.notify_all();
                registered = true;
                m_credit   = 0;         // simxpm starts a (re)registered link with none
                m_changed.store(true, std::memory_order_release);   // Restate group membership
            } else {
                logging::warning("MemPoolSim: ignoring '%s' message from simxpm", kind.c_str());
            }
        }
        if (!registered)  continue;

        if (m_changed.exchange(false, std::memory_order_acq_rel)) {
            if (m_connected.load(std::memory_order_acquire)) {
                std::string msg = json({{"group", m_group.load()}}).dump();
                _send(socket, "CONNECT", msg.data(), msg.size());
            } else {
                _send(socket, "DISCONNECT", "", 0);
            }
        }

        // Grant one credit per frame's worth of free buffers not already promised
        unsigned nFree;
        {
            std::lock_guard<std::mutex> lock(m_simLock);
            nFree = m_free.size();
        }
        unsigned avail = nFree / m_nLanes;
        if (avail > m_credit) {
            uint32_t grant = avail - m_credit;
            if (_send(socket, "CREDIT", &grant, sizeof(grant)) >= 0)  m_credit += grant;
        }
    }
    _send(socket, "BYE", "", 0);
    zmq_msg_close(&type);
    zmq_msg_close(&body);
    zmq_close(socket);
    zmq_ctx_term(context);
}

}
