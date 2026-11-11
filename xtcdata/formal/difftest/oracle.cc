// Differential-test oracle for the XTC2 formal model.
//
// Reads one case per line on stdin, runs the real xtcdata code on it and
// prints one result line per case on stdout.  The Lean model (xtcdiff) reads
// the same lines and must print the same results.
//
// A case that makes the library call abort() prints "ABORT"; the library's
// own "*** ..." diagnostics go to stderr (or to stdout on a line of their
// own, which the comparator drops).
#include "xtcdata/xtc/Xtc.hh"
#include "xtcdata/xtc/Dgram.hh"
#include "xtcdata/xtc/XtcIterator.hh"
#include "xtcdata/xtc/XtcFileIterator.hh"
#include "xtcdata/xtc/NamesId.hh"
#include "xtcdata/xtc/TimeStamp.hh"
#include "xtcdata/xtc/TransitionId.hh"
#include "xtcdata/xtc/Level.hh"

#include <csetjmp>
#include <csignal>
#include <cstring>
#include <cinttypes>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <unistd.h>
#include <fcntl.h>

using namespace XtcData;

static sigjmp_buf g_jmp;
static void onAbort(int) { siglongjmp(g_jmp, 1); }
static void onSegv(int)  { siglongjmp(g_jmp, 2); }

static std::vector<uint8_t> unhex(const std::string& s)
{
    std::vector<uint8_t> v;
    if (s == "-") return v;
    for (size_t i = 0; i + 1 < s.size(); i += 2)
        v.push_back((uint8_t)strtoul(s.substr(i, 2).c_str(), 0, 16));
    return v;
}

// The walk every reader in the tree uses: descend into Parent, record the rest.
class Walk : public XtcIterator
{
public:
    Walk(const char* base, std::ostringstream& out, long stopAfter)
        : _base(base), _out(out), _left(stopAfter) {}
    int process(Xtc* xtc, const void* bufEnd) override
    {
        _out << " " << ((const char*)xtc - _base) << ":" << xtc->contains.value()
             << ":" << xtc->extent;
        if (_left > 0 && --_left == 0) return 0;
        if (xtc->contains.id() == TypeId::Parent) iterate(xtc, bufEnd);
        return 1;
    }
private:
    const char* _base;
    std::ostringstream& _out;
    long _left;
};

