#include "MemPoolSim.hh"
#include "EventBatcher.hh"
#include "JungfrauData.hh"

#include "psdaq/service/EbDgram.hh"
#include "xtcdata/xtc/TransitionId.hh"
#include "psalg/utils/SysLog.hh"

#include <nlohmann/json.hpp>
#include <zmq.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/eventfd.h>
#include <sys/prctl.h>
#include <sys/socket.h>
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

// epixm320 (EpixM320::_event): subframes 2..5 are ASICs 0..3, each a 48 B header {rsvd u32,
// frameNo u32, asicNo u8, ...}, 192 x 384 uint16 in the ASIC's bank order, and a 48 B trailer.
// EpixM320::_descramble reorders the 24 banks (and shifts each bank's rows up by one for an
// ASIC firmware bug); the framer puts image pixel (q, r, c) where that loop reads it.  15 data
// bits (psana's epixm320 raw masks with 0x7fff; bit 15 is the gain bit, 0 here).
static const unsigned EpixMRows = 192, EpixMCols = 384, EpixMBankRows = 4, EpixMBankCols = 6;
static const unsigned EpixMBanks = 24, EpixMHdr = 48, EpixMAsic = EpixMRows * EpixMCols;

static std::vector<uint32_t> epixm320Order()    // readout word -> image pixel within an ASIC
{
    std::vector<uint32_t> inv(EpixMAsic);
    const unsigned bankHeight = EpixMRows / EpixMBankRows, bankWidth = EpixMCols / EpixMBankCols;
    const unsigned hw = bankWidth / 2, hb = bankHeight * hw;
    uint32_t d = 0;                                 // EpixM320::_descramble's dst, row-major
    for (unsigned bankRow = 0; bankRow < EpixMBankRows; ++bankRow)
        for (unsigned row = 0; row < bankHeight; ++row) {
            unsigned rowFix = row == 0 ? bankHeight - 1 : row - 1;
            for (unsigned bankCol = 0; bankCol < EpixMBankCols; ++bankCol) {
                unsigned bank = EpixMBankRows * bankCol + bankRow;
                for (unsigned col = 0; col < bankWidth; ++col)
                    inv[(((col + 1) % 2) * hb + hw * rowFix + col / 2) * EpixMBanks + bank] = d++;
            }
        }
    return inv;
}

static void epixm320Data(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const std::vector<uint32_t> order = epixm320Order();
    static const std::vector<PixelMap> asics = [] {
        std::vector<PixelMap> v;
        for (uint32_t q = 0; q < 4; ++q)
            v.emplace_back(EpixMAsic, 15, [q](size_t j) { return q * EpixMAsic + order[j]; });
        return v;
    }();
    out.timingCopy(1);                  // the detailed timing frame; a copy stands in for it
    for (unsigned q = 0; q < 4; ++q) {
        uint8_t* d = out.data();
        memset(d, 0, EpixMHdr);
        memcpy(d + 4, &f.seq, 4);       // frameNo
        d[8] = uint8_t(q);              // asicNo
        asics[q].fill(reinterpret_cast<uint16_t*>(d + EpixMHdr), seed, f.seq);
        memset(d + EpixMHdr + 2 * EpixMAsic, 0, EpixMHdr);
        out.tail(2 * EpixMHdr + 2 * EpixMAsic, 2 + q);
    }
}

// opal (Opal::_event, write_image): subframe 2 is the camera's image as the camera link FEB
// sends it, rows x columns uint16 in row order (tdest 1 is the timing frame).  The model the
// camera answers '@ID?' with (psdaq/psdaq/sim/seeds/opal.json: an Opal-1000) sets the shape
// Opal::_connectionInfo allocates, 1024 x 1024; 12 data bits (opal_config's '@OR12').
static const unsigned OpalRows = 1024, OpalCols = 1024, OpalBits = 12;

static void opalData(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const PixelMap pixels(OpalRows * OpalCols, OpalBits, [](size_t j) { return uint32_t(j); });
    out.timingCopy(1);                  // the detailed timing frame; a copy stands in for it
    pixels.fill(reinterpret_cast<uint16_t*>(out.data()), seed, f.seq);
    out.tail(2 * OpalRows * OpalCols, 2);
}

// piranha4 (Piranha4::_event, write_image): subframe 2 is the line camera's one row of pixels,
// uint16; the model in the camera's 'gcp' summary (seeds/piranha4.json: P4_CM_02K..) sets the
// 2048 pixels Piranha4::_connectionInfo allocates; 12 data bits (piranha4_config's 'spf 2').
static const unsigned Piranha4Pixels = 2048, Piranha4Bits = 12;

