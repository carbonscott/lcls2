// drp_sim_frame <detType> <seq> [<seed>]: write one simulated L1Accept DMA buffer, as
// MemPoolSim makes it for 'drp -D <detType> -d sim://', to stdout (for the framer's tests):
// an EventBatcher buffer for a BEB type, or the TimingHeader and TDet message for 'ts'.
#include "MemPoolSim.hh"
#include "xtcdata/xtc/TransitionId.hh"

#include <cstdio>
#include <cstdlib>
#include <vector>

int main(int argc, char** argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <detType> <seq> [<seed>]\n", argv[0]);
        return 2;
    }
    const Drp::MemPoolSim::Batcher* b = Drp::MemPoolSim::batcher(argv[1]);
    const Drp::MemPoolSim::TDetMsg* t = Drp::MemPoolSim::tdetMsg(argv[1]);
    if (!b && !t) {
        fprintf(stderr, "%s: no simulated EventBatcher layout or TDet message for detType '%s'\n",
                argv[0], argv[1]);
        return 1;
    }
    if (b && !b->data) {                        // jungfrau: its module sends the data (UdpFront)
        fprintf(stderr, "%s: %s's data comes from its module over UDP (psdaq.sim.simsls), not "
                "from a framer\n", argv[0], argv[1]);
        return 1;
    }
    Drp::MemPoolSim::Frame f{};
    f.pulseIdAndControl = (uint64_t(XtcData::TransitionId::L1Accept) << 56) | 0x123456789abull;
    f.nanoseconds       = 500000000;
    f.seconds           = 1100000000;
    f.env               = 1;                    // readout group 0
    f.seq               = strtoul(argv[2], nullptr, 0);
    uint32_t seed       = argc > 3 ? strtoul(argv[3], nullptr, 0) : 0x1234;

    if (t) {                                    // TimingHeader + the TDet message
        std::vector<uint8_t> buffer(32 + t->bytes);
        size_t size = Drp::MemPoolSim::fill(buffer.data(), f, f.seq, 0, 0, seed);
        t->data(buffer.data() + size, f, seed);
        size += t->bytes;
        return fwrite(buffer.data(), 1, size, stdout) == size ? 0 : 1;
    }

    std::vector<uint8_t> buffer(8 + (32 + 8) + b->dataBytes);
    size_t size = Drp::MemPoolSim::fillBatcher(buffer.data(), *b, f, f.seq, true, seed);
    if (size > buffer.size()) {
        fprintf(stderr, "%s: %s frame of %zu B overran its %zu B buffer\n", argv[0], argv[1],
                size, buffer.size());
        return 1;
    }
    return fwrite(buffer.data(), 1, size, stdout) == size ? 0 : 1;
}