static std::string run(const std::string& line)
{
    std::istringstream in(line);
    std::string op;
    in >> op;
    std::ostringstream out;

    if (op == "typeid_ctor") {
        unsigned t, v; in >> t >> v;
        TypeId x((TypeId::Type)t, v);
        out << x.value() << " " << (unsigned)x.id() << " " << x.version();
    } else if (op == "typeid_str") {
        std::string s; in >> s;
        // white space travels as ~s ~t ~n
        for (const char* e : {"~s ", "~t\t", "~n\n"})
            for (size_t p; (p = s.find(std::string(e, 2))) != std::string::npos;) s.replace(p, 2, 1, e[2]);
        TypeId x(s.c_str());
        out << x.value() << " " << (unsigned)x.id() << " " << x.version();
    } else if (op == "typeid_name") {
        unsigned t; in >> t;
        out << TypeId::name((TypeId::Type)t);
    } else if (op == "damage_inc_value") {
        unsigned d, v; in >> d >> v;
        Damage x((uint16_t)d); x.increase((Damage::Value)v);
        out << x.value();
    } else if (op == "damage_inc_u16") {
        unsigned d, v; in >> d >> v;
        Damage x((uint16_t)d); x.increase((uint16_t)v);
        out << x.value();
    } else if (op == "damage_get") {
        unsigned d; in >> d;
        Damage x((uint16_t)d);
        out << x.bits() << " " << x.userBits();
    } else if (op == "damage_setuser") {
        unsigned d, v; in >> d >> v;
        Damage x((uint16_t)d); x.userBits((uint16_t)v);
        out << x.value();
    } else if (op == "src_ctor") {
        unsigned value, level; in >> value >> level;
        Src x(value, (Level::Type)level);
        uint32_t raw; memcpy(&raw, &x, 4);
        out << raw << " " << (unsigned)x.level() << " " << x.value();
    } else if (op == "namesid") {
        unsigned node, names; in >> node >> names;
        NamesId x(node, names);
        uint32_t raw; memcpy(&raw, &x, 4);
        out << raw << " " << x.nodeId() << " " << x.namesId() << " " << (unsigned)x;
    } else if (op == "ts_u64") {
        uint64_t s; in >> s;
        TimeStamp x(s);
        out << x.value() << " " << x.seconds() << " " << x.nanoseconds() << " "
            << x.to_ns() << " " << x.isZero();
    } else if (op == "ts_secnsec") {
        unsigned s, n; in >> s >> n;
        TimeStamp x(s, n);
        out << x.value() << " " << x.to_ns();
    } else if (op == "ts_from_ns") {
        uint64_t n; in >> n;
        TimeStamp x; x.from_ns(n);
        out << x.value() << " " << x.to_ns();
    } else if (op == "ts_cmp") {
        uint64_t a, b; in >> a >> b;
        TimeStamp x(a), y(b);
        out << (x > y) << " " << (x == y);
    } else if (op == "transition") {
        unsigned type, tid, env; in >> type >> tid >> env;
        Transition x((TransitionBase::Type)type, (TransitionId::Value)tid, TimeStamp((uint64_t)0), env);
        out << x.env << " " << x.control() << " " << (unsigned)x.service() << " "
            << (unsigned)x.type() << " " << x.isEvent() << " " << x.isExtended() << " "
            << x.readoutGroups() << " " << x.keepRaw();
    } else if (op == "env") {
        // accessors on a raw env word, as read back from a file
        uint32_t env; in >> env;
        L1Dgram x; x.env = env;
        out << x.control() << " " << (unsigned)x.service() << " " << (unsigned)x.type() << " "
            << x.isEvent() << " " << x.isExtended() << " " << x.readoutGroups() << " "
            << x.keepRaw() << " " << x.reserved();
    } else if (op == "trname") {
        unsigned t; in >> t;
        out << TransitionId::name((TransitionId::Value)t);
    } else if (op == "levelname") {
        unsigned t; in >> t;
        out << Level::name((Level::Type)t);
    } else if (op == "sizeof_payload") {
        uint32_t e; in >> e;
        Xtc x; x.extent = e;
        out << x.sizeofPayload();
    } else if (op == "alloc") {
        // alloc <extent> <size> <endOffset|none>: Xtc at offset 0 of a buffer
        uint32_t e; uint64_t size; std::string endS; in >> e >> size >> endS;
        static char buf[64];
        Xtc* x = (Xtc*)buf; x->extent = e;
        const void* end = endS == "none" ? 0 : buf + strtoull(endS.c_str(), 0, 10);
        char* p = (char*)x->alloc(size, end);
        out << (uint64_t)(p - buf) << " " << x->extent;
    } else if (op == "iterate") {
        // iterate <hex buffer> <bufEnd offset|none> <stopAfter, 0 = never>
        std::string hex, endS; long stop; in >> hex >> endS >> stop;
        std::vector<uint8_t> v = unhex(hex);
        // exact-size heap block, so that AddressSanitizer sees every read past it
        char* buf = (char*)malloc(v.size() ? v.size() : 1);
        memcpy(buf, v.data(), v.size());
        const void* end = endS == "none" ? 0 : buf + strtoull(endS.c_str(), 0, 10);
        Walk w(buf, out, stop);
        out << "ok";
        w.iterate((Xtc*)buf, end);
        free(buf);
    } else if (op == "fileiter") {
        // fileiter <hex file> <maxDgramSize> <maxDgrams>
        std::string hex; size_t maxSize; int maxDg; in >> hex >> maxSize >> maxDg;
        std::vector<uint8_t> v = unhex(hex);
        char name[] = "/tmp/xtcoracleXXXXXX";
        int fd = mkstemp(name); unlink(name);
        if (write(fd, v.data(), v.size()) != (ssize_t)v.size()) return "IOERR";
        lseek(fd, 0, SEEK_SET);
        fflush(stdout);
        // the iterator printf()s why it returns 0: capture that to name the path taken
        char oname[] = "/tmp/xtcoracleoutXXXXXX";
        int saved = dup(1), cap = mkstemp(oname); unlink(oname);
        dup2(cap, 1);
        {
            XtcFileIterator it(fd, maxSize);
            out << "ok";
            for (int i = 0; i < maxDg; i++) {
                Dgram* dg = it.next();
                if (!dg) {
                    fflush(stdout);
                    char msg[256] = {0};
                    if (pread(cap, msg, sizeof(msg) - 1, 0) < 0) msg[0] = 0;
                    out << (strstr(msg, "larger than maximum") ? " end:big" :
                            strstr(msg, "read error")          ? " end:err" :
                            strstr(msg, "incomplete payload")  ? " end:short" : " end:eof");
                    break;
                }
                out << " " << dg->xtc.extent << "@" << lseek(fd, 0, SEEK_CUR);
            }
        }
        fflush(stdout); dup2(saved, 1); close(saved); close(cap); close(fd);
    } else {
        return "BADOP";
    }
    return out.str();
}

int main()
{
    signal(SIGABRT, onAbort);
    signal(SIGSEGV, onSegv);
    signal(SIGBUS, onSegv);
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        std::string r;
        int j = sigsetjmp(g_jmp, 1);
        if (j == 0)      r = run(line);
        else if (j == 1) r = "ABORT";
        else             r = "SEGV";
        std::cout << r << "\n";
    }
    return 0;
}