static void piranha4Data(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const PixelMap pixels(Piranha4Pixels, Piranha4Bits, [](size_t j) { return uint32_t(j); });
    out.timingCopy(1);                  // the detailed timing frame; a copy stands in for it
    pixels.fill(reinterpret_cast<uint16_t*>(out.data()), seed, f.seq);
    out.tail(2 * Piranha4Pixels, 2);
}

// tt (TimeTool::_event): subframe 2 is the camera's line of the timetool's region of interest,
// one uint8 per pixel (tt_config_store's ClinkCh.DataMode 1, 8 bit), which the DRP records as
// 'image' only if its length is the config's UartPiranha4.ROI1 - ROI0 + 1, 2048 (ROI 1..2048 in
// tt_config_store) here; pixel i is pattern(seed, seq, i, 8).  The FEX results that the timetool
// firmware sends in tdest 1 are left out: TimeTool::_event does not read them.
static const unsigned TtPixels = 2048;

static void ttData(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const std::vector<uint8_t> base = [] {
        std::vector<uint8_t> v(TtPixels);
        for (unsigned i = 0; i < TtPixels; ++i)  v[i] = uint8_t(MemPoolSim::mix(i));
        return v;
    }();
    uint8_t  add = uint8_t(f.seq * 0x9e37u + seed);
    uint8_t* d   = out.data();
    for (unsigned i = 0; i < TtPixels; ++i)  d[i] = uint8_t(base[i] + add);
    out.tail(TtPixels, 2);
}

// tb (TimingBEB::_event, TimingDef::createDataETM): the timing system's event timing message
// in the last subframe (tdest 2, the lane's data channel), read with the TimingHeader of
// subframe 0: {u64 pulseId (not recorded), u16 rate markers (fixed 0-9, AC 10-15), u8 AC
// time slot, u8 beam (present bit 0, destination bits 4-7), 18 x u16 sequence values}.  The
// fields are pattern(seed, seq, element, bits), elements 2, 3, 4, 5.. in that order; the DRP
// records the other TimingData fields as 0.
static const unsigned TbEtmBytes = 48;

static void tbData(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    uint8_t* d   = out.data();
    uint64_t pid = f.pulseIdAndControl & ((1ull << 56) - 1);
    memcpy(d, &pid, 8);
    uint16_t rates = uint16_t(MemPoolSim::pattern(seed, f.seq, 2, 16));
    memcpy(d + 8, &rates, 2);
    d[10] = uint8_t(MemPoolSim::pattern(seed, f.seq, 3, 3));
    d[11] = uint8_t(MemPoolSim::pattern(seed, f.seq, 4, 8));
    for (unsigned i = 0; i < 18; ++i) {
        uint16_t v = uint16_t(MemPoolSim::pattern(seed, f.seq, 5 + i, 16));
        memcpy(d + 12 + 2 * i, &v, 2);
    }
    out.tail(TbEtmBytes, 2);
}

// epixquad (EpixQuad::_event): 4 subframes; tdest 2 is the camera's frame, a 32 B header and
// then, for each of 176 super rows i, 8 rows of 384 pixels of elements (2, 3, 2, 3, 0, 1, 0, 1)
// at rows (175-i, 175-i, 176+i, 176+i, ...) with each row's columns reversed, then 4
// calibration rows of elements 2, 3, 0, 1.  The framer puts raw pixel (element q, row r,
// column c) where that loop reads it; 14 data bits (gain bits 0).  Tdest 1 (unused by the DRP)
// and 3 carry copies of the timing frame.
static const unsigned EquadRows = 352, EquadCols = 384, EquadAsicRows = 176, EquadCalib = 4;
static const unsigned EquadBytes = 32 + (8 * EquadAsicRows + 4 * EquadCalib) * EquadCols * 2;

static std::vector<uint32_t> epixquadOrder()    // readout word -> raw pixel index (or past it)
{
    std::vector<uint32_t> order;
    const unsigned image = 4 * EquadRows * EquadCols;
    auto row = [&](unsigned el, unsigned r, uint32_t base) {
        for (unsigned k = 0; k < EquadCols; ++k)  order.push_back(base + (el * EquadRows + r) * EquadCols + EquadCols - 1 - k);
    };
    for (unsigned i = 0; i < EquadAsicRows; ++i) {
        unsigned up = EquadAsicRows - i - 1, dn = EquadAsicRows + i;
        row(2, up, 0); row(3, up, 0); row(2, dn, 0); row(3, dn, 0);
        row(0, up, 0); row(1, up, 0); row(0, dn, 0); row(1, dn, 0);
    }
    for (unsigned i = 0; i < EquadCalib; ++i) {     // calibration rows: indices past the image
        auto cal = [&](unsigned el) {
            for (unsigned k = 0; k < EquadCols; ++k)  order.push_back(image + (el * EquadCalib + i) * EquadCols + EquadCols - 1 - k);
        };
        cal(2); cal(3); cal(0); cal(1);
    }
    return order;
}

