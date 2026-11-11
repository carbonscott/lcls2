// g++ -I xtcdata repro.cc -o repro && ./repro
#include "xtcdata/xtc/Damage.hh"
#include <cstdio>
using XtcData::Damage;
int main()
{
    Damage a(0), b(0);
    a.increase(Damage::Corrupted);     // bit 3
    b.increase(Damage::UserDefined);   // bit 12
    printf("increase(Corrupted)   -> value 0x%04x\n", a.value());
    printf("increase(UserDefined) -> value 0x%04x, userBits %u\n", b.value(), b.userBits());
    return b.value() == 0;             // exits 1 while the bug is present
}
