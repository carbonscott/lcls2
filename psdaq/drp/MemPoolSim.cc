#include "MemPoolSim.hh"
#include "EventBatcher.hh"

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
#include <algorithm>
#include <chrono>
#include <vector>

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

uint32_t MemPoolSim::mix(uint32_t index)
{
    uint32_t h = index * 0x9e3779b1u;
    h ^= h >> 16;
    h *= 0x85ebca6bu;
    h ^= h >> 13;
    return h;
}

uint32_t MemPoolSim::pattern(uint32_t seed, uint32_t seq, uint32_t index, unsigned bits)
{
    uint32_t v = mix(index) + seq * 0x9e37u + seed;
    return bits >= 32 ? v : v & ((1u << bits) - 1);
}

void MemPoolSim::Out::tail(uint32_t size, uint8_t tdest)
{
    const unsigned width = 2;                           // 8-byte lines
    const unsigned lw    = EvtBatcherHeader::lineWidth(width);
    pos += (size + lw - 1) & ~(lw - 1);
    uint8_t* t = buffer + pos;
    memcpy(t, &size, sizeof(size));
    t[4] = tdest;  t[5] = 0x2;  t[6] = 0;  t[7] = width;    // tuser_first: SOF
    pos += lw;
}

void MemPoolSim::Out::timingCopy(uint8_t tdest)
{
    // The TimingHeader is the first subframe, right after the header line
    memcpy(data(), buffer + EvtBatcherHeader::lineWidth(2), sizeof(Pds::TimingHeader));
    tail(sizeof(Pds::TimingHeader), tdest);
}

static constexpr unsigned _padded(unsigned size) { return ((size + 7) & ~7u) + 8; }   // + tail

static void _dataHeader(uint8_t* data, const MemPoolSim::Frame& f, uint32_t seed)
{
    uint64_t  pid = f.pulseIdAndControl & ((1ull << 56) - 1);
    uint32_t* w   = reinterpret_cast<uint32_t*>(data);
    w[0] = uint32_t(pid);  w[1] = uint32_t(pid >> 32);  w[2] = f.seq;  w[3] = seed;
}

// Pixels whose order is fixed per type: 'map' lists, for each 16-bit word of the readout in
// order, the flat index of the image pixel it carries.  The per-event value is mix(index)
// (precomputed) + seq * 0x9e37 + seed, masked, so an event costs one add per pixel.
struct PixelMap
{
    std::vector<uint16_t> base;                         // mix(index) & mask, in readout order
    uint16_t              mask;
    template <typename F> PixelMap(size_t n, unsigned bits, F index) :
        base(n), mask(uint16_t((1u << bits) - 1))
    {
        for (size_t j = 0; j < n; ++j)  base[j] = uint16_t(MemPoolSim::mix(index(j)) & mask);
    }
    void fill(uint16_t* out, uint32_t seed, uint32_t seq) const
    {
        uint16_t add = uint16_t(seq * 0x9e37u + seed);
        for (size_t j = 0; j < base.size(); ++j)  out[j] = uint16_t(base[j] + add) & mask;
    }
};

// epix100 (Epix100::_event): subframe 3 = 32 B header, 704 pixel rows + 2 environmental + 2
// calibration rows of 768 uint16, 12 B trailer.  The two ASIC halves arrive interleaved:
// readout row 2i is image row 352+i and row 2i+1 is image row 351-i (Epix100.cc unscrambles
// them as LCLS1's Epix100aServer did).  The extra rows carry image indices past the end.
static const unsigned Epix100Rows = 704, Epix100Cols = 768, Epix100Extra = 4;
static const unsigned Epix100Bytes = 32 + (Epix100Rows + Epix100Extra) * Epix100Cols * 2 + 12;

static void epix100Data(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const PixelMap pixels((Epix100Rows + Epix100Extra) * Epix100Cols, 14, [](size_t j) {
        unsigned r = j / Epix100Cols, c = j % Epix100Cols;
        if (r >= Epix100Rows)  return uint32_t(j);
        unsigned img = (r & 1) ? Epix100Rows / 2 - 1 - r / 2 : Epix100Rows / 2 + r / 2;
        return uint32_t(img * Epix100Cols + c);
    });
    out.timingCopy(2);                  // the detailed timing frame; a copy stands in for it
    uint8_t* data = out.data();
    memset(data, 0, 32);
    _dataHeader(data, f, seed);
    pixels.fill(reinterpret_cast<uint16_t*>(data + 32), seed, f.seq);
    memset(data + Epix100Bytes - 12, 0, 12);
    out.tail(Epix100Bytes, 3);
}