static void epixquadData(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const std::vector<uint32_t> order = epixquadOrder();
    static const PixelMap pixels(order.size(), 14, [](size_t j) { return order[j]; });
    out.timingCopy(1);
    uint8_t* data = out.data();
    memset(data, 0, 32);
    _dataHeader(data, f, seed);
    pixels.fill(reinterpret_cast<uint16_t*>(data + 32), seed, f.seq);
    out.tail(EquadBytes, 2);
    out.timingCopy(3);
}

// epixUHR (EpixUHR::_event): 4 ASIC subframes (tdest 2-5, ASICs 0-3 of user.asic_enable 0xf), each
// 168 x 192 pixels of 12 bits packed into 48,384 B as the ASIC's 8 serial lanes send them; the DRP
// records them as they come and psana's epixuhr raw() (_descramble_raw_frame, with gain_msb)
// unpacks them.  The framer runs that unpacking backwards: pixel (y, x) of ASIC q, flat index
// q * 32256 + 192 y + x, is pattern(seed, seq, index, 12); its 12-bit word is that value rotated
// left by one (gain_msb moves the word's bit 0 to bit 11); the word goes to column c = x / 12 of
// the lane map (psana's _lane_map_uhr35kHzv2) at entry n = 12 (167 - y) + x % 12, slot
// s = map[n] of the column pair 2c, 2c+1: 12-bit word (s / 2) of lane (2c + s % 2) / 4, place
// (2c + s % 2) % 4; each lane packs 4 words (in reverse) into 6 bytes (in reverse), and byte j of
// lane L's group k is byte 8 (6 k + j) + L of the subframe.
static const unsigned UhrRows = 168, UhrCols = 192, UhrAsicBytes = UhrRows * UhrCols * 12 / 8;

static std::vector<uint32_t> epixUHRSlots()     // image pixel (y, x) of an ASIC -> 4 k + place, lane
{
    int cm[72];                                 // cluster map: 2 columns of 3, the second reversed
    for (int r = 0; r < 12; ++r)
        for (int j = 0; j < 3; ++j) {
            cm[r * 6 + j]     = r * 3 + j;
            cm[r * 6 + 3 + j] = 36 + r * 3 + (2 - j);
        }
    int column[1008];
    for (int cl = 0; cl < 14; ++cl)
        for (int i = 0; i < 72; ++i)  column[cl * 72 + i] = 14 * cm[i] + cl;
    int map[2016];
    for (int r = 0; r < 168; ++r)
        for (int j = 0; j < 12; ++j)
            map[r * 12 + j] = j < 6 ? 2 * column[r * 6 + j] : 2 * column[r * 6 + j - 6] + 1;
    std::vector<uint32_t> slot(UhrRows * UhrCols);
    for (unsigned c = 0; c < 16; ++c)
        for (unsigned n = 0; n < 2016; ++n) {
            unsigned y = 167 - n / 12, x = c * 12 + n % 12;
            unsigned s = map[n], k = s / 2, col = 2 * c + s % 2;
            slot[y * UhrCols + x] = ((4 * k + col % 4) << 3) | (col / 4);
        }
    return slot;
}

static void epixUHRData(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const std::vector<uint32_t> slot = epixUHRSlots();
    static const std::vector<PixelMap> asics = [] {
        std::vector<PixelMap> v;
        for (uint32_t q = 0; q < 4; ++q)
            v.emplace_back(UhrRows * UhrCols, 12, [q](size_t j) { return uint32_t(q * UhrRows * UhrCols + j); });
        return v;
    }();
    std::vector<uint16_t> pix(UhrRows * UhrCols), words(4 * 1008 * 8);
    out.timingCopy(1);                  // the detailed timing frame; a copy stands in for it
    for (unsigned q = 0; q < 4; ++q) {
        asics[q].fill(pix.data(), seed, f.seq);
        for (unsigned i = 0; i < pix.size(); ++i) {
            uint16_t v = uint16_t(((pix[i] << 1) & 0xfff) | (pix[i] >> 11));    // gain_msb, inverted
            words[(slot[i] >> 3) * 8 + (slot[i] & 7)] = v;                  // [4 k + place][lane]
        }
        uint8_t* d = out.data();
        for (unsigned k = 0; k < 1008; ++k)
            for (unsigned L = 0; L < 8; ++L) {
                const uint16_t* w = &words[(4 * k) * 8 + L];
                uint16_t t0 = w[3 * 8], t1 = w[2 * 8], t2 = w[1 * 8], t3 = w[0];
                uint8_t x[6] = { uint8_t(t0 >> 4), uint8_t(((t0 & 0xf) << 4) | (t1 >> 8)), uint8_t(t1),
                                 uint8_t(t2 >> 4), uint8_t(((t2 & 0xf) << 4) | (t3 >> 8)), uint8_t(t3) };
                for (unsigned j = 0; j < 6; ++j)  d[8 * (6 * k + 5 - j) + L] = x[j];
            }
        out.tail(UhrAsicBytes, 2 + q);
    }
}

