#pragma once

#include "drp.hh"

#include <atomic>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace Drp {

// A software stand-in for the PGP card's DMA engine and the TDet firmware behind it, so that a
// CPU DRP runs with no hardware.  Selected with '-d sim://<host>:<port>' (or 'sim://<zmq
// endpoint>'), it receives timing frames from simxpm (psdaq/psdaq/sim/simxpm.py) and turns each
// one into the DMA buffers PgpReader expects: a TimingHeader per lane, followed for L1Accepts
// by 'sim_length' words of payload, as the TDetSemi firmware block would.
//
// Protocol (ZMQ DEALER here, ROUTER in simxpm; each message is [type, payload]):
//   -> HELLO  {alias,host,pid,lanes,dmaCount}   <- WELCOME {xpm,link,pvbase}
//   -> CREDIT u32 n                              frames this DRP can still take
//   -> CONNECT {group} / DISCONNECT / BYE        readout group membership
//   <- FRAMES n x Frame                          in timing order
// simxpm sends a frame only when every connected member of its readout groups has credit, so
// nothing is dropped and all DRPs of a group see the same pulses in the same order.
//
// Payload, per lane, in 32-bit words (L = sim_length):
//   w0 = pulseId & 0xffffffff, w1 = pulseId >> 32, w2 = seq (L1Accepts since the last
//   GroupL0Reset), w3 = seed, w[k] = seed + w0 + k + (lane << 16) for k = 4..L-1.
// The seed comes from the configuration database at Configure (see XpmDetector).
// The timing system's DRP (-D ts) gets the timing message its TDet firmware sends instead of
// these words: TimingData (TimingDef.hh) with the frame's pulseId and time (MemPoolSim.cc).
//
// Detector types whose data the AxiStreamBatcherEventBuilder formats (BEBDetector) get their
// DMA buffers in that format instead (see EventBatcher.hh): a batcher header, the TimingHeader
// as subframe 0 and, for L1Accepts, the type's subframes.  The layout is chosen by detType
// from a table in MemPoolSim.cc ('batcher' below); a BEB type not in it cannot run sim://.
// Each data subframe starts with {w0 = pulseId lo, w1 = pulseId hi, w2 = seq, w3 = seed}
// where the type has room for it.  Pixel i of the image the type's DRP builds (psana's raw
// array, flattened) is pattern(seed, seq, i, bits): it depends on where the pixel is, so a DRP
// that reorders or offsets pixels wrongly fails psdaq/psdaq/sim/xtc2_check.py (pattern.py is
// the same function in Python).  The framer writes each pixel where the detector's firmware
// would, e.g. epix100's interleaved ASIC rows, so the DRP's own reordering is what is checked.
class MemPoolSim : public MemPool
{
public:
    // One timing frame as sent by simxpm, little-endian
    struct Frame
    {
        uint64_t pulseIdAndControl;     // as in Pds::TimingHeader
        uint32_t nanoseconds;
        uint32_t seconds;               // since the EPICS epoch
        uint32_t env;                   // readout group mask in bits 0-15
        uint32_t seq;                   // L1Accept sequence number, 0 for transitions
    } __attribute__((packed));
    static_assert(sizeof(Frame) == 24, "simxpm frame size");
    // Writes the subframes of one EventBatcher buffer
    struct Out
    {
        uint8_t* buffer;
        size_t   pos;                   // where the next subframe's data starts
        uint8_t* data() { return buffer + pos; }
        void     tail(uint32_t size, uint8_t tdest);    // close the subframe of 'size' bytes
        void     timingCopy(uint8_t tdest);             // a subframe holding the TimingHeader
    };
    // EventBatcher layout of one BEB type's L1Accept DMA buffer
    struct Batcher
    {
        const char* detType;
        unsigned    dataBytes;          // most bytes its L1Accept subframes take after the
                                        //   TimingHeader's, tails included
        // Write the type's L1Accept subframes after the TimingHeader's (tdest 0)
        void      (*data)(Out& out, const Frame& f, uint32_t seed);
    };
    static const Batcher* batcher(const std::string& detType);
    // An XpmDetector type whose TDet firmware sends a formatted message instead of the
    // TDetSemi words above: 'bytes' of it after each L1Accept's TimingHeader (MemPoolSim.cc)
    struct TDetMsg
    {
        const char* detType;
        unsigned    bytes;
        void      (*data)(uint8_t* out, const Frame& f, uint32_t seed);
    };
    static const TDetMsg* tdetMsg(const std::string& detType);
    // The simulated value of pixel 'index' in event 'seq' (see above)
    static uint32_t pattern(uint32_t seed, uint32_t seq, uint32_t index, unsigned bits);
    static uint32_t mix(uint32_t index);        // the position-dependent part of pattern()
public:
    static bool isSimDevice(const std::string& device);
    // Lay out one DMA buffer for frame 'f'; returns its size in bytes
    static size_t fill(uint8_t* buffer, const Frame& f, uint32_t evtCounter,
                       unsigned lane, unsigned length, uint32_t seed);
    static size_t fillBatcher(uint8_t* buffer, const Batcher& b, const Frame& f,
                              uint32_t evtCounter, bool l1, uint32_t seed);
    // A deliberate fault, for showing that the per-event check catches a corrupted payload
    // (daq_sim matrix --break corrupt): with CorruptEnv=<seq> in the DRP's environment, the
    // L1Accept with that seq gets one byte inverted.  corrupt() inverts the middle byte of the
    // largest data subframe of an EventBatcher buffer (not subframe 0, the TimingHeader, nor a
    // copy of it), or of what follows the TimingHeader otherwise (TDetSemi words, a TDet
    // message); it returns that byte's offset in the buffer, 0 if the buffer has no payload.
    static constexpr const char* CorruptEnv = "PSDAQ_SIM_CORRUPT_SEQ";
    static size_t corrupt(uint8_t* buffer, size_t size, bool batcher);
public:
    MemPoolSim(const Parameters& para);
    virtual ~MemPoolSim();
    virtual int fd() const override { return m_efd; }
    virtual int setMaskBytes(uint8_t laneMask, unsigned virtChan) override;
public:                                 // For XpmDetector
    MemPoolSim* sim() override { return this; }
    bool batched() const { return m_batcher != nullptr; }    // EventBatcher framing (fillBatcher)
    unsigned paddr();                   // (xpm << 16) | link, once simxpm has answered
    void connect(unsigned readoutGroup, unsigned length);
    void disconnect();
    void seed(uint32_t value) { m_seed.store(value, std::memory_order_release); }
private:
    virtual ssize_t _freeDma(unsigned count, uint32_t* indices) override;
    virtual ssize_t _readDma(uint32_t count, int32_t* ret, uint32_t* index,
                             uint32_t* flags, uint32_t* errors, uint32_t* dest) override;
    virtual ssize_t _retDma(unsigned count, uint32_t* indices) override;
    void _return(unsigned count, const uint32_t* indices);
    void _receiver();
    void _frames(const uint8_t* data, size_t size);
    int  _send(void* socket, const std::string& type, const void* data, size_t size);
private:
    struct Ready { int32_t size; uint32_t index; uint32_t dest; };
    std::string             m_endpoint;
    std::string             m_alias;
    const Batcher*          m_batcher;          // EventBatcher framing, or nullptr for TDet
    const TDetMsg*          m_tdetMsg;          // TDet message instead of TDetSemi words, or nullptr
    unsigned                m_nLanes;
    uint8_t                 m_laneMask;
    unsigned                m_virtChan;
    int                     m_efd;              // eventfd, readable while DMAs are ready
    uint8_t*                m_memory;
    std::mutex              m_simLock;          // Guards m_free and m_ready
    std::vector<uint32_t>   m_free;
    std::deque<Ready>       m_ready;
    std::thread             m_thread;
    std::atomic<bool>       m_terminate;
    std::atomic<bool>       m_connected;
    std::atomic<bool>       m_changed;          // Send CONNECT or DISCONNECT
    std::atomic<unsigned>   m_group;
    std::atomic<unsigned>   m_length;
    std::atomic<uint32_t>   m_seed;
    std::mutex              m_regLock;
    std::condition_variable m_regCv;
    bool                    m_registered;
    unsigned                m_paddr;
    uint32_t                m_evtCounter;       // Receiver thread only
    unsigned                m_credit;           // Granted, not yet used; receiver thread only
    uint64_t                m_nOverruns;
    uint32_t                m_corruptSeq;       // CorruptEnv's seq, 0 if unset
};

}