// wave8 (Wave8::_event reads subframes 2..11): 8 raw waveforms (tdest 2..9) of Wave8Samples
// uint16 samples, then the integrals stream (tdest 10, W8::IntegralStream, 56 B) and the
// processed stream (tdest 11, W8::ProcStream, 32 B).  Sample k of channel ch is index
// ch * Wave8Samples + k; the integrals and baselines continue the indices after them.
static const unsigned Wave8Samples = 256;

static void wave8Data(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const PixelMap samples(8 * Wave8Samples, 16, [](size_t j) { return uint32_t(j); });
    out.timingCopy(1);                  // auxiliary timing header
    std::vector<uint16_t> raw(8 * Wave8Samples);
    samples.fill(raw.data(), seed, f.seq);
    for (unsigned ch = 0; ch < 8; ++ch) {
        memcpy(out.data(), raw.data() + ch * Wave8Samples, Wave8Samples * sizeof(uint16_t));
        out.tail(Wave8Samples * sizeof(uint16_t), 2 + ch);
    }
    const uint32_t n = 8 * Wave8Samples;
    uint8_t* d = out.data();                                    // W8::IntegralStream
    memset(d, 0, 56);
    uint16_t itrig = uint16_t(f.seq);
    memcpy(d + 4, &itrig, 2);
    for (unsigned i = 0; i < 8; ++i) {
        uint32_t integral = MemPoolSim::pattern(seed, f.seq, n + i, 24);     // 24-bit signed
        uint16_t base     = uint16_t(MemPoolSim::pattern(seed, f.seq, n + 8 + i, 16));
        memcpy(d + 8 + 4 * i, &integral, 4);
        memcpy(d + 40 + 2 * i, &base, 2);
    }
    out.tail(56, 10);
    d = out.data();                                             // W8::ProcStream
    uint32_t proc[2] = { 0, f.seq };
    double   v[3] = { double(MemPoolSim::pattern(seed, f.seq, n + 16, 20)),
                      double(MemPoolSim::pattern(seed, f.seq, n + 17, 20)) / 1024.,
                      double(MemPoolSim::pattern(seed, f.seq, n + 18, 20)) / 1024. };
    memcpy(d, proc, sizeof(proc));
    memcpy(d + 8, v, sizeof(v));
    out.tail(32, 11);
}

// wave8he (Wave8HE::_event reads subframes 2..9 as raw waveforms, 0x0C as W8HE::PeakStream,
// 0x0D as W8HE::IntegralStream): 8 waveforms of Wave8Samples uint16 (the firmware's 255
// samples padded to 512 B), then the 64 B peak stream {8 x [peakPos:8|peakVal:24], 8 packed
// 24-bit baselines, float posX, posY} and the 32 B integral stream {8 packed 24-bit
// integrals, float posX, posY}.  Indices continue after the samples as for wave8.
static void _put24(uint8_t* p, uint32_t v) { p[0] = v & 0xff;  p[1] = (v >> 8) & 0xff;  p[2] = (v >> 16) & 0xff; }