// epixhr2x2 (EpixHR2x2::_event, getTimingHeader): the card's event builder nests the camera
// board's.  Subframe 0 is an EventBatcher whose first subframe is the TimingHeader (fillBatcher,
// timingBatch: getTimingHeader steps into it); subframes 3 and 4, ASICs 0/1 and 2/3, are each an
// EventBatcher of {tdest 0: a copy of the TimingHeader, tdest 2: the ASIC pair's 146 rows of 384
// uint16}.  The DRP (m_descramble false) drops the first and the last row of each and records
// rows 1-144 of subframe 3's, then of subframe 4's, as raw (288, 384), as they come.  The framer
// puts raw pixel i = 384 r + c there (r < 144 from ASICs 0/1, the rest from 2/3), 16 bits, and
// indices past the image in the dropped rows; the first row starts with the data header.
static const unsigned Hr2Rows = 144, Hr2Cols = 384, Hr2StreamRows = Hr2Rows + 2;
static const unsigned Hr2StreamBytes = Hr2StreamRows * Hr2Cols * 2;
// subframe 3 or 4: its header line, the TimingHeader copy and the rows, each subframe with its tail
static const unsigned Hr2NestedBytes = 8 + _padded(32) + _padded(Hr2StreamBytes);

static void epixhr2x2Data(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const std::vector<PixelMap> pairs = [] {
        std::vector<PixelMap> v;
        for (uint32_t p = 0; p < 2; ++p)
            v.emplace_back(Hr2StreamRows * Hr2Cols, 16, [p](size_t j) {
                uint32_t r = j / Hr2Cols, c = j % Hr2Cols;
                if (r == 0 || r == Hr2StreamRows - 1)       // dropped: past the image
                    return uint32_t(2 * Hr2Rows * Hr2Cols + (2 * p + (r ? 1 : 0)) * Hr2Cols + c);
                return uint32_t((p * Hr2Rows + r - 1) * Hr2Cols + c);
            });
        return v;
    }();
    // The TimingHeader in subframe 0's EventBatcher: after the header line and its own
    const uint8_t* th = out.buffer + 2 * EvtBatcherHeader::lineWidth(2);
    for (unsigned p = 0; p < 2; ++p) {
        uint8_t* nb = out.data();
        memset(nb, 0, EvtBatcherHeader::lineWidth(2));
        auto ebh = reinterpret_cast<EvtBatcherHeader*>(nb);
        ebh->version        = 1;
        ebh->width          = 2;
        ebh->sequence_count = out.buffer[1];
        MemPoolSim::Out in{nb, EvtBatcherHeader::lineWidth(2)};
        memcpy(in.data(), th, sizeof(Pds::TimingHeader));
        in.tail(sizeof(Pds::TimingHeader), 0);
        pairs[p].fill(reinterpret_cast<uint16_t*>(in.data()), seed, f.seq);
        _dataHeader(in.data(), f, seed);
        in.tail(Hr2StreamBytes, 2);
        out.tail(in.pos, 3 + p);
    }
}

// jungfrau (Jungfrau::_event): a module sends each frame as JungfrauData::PacketNum UDP packets
// to the card's UDP engine, at the destination Drp::Jungfrau programs through sls::Detector (the
// config's user.kcu_ip and user.port), and the card's timing receiver triggers the module for
// each L1Accept.  Here the module is psdaq/psdaq/sim/simsls.py, a stand-in for its slsDetector
// servers, and this is the card's side:
//   - for each L1Accept, a datagram to the module's trigger input (UDP to its control
//     host:port, the drp's -k slsHosts, which must be a 127.x address),
//   - the frame's packets, received on 127.0.0.1:<sim_udp_port> (the config's user.port),
//   - written as the card's UdpFrameReorg and batcher do: subframe 2 is an EventBatcher of one
//     subframe per packet, in descending packet number (BEBDetector::_subframes reads the tails
//     back to front, so Jungfrau::_event sees packet 0 first), after subframe 1, a copy of the
//     timing frame standing in for the detailed one.
// A packet that has not arrived 200 ms after the last one (1 s for the first) is missing from
// the frame, which Jungfrau::_event flags as MissingData; a frame with no packet at all gets one
// empty subframe, so the event is recorded damaged instead of stalling the readout.  One module
// (one lane) only.
class UdpFront
{
public:
    static constexpr unsigned PacketBytes = sizeof(JungfrauData::JungfrauPacket);
    static constexpr unsigned Line        = 8;                          // EventBatcher width 2
    static constexpr unsigned DataBytes   = Line + JungfrauData::PacketNum * (PacketBytes + Line);
    static_assert(PacketBytes % Line == 0, "packets fill whole batcher lines");

    UdpFront(const Parameters& para);
    ~UdpFront();
    size_t frame(uint8_t* dst);         // trigger, receive, write the inner batcher; its size
private:
    int                   m_fd;
    sockaddr_in           m_module;
    std::string           m_moduleStr;
    std::vector<uint8_t>  m_packets;    // PacketNum x PacketBytes, by packet number
    std::vector<uint8_t>  m_have;
    std::vector<uint8_t>  m_rx;
    uint64_t              m_frames, m_incomplete, m_dropped;
};

static bool _loopback(const in_addr& a) { return (ntohl(a.s_addr) >> 24) == 127; }

UdpFront::UdpFront(const Parameters& para) :
    m_fd(-1), m_packets(JungfrauData::PacketNum * PacketBytes), m_have(JungfrauData::PacketNum),
    m_rx(PacketBytes + 1), m_frames(0), m_incomplete(0), m_dropped(0)
{
    if (__builtin_popcount(para.laneMask) != 1) {
        logging::critical("MemPoolSim: %s on sim:// runs one module (one lane), not lane mask 0x%x",
                          para.detType.c_str(), para.laneMask);
        abort();
    }
    auto hosts = para.kwargs.find("slsHosts");
    auto port  = para.kwargs.find("sim_udp_port");
    if (hosts == para.kwargs.end() || port == para.kwargs.end()) {
        logging::critical("MemPoolSim: %s on sim:// needs -k slsHosts=<127.x host>:<port> (the "
                          "module stand-in, psdaq.sim.simsls) and sim_udp_port=<the config's user.port>",
                          para.detType.c_str());
        abort();
    }
    m_moduleStr = hosts->second;
    auto colon = m_moduleStr.rfind(':');
    addrinfo hints{}, *res = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_DGRAM;
    if (colon == std::string::npos ||
        getaddrinfo(m_moduleStr.substr(0, colon).c_str(), m_moduleStr.substr(colon + 1).c_str(),
                    &hints, &res) != 0 || !res) {
        logging::critical("MemPoolSim: slsHosts '%s' is not <host>:<port>", m_moduleStr.c_str());
        abort();
    }
    memcpy(&m_module, res->ai_addr, sizeof(m_module));
    freeaddrinfo(res);
    if (!_loopback(m_module.sin_addr)) {
        logging::critical("MemPoolSim: the module stand-in '%s' must be on loopback (127.x)",
                          m_moduleStr.c_str());
        abort();
    }
    m_fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    int rcvbuf = 16 << 20;
    setsockopt(m_fd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf));
    sockaddr_in local{};
    local.sin_family = AF_INET;
    local.sin_port   = htons(std::stoul(port->second, nullptr, 0));
    inet_pton(AF_INET, "127.0.0.1", &local.sin_addr);
    if (m_fd < 0 || bind(m_fd, (sockaddr*)&local, sizeof(local)) < 0) {
        logging::critical("MemPoolSim: cannot bind the card's UDP port 127.0.0.1:%s: %m",
                          port->second.c_str());
        abort();
    }
    socklen_t len = sizeof(rcvbuf);
    getsockopt(m_fd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, &len);
    logging::info("MemPoolSim: %s module at %s (trigger: UDP there); its frames arrive on "
                  "127.0.0.1:%s (receive buffer %d B)", para.detType.c_str(), m_moduleStr.c_str(),
                  port->second.c_str(), rcvbuf);
}

UdpFront::~UdpFront()
{
    logging::info("MemPoolSim: %lu module frames, %lu incomplete, %lu stray packets dropped",
                  m_frames, m_incomplete, m_dropped);
    if (m_fd >= 0)  close(m_fd);
}