static void wave8heData(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const PixelMap samples(8 * Wave8Samples, 16, [](size_t j) { return uint32_t(j); });
    out.timingCopy(1);                  // auxiliary timing header
    std::vector<uint16_t> raw(8 * Wave8Samples);
    samples.fill(raw.data(), seed, f.seq);
    for (unsigned ch = 0; ch < 8; ++ch) {
        memcpy(out.data(), raw.data() + ch * Wave8Samples, Wave8Samples * sizeof(uint16_t));
        out.tail(Wave8Samples * sizeof(uint16_t), 2 + ch);
    }
    const uint32_t n = 8 * Wave8Samples;
    auto p = [&](unsigned i, unsigned bits) { return MemPoolSim::pattern(seed, f.seq, n + i, bits); };
    uint8_t* d = out.data();                                    // W8HE::PeakStream
    memset(d, 0, 64);
    for (unsigned i = 0; i < 8; ++i) {
        uint32_t word = (p(i, 8) << 24) | p(8 + i, 24);
        memcpy(d + 4 * i, &word, 4);
        _put24(d + 32 + 3 * i, p(16 + i, 24));
    }
    float pos[2] = { float(p(24, 20)) / 1024.f, float(p(25, 20)) / 1024.f };
    memcpy(d + 56, pos, sizeof(pos));
    out.tail(64, 0x0c);
    d = out.data();                                             // W8HE::IntegralStream
    memset(d, 0, 32);
    for (unsigned i = 0; i < 8; ++i)
        _put24(d + 3 * i, p(32 + i, 24));
    float ipos[2] = { float(p(40, 20)) / 1024.f, float(p(41, 20)) / 1024.f };
    memcpy(d + 24, ipos, sizeof(ipos));
    out.tail(32, 0x0d);
}

// hrencoder (HREncoder::_event reads subframe 2 as Enc::Stream): {int32 position, uint8
// encErrCnt, missedTrigCnt, latches, reserved}.  position is pattern(seed, seq, 0, 32) as a
// signed value, the three counts pattern(seed, seq, 1..3, 8); the reserved byte is 0.
static void hrencoderData(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    uint8_t* d = out.data();
    uint32_t position = MemPoolSim::pattern(seed, f.seq, 0, 32);
    memcpy(d, &position, 4);
    for (unsigned i = 0; i < 3; ++i)
        d[4 + i] = uint8_t(MemPoolSim::pattern(seed, f.seq, 1 + i, 8));
    d[7] = 0;
    out.tail(8, 2);
}

// One row per BEB detector type that can run with -d sim://
static const MemPoolSim::Batcher Batchers[] = {
    { "epix100", _padded(32) + _padded(Epix100Bytes), epix100Data },
    { "wave8",   _padded(32) + 8 * _padded(2 * Wave8Samples) + _padded(56) + _padded(32), wave8Data },
    { "wave8he", _padded(32) + 8 * _padded(2 * Wave8Samples) + _padded(64) + _padded(32), wave8heData },
    { "hrencoder", _padded(8), hrencoderData },
};

const MemPoolSim::Batcher* MemPoolSim::batcher(const std::string& detType)
{
    for (const auto& b : Batchers)
        if (detType == b.detType)  return &b;
    return nullptr;
}

// ts (TimingSystem::event, TimingDef.hh): the 153-byte packed TimingData that the timing
// system's TDet firmware sends after the TimingHeader.  pulseId and timeStamp are the frame's.
// Every other element, numbered 2, 3, ... in TimingData order (an array element by element),
// is pattern(seed, seq, element, bits), 'bits' being what the field holds: 1 for the
// fixedRates, acRates, ebeamPresent and mpsLimits flags, 3 for timeSlot, 4 for ebeamDestn and
// each mpsPowerClass, else the field's size (psdaq/psdaq/sim/xtc2_check.py TIMING_FIELDS).
static const struct { unsigned n, bytes, bits; } TimingFields[] = {
    {10, 1,  1},    // fixedRates
    { 6, 1,  1},    // acRates
    { 1, 1,  3},    // timeSlot
    { 1, 2, 16},    // timeSlotPhase
    { 1, 1,  1},    // ebeamPresent
    { 1, 1,  4},    // ebeamDestn
    { 1, 2, 16},    // ebeamCharge
    { 4, 2, 16},    // ebeamEnergy
    { 2, 2, 16},    // xWavelength
    { 1, 2, 16},    // dmod5
    {16, 1,  1},    // mpsLimits
    {16, 1,  4},    // mpsPowerClass
    {18, 2, 16},    // sequenceValues (the event codes)
    { 8, 4, 32},    // inhibitCounts
};
static const unsigned TimingDataBytes = 153;    // TimingDef::data_size