size_t UdpFront::frame(uint8_t* dst)
{
    while (recv(m_fd, m_rx.data(), m_rx.size(), MSG_DONTWAIT) > 0)  ++m_dropped;   // late packets

    static const char trigger[] = "TRIG";
    if (sendto(m_fd, trigger, 4, 0, (const sockaddr*)&m_module, sizeof(m_module)) != 4 &&
        m_frames < 5)
        logging::error("MemPoolSim: trigger to %s failed: %m", m_moduleStr.c_str());

    std::fill(m_have.begin(), m_have.end(), 0);
    unsigned n = 0;
    uint64_t framenum = 0;
    while (n < JungfrauData::PacketNum) {
        pollfd p{m_fd, POLLIN, 0};
        if (poll(&p, 1, n ? 200 : 1000) <= 0)  break;
        ssize_t sz = recv(m_fd, m_rx.data(), m_rx.size(), 0);
        if (sz != ssize_t(PacketBytes)) { ++m_dropped; continue; }
        auto pkt = reinterpret_cast<const JungfrauData::JungfrauPacket*>(m_rx.data());
        unsigned pn = pkt->header.packetnum;
        if (n == 0)  framenum = pkt->header.framenum;
        if (pkt->header.framenum != framenum || pn >= JungfrauData::PacketNum || m_have[pn]) {
            ++m_dropped;
            continue;
        }
        memcpy(&m_packets[size_t(pn) * PacketBytes], m_rx.data(), PacketBytes);
        m_have[pn] = 1;
        ++n;
    }
    ++m_frames;
    if (n < JungfrauData::PacketNum && m_incomplete++ < 5)
        logging::error("MemPoolSim: module %s sent %u of %zu packets of frame %lu",
                       m_moduleStr.c_str(), n, JungfrauData::PacketNum, framenum);

    memset(dst, 0, Line);
    auto ebh = reinterpret_cast<EvtBatcherHeader*>(dst);
    ebh->version = 1;
    ebh->width   = 2;
    MemPoolSim::Out in{dst, Line};
    for (int pn = JungfrauData::PacketNum - 1; pn >= 0; --pn) {
        if (!m_have[pn])  continue;
        memcpy(in.data(), &m_packets[size_t(pn) * PacketBytes], PacketBytes);
        in.tail(PacketBytes, uint8_t(pn));
    }
    if (n == 0) {                       // nothing came: one empty subframe
        memset(in.data(), 0, Line);
        in.tail(Line, 0);
    }
    return in.pos;
}

// epixuhr3x2 (EpixUHR3x2::_event): the panel subframe (tdest 3), 336 x 576 uint16 in row order, as
// the firmware (v5.0.0 on) assembles the six ASICs (disabled ones zero-filled; user.asic_enable
// enables all six here); psana's epixuhr3x2 raw() (raw alg 1.0.0) keeps each word's low 12 bits
// (gain bit 0, 11 data bits).  Pixel i of the panel is pattern(seed, seq, i, 12).  Tdest 2 (the
// detailed timing frame, unused by the DRP) carries a copy of the timing frame.
static const unsigned Uhr3x2Rows = 336, Uhr3x2Cols = 576, Uhr3x2Bytes = 2 * Uhr3x2Rows * Uhr3x2Cols;

static void epixuhr3x2Data(MemPoolSim::Out& out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const PixelMap pixels(Uhr3x2Rows * Uhr3x2Cols, 12, [](size_t j) { return uint32_t(j); });
    out.timingCopy(2);
    pixels.fill(reinterpret_cast<uint16_t*>(out.data()), seed, f.seq);
    out.tail(Uhr3x2Bytes, 3);
}

// One row per BEB detector type that can run with -d sim://
static const MemPoolSim::Batcher Batchers[] = {
    { "epix100", _padded(32) + _padded(Epix100Bytes), epix100Data },
    { "wave8",   _padded(32) + 8 * _padded(2 * Wave8Samples) + _padded(56) + _padded(32), wave8Data },
    { "wave8he", _padded(32) + 8 * _padded(2 * Wave8Samples) + _padded(64) + _padded(32), wave8heData },
    { "hrencoder", _padded(8), hrencoderData },
    { "epixm320", _padded(32) + 4 * _padded(2 * EpixMHdr + 2 * EpixMAsic), epixm320Data },
    { "opal",     _padded(32) + _padded(2 * OpalRows * OpalCols), opalData },
    { "piranha4", _padded(32) + _padded(2 * Piranha4Pixels), piranha4Data },
    { "tt",       _padded(TtPixels), ttData },
    { "tb",       _padded(TbEtmBytes), tbData },
    { "epixquad", 2 * _padded(32) + _padded(EquadBytes), epixquadData },
    { "epixquad1kfps", 2 * _padded(32) + _padded(EquadBytes), epixquadData },  // the same EpixQuad DRP
    { "epixUHR",  _padded(32) + 4 * _padded(UhrAsicBytes), epixUHRData },
    // + 16: subframe 0 is an EventBatcher of the TimingHeader (its header line and tail)
    { "epixhr2x2", 16 + 2 * _padded(Hr2NestedBytes), epixhr2x2Data, true },
    // its data comes from the module's UDP stream (UdpFront above), not from a framer
    { "jungfrau", _padded(32) + _padded(UdpFront::DataBytes), nullptr },
    { "epixuhr3x2", _padded(32) + _padded(Uhr3x2Bytes), epixuhr3x2Data },
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

// hsd (Digitizer::event, psalg/digitizer/Stream.hh, psana/psana/hsd/HsdPython.hh): after the
// TimingHeader, whose two opaque words are the hsd's event header (word 0: stream mask in bits
// 20-23, here raw and fex; word 1: bit 31 the JESD link status, else the event is damaged), one
// stream per bit of the mask, each a 16-byte StreamHeader {num_samples, stream_id << 24, 0, 0}
// and its uint16 samples:
//   raw (stream 0): HsdRawSamples samples, sample i = pattern(seed, seq, i, 12), the 12-bit ADC
//     codes of the 1160 samples hsd_config.py's default gate (user.raw.gate_ns 200) asks for;
//   fex (stream 1): HsdFexWords words of the sparsified stream: groups of 4 words with bit 15
//     set are skips (their low 15 bits add up the samples skipped), the rest are kept samples.
//     Skip A, peak 1 (4 baseline words, then 16 samples), skip B, peak 2 (12 samples), skip C.
//     The k-th kept word is pattern(seed, seq, HsdRawSamples + k, 15) and word j of skip g is
//     0x8000 | pattern(seed, seq, HsdRawSamples + 32 + 4 g + j, 6).  psana's hsd_raw_3_0_0
//     peaks() then gives peak 1 at A + 4 (its baseline words dropped) and peak 2 at A + B + 20,
//     A and B the skip groups' sums (psdaq/psdaq/sim/xtc2_check.py).
static const unsigned HsdRawSamples = 1160, HsdFexWords = 44, HsdStreamHdr = 16;
static const unsigned HsdMsgBytes   = 2 * HsdStreamHdr + 2 * (HsdRawSamples + HsdFexWords);

static void hsdMessage(uint8_t* out, const MemPoolSim::Frame& f, uint32_t seed)
{
    static const PixelMap raw(HsdRawSamples, 12, [](size_t j) { return uint32_t(j); });
    uint32_t* h = reinterpret_cast<uint32_t*>(out);
    h[0] = HsdRawSamples;  h[1] = 0u << 24;  h[2] = 0;  h[3] = 0;
    raw.fill(reinterpret_cast<uint16_t*>(out + HsdStreamHdr), seed, f.seq);
    out += HsdStreamHdr + 2 * HsdRawSamples;
    h = reinterpret_cast<uint32_t*>(out);
    h[0] = HsdFexWords;  h[1] = 1u << 24;  h[2] = 0;  h[3] = 0;
    uint16_t* q = reinterpret_cast<uint16_t*>(out + HsdStreamHdr);
    static const int layout[] = { -1, 20, -1, 12, -1 };     // -1: a skip group, else kept words
    unsigned kept = 0, skips = 0;
    for (int n : layout) {
        if (n < 0) {
            for (unsigned j = 0; j < 4; ++j, ++skips)
                *q++ = uint16_t(0x8000 | MemPoolSim::pattern(seed, f.seq, HsdRawSamples + 32 + skips, 6));
        } else {
            for (int j = 0; j < n; ++j, ++kept)
                *q++ = uint16_t(MemPoolSim::pattern(seed, f.seq, HsdRawSamples + kept, 15));
        }
    }
}

static const MemPoolSim::TDetMsg TDetMsgs[] = {
    { "ts",  TimingDataBytes, timingMessage, { 0, 0 } },
    { "hsd", HsdMsgBytes,     hsdMessage,    { (1u << 24) | (0x3u << 20) | HsdRawSamples, 1u << 31 } },
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

    // Subframe 0: the TimingHeader (getTimingHeader() returns its address), or an EventBatcher
    // whose only subframe it is (timingBatch)
    if (b.timingBatch) {
        uint8_t* nb = out.data();
        memset(nb, 0, lw);
        auto neh = reinterpret_cast<EvtBatcherHeader*>(nb);
        neh->version        = 1;
        neh->width          = width;
        neh->sequence_count = evtCounter & 0xff;
        Out in{nb, lw};
        in.tail(fill(in.data(), f, evtCounter, 0, 0, 0), 0);
        out.tail(in.pos, 0);
    } else {
        size_t th = fill(out.data(), f, evtCounter, 0, 0, 0);
        out.tail(th, 0);
    }
    if (!l1 || !b.data)  return out.pos;

    b.data(out, f, seed);
    return out.pos;
}

size_t MemPoolSim::corrupt(uint8_t* buffer, size_t size, bool batcher)
{
    size_t start = sizeof(Pds::TimingHeader);
    size_t bytes = size > start ? size - start : 0;
    if (batcher) {                      // walk the tails from the end, as EvtBatcherIterator does
        const size_t lw = EvtBatcherHeader::lineWidth(2);
        bytes = 0;
        size_t pos = size;              // end of the next subframe's tail
        while (pos >= 2 * lw) {
            size_t   tail = pos - lw;
            uint32_t sub;
            memcpy(&sub, buffer + tail, sizeof(sub));
            uint8_t  tdest  = buffer[tail + 4];
            size_t   padded = (size_t(sub) + lw - 1) & ~(lw - 1);
            if (padded + lw > tail)  break;     // would start before the header line
            size_t   at     = tail - padded;
            bool     copy   = sub == sizeof(Pds::TimingHeader) &&
                              memcmp(buffer + at, buffer + lw, sub) == 0;
            if (tdest != 0 && !copy && sub > bytes) {
                start = at;
                bytes = sub;
            }
            if (at == lw)  break;
            pos = at;
        }
    }
    if (bytes == 0)  return 0;
    size_t at = start + bytes / 2;
    buffer[at] ^= 0xff;
    return at;
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
    m_nOverruns (0),
    m_corruptSeq(0)
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
        if (!m_batcher->data)
            m_udp = std::make_unique<UdpFront>(para);
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
    if (const char* v = getenv(CorruptEnv)) {
        m_corruptSeq = strtoul(v, nullptr, 0);
        logging::warning("MemPoolSim: %s=%u: L1Accept seq %u gets one payload byte inverted (a deliberate fault)",
                         CorruptEnv, m_corruptSeq, m_corruptSeq);
    }

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
    if (m_udp) {
        _udpFrames(data, size);
        return;
    }
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
                auto th = reinterpret_cast<uint32_t*>(dmaBuffers[idx]);
                th[6] = m_tdetMsg->opaque[0];
                th[7] = m_tdetMsg->opaque[1];
                m_tdetMsg->data((uint8_t*)dmaBuffers[idx] + sz, f, seed);
                sz += m_tdetMsg->bytes;
            }
            if (m_corruptSeq && tid == TransitionId::L1Accept && f.seq == m_corruptSeq) [[unlikely]] {
                size_t at = corrupt((uint8_t*)dmaBuffers[idx], sz, m_batcher != nullptr);
                logging::warning("MemPoolSim: %s=%u: L1Accept seq %u lane %u: byte %zu of %zu inverted",
                                 CorruptEnv, m_corruptSeq, f.seq, lane, at, size_t(sz));
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

// As _frames, for a front-end whose data arrives over UDP (UdpFront): the module is triggered
// and its frame received outside m_simLock, so the readout is not held up meanwhile
void MemPoolSim::_udpFrames(const uint8_t* data, size_t size)
{
    bool     connected = m_connected.load(std::memory_order_acquire);
    unsigned lane      = __builtin_ffs(m_laneMask) - 1;

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

        uint32_t idx;
        {
            std::lock_guard<std::mutex> lock(m_simLock);
            if (m_free.empty()) [[unlikely]] {
                if (m_nOverruns++ < 5)
                    logging::error("MemPoolSim: no free DMA buffer for %s (credit protocol violated)",
                                   TransitionId::name(tid));
                continue;
            }
            idx = m_free.back();
            m_free.pop_back();
        }
        auto   buffer = (uint8_t*)dmaBuffers[idx];
        size_t sz     = fillBatcher(buffer, *m_batcher, f, m_evtCounter, false, 0);
        if (tid == TransitionId::L1Accept) {
            Out out{buffer, sz};
            out.timingCopy(1);          // the detailed timing frame; a copy stands in for it
            out.tail(m_udp->frame(out.data()), 2);
            sz = out.pos;
        }
        {
            std::lock_guard<std::mutex> lock(m_simLock);
            m_ready.push_back({int32_t(sz), idx, (lane << 8) | m_virtChan});
        }
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