static void timingMessage(uint8_t* out, const MemPoolSim::Frame& f, uint32_t seed)
{
    uint64_t pid  = f.pulseIdAndControl & ((1ull << 56) - 1);
    uint64_t time = (uint64_t(f.seconds) << 32) | f.nanoseconds;
    memcpy(out, &pid, 8);
    memcpy(out + 8, &time, 8);
    uint8_t* p = out + 16;
    uint32_t element = 2;
    for (const auto& field : TimingFields) {
        for (unsigned i = 0; i < field.n; ++i, ++element, p += field.bytes) {
            uint32_t v = MemPoolSim::pattern(seed, f.seq, element, field.bits);
            memcpy(p, &v, field.bytes);                 // little-endian, as the firmware
        }
    }
}

static const MemPoolSim::TDetMsg TDetMsgs[] = {
    { "ts", TimingDataBytes, timingMessage },
};

const MemPoolSim::TDetMsg* MemPoolSim::tdetMsg(const std::string& detType)
{
    for (const auto& t : TDetMsgs)
        if (detType == t.detType)  return &t;
    return nullptr;
}

// Lay out a buffer as the AxiStreamBatcherEventBuilder does (EventBatcher.hh): a header line,
// then each subframe's data padded to the line width followed by a one-line tail
// {size, tdest, tuser_first, tuser_last, width}.  BEBDetector walks the tails backwards from
// the end, so the subframe with the highest tdest comes last.
size_t MemPoolSim::fillBatcher(uint8_t* buffer, const Batcher& b, const Frame& f,
                               uint32_t evtCounter, bool l1, uint32_t seed)
{
    const unsigned width = 2;                           // 8-byte lines
    const unsigned lw    = EvtBatcherHeader::lineWidth(width);
    static_assert(sizeof(EvtBatcherSubFrameTail) == 8, "batcher tail fits one 8-byte line");

    memset(buffer, 0, lw);
    auto ebh = reinterpret_cast<EvtBatcherHeader*>(buffer);
    ebh->version        = 1;
    ebh->width          = width;
    ebh->sequence_count = evtCounter & 0xff;
    Out out{buffer, lw};

    // Subframe 0: the TimingHeader (getTimingHeader() returns its address)
    size_t th = fill(out.data(), f, evtCounter, 0, 0, 0);
    out.tail(th, 0);
    if (!l1)  return out.pos;

    b.data(out, f, seed);
    return out.pos;
}

MemPoolSim::MemPoolSim(const Parameters& para) :
    MemPool     (para),
    m_alias     (para.alias),
    m_batcher   (batcher(para.detType)),
    m_tdetMsg   (tdetMsg(para.detType)),
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
    if (m_batcher) {
        size_t need = 8 + (sizeof(Pds::TimingHeader) + 8) + m_batcher->dataBytes;
        if (m_dmaSize < need + sizeof(uint32_t)) {
            logging::critical("MemPoolSim: %s needs sim_dma_size >= %zu (have %u)",
                              para.detType.c_str(), need + sizeof(uint32_t), m_dmaSize);
            abort();
        }
        logging::info("MemPoolSim: %s data framed as EventBatcher subframes (up to %u B of data)",
                      para.detType.c_str(), m_batcher->dataBytes);
    }
    if (m_tdetMsg) {
        if (m_dmaSize < sizeof(Pds::TimingHeader) + m_tdetMsg->bytes + sizeof(uint32_t)) {
            logging::critical("MemPoolSim: %s needs sim_dma_size >= %zu (have %u)", para.detType.c_str(),
                              sizeof(Pds::TimingHeader) + m_tdetMsg->bytes + sizeof(uint32_t), m_dmaSize);
            abort();
        }
        logging::info("MemPoolSim: %s data is its TDet firmware's %u B message",
                      para.detType.c_str(), m_tdetMsg->bytes);
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
            auto sz = m_batcher
                    ? fillBatcher((uint8_t*)dmaBuffers[idx], *m_batcher, f, m_evtCounter,
                                  tid == TransitionId::L1Accept, seed)
                    : fill((uint8_t*)dmaBuffers[idx], f, m_evtCounter, lane, m_tdetMsg ? 0 : len, seed);
            if (m_tdetMsg && tid == TransitionId::L1Accept) {
                m_tdetMsg->data((uint8_t*)dmaBuffers[idx] + sz, f, seed);
                sz += m_tdetMsg->bytes;
            }
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
