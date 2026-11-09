#include "Client.hh"
#include "Frame.hh"
#include "Module.hh"
#include "Queues.hh"

#include <sys/mman.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <string>

using namespace Pds::Tpr;

//  A stand-in for the TPR card, for running without hardware (psdaq/psdaq/sim, RUNBOOK 3d):
//  with PSDAQ_SIM_TPR=<dir> in the environment, the card's register map (BAR 1) and the
//  channel's message queues are regular files in <dir> named after the device files
//  (<dir>/tpra, <dir>/tpra<channel>), created zero-filled and mapped as the driver's device
//  files are.  The registers keep what is written (no firmware acts on them), so another
//  process can read what was programmed; no timing frame reaches the queues.  Without
//  PSDAQ_SIM_TPR the device files are opened, as before.
static std::string _simPath(const char* devname)
{
  const char* dir = getenv("PSDAQ_SIM_TPR");
  if (!dir || !*dir)  return std::string();
  const char* base = strrchr(devname, '/');
  return std::string(dir) + "/" + (base ? base+1 : devname);
}

static int _open(const char* devname, const std::string& sim, size_t size)
{
  if (sim.empty())  return ::open(devname, O_RDWR);
  int fd = ::open(sim.c_str(), O_RDWR|O_CREAT, 0644);
  if (fd >= 0 && ftruncate(fd, size) < 0) {
    close(fd);
    return -1;
  }
  printf("Tpr::Client: simulated TPR (PSDAQ_SIM_TPR): %s is %s\n", devname, sim.c_str());
  return fd;
}

Client::Client(const char* devname,
               unsigned    channel,
               bool        clksel,
               ModeSel     modsel) :
  _channel(channel),
  _dev    (nullptr),
  _queues (nullptr)
{
  _fd = _open(devname, _simPath(devname), sizeof(Pds::Tpr::TprReg));
  if (_fd<0) {
    perror("Could not open tpr");
    throw std::string("Could not open tpr");
  }

  void* ptr = mmap(0, sizeof(Pds::Tpr::TprReg), PROT_READ|PROT_WRITE, MAP_SHARED, _fd, 0);
  if (ptr == MAP_FAILED) {
    perror("Failed to map master");
    throw std::string("Failed to map master");
  }

  _dev = reinterpret_cast<Pds::Tpr::TprReg*>(ptr);

  if (_dev->tpr.clkSel() != clksel) {
    _dev->tpr.clkSel(clksel);
    printf("Changed clk xbar to %s mode\n", clksel ? "LCLS2":"LCLS1");
  }

  bool l2mode = (modsel==Lcls2Proto);
  if (_dev->tpr.modeSelEn()) {
      if (modsel != ClkSel) {
          if (_dev->tpr.modeSel() != l2mode) {
              _dev->tpr.modeSel( l2mode );
              printf("Changed mode sel to %s mode\n", l2mode ? "LCLS2":"LCLS1");
          }
      }
      else {
          _dev->tpr.modeSelEn(false);
          printf("Disabled mode sel\n");
      }
  }
  else if (modsel != ClkSel) {
      _dev->tpr.modeSel(l2mode);
      _dev->tpr.modeSelEn(true);
      printf("Enabled mode sel for %s mode\n", l2mode ? "LCLS2":"LCLS1");
  }

  _dev->xbar.setTpr( XBar::StraightIn );
  _dev->xbar.setTpr( XBar::StraightOut);

  { Pds::Tpr::RingB& ring = _dev->ring0;
    ring.clear();
    ring.enable(true);
    usleep(1000);
    ring.enable(false);
    ring.dumpFrames(); }

  char dev[16];
  sprintf(dev,"%s%x",devname,_channel);

  _fdsh = _open(dev, _simPath(dev), sizeof(Pds::Tpr::Queues));
  if (_fdsh < 0) {
    perror("Could not open sh");
    throw std::string("Could not open sh");
  }

  ptr = mmap(0, sizeof(Pds::Tpr::Queues), PROT_READ, MAP_SHARED, _fdsh, 0);
  if (ptr == MAP_FAILED) {
    perror("Failed to map slave");
    throw std::string("Failed to map slave");
  }

  _queues = reinterpret_cast<Pds::Tpr::Queues*>(ptr);

}

Client::~Client()
{
  if (_fdsh >= 0) {
    close(_fdsh);
    if (_queues)  munmap(_queues, sizeof(Pds::Tpr::Queues));
    _queues = nullptr;
  }
  _fdsh = -1;

  release();
}

void Client::release() {
  if (_fd>=0) {
    close(_fd);
    if (_dev)  munmap(_dev,sizeof(Pds::Tpr::TprReg));
    _dev = nullptr;
  }
  _fd=-1;
}

void Client::_dump() const
{
  printf("TprBase::channel[%u] evtsel %08x control %x\n",
         _channel,
         _dev->base.channel[_channel].evtSel,
         _dev->base.channel[_channel].control);
}

//  Setup the trigger channel
void Client::setup(unsigned output, unsigned delay, unsigned width, unsigned polarity, unsigned delaytap)
{
  _dev->base.setupTrigger(output, _channel, polarity, delay, width, delaytap);
}

// Setup the transmit source
void Client::loopOut(bool enable)
{
    _dev->xbar.setTpr(enable ? XBar::LoopOut : XBar::StraightOut);
}

  //  Enable the trigger
void Client::start(TprBase::Partition partn)
{
  _dump();
  _dev->base.setupChannel(_channel, (TprBase::Partition)partn, 0, 0, 1);
  _dump();

  char buff[32];
  if (read(_fdsh, &buff, 32 )) {}
  _rp = _queues->allwp[_channel];
}

//  Enable the trigger
void Client::start(TprBase::FixedRate rate)
{
  _dump();
  _dev->base.setupChannel(_channel, TprBase::Any, rate, 0, 0, 1);
  _dump();

  char buff[32];
  if (read(_fdsh, &buff, 32 )) {}
  _rp = _queues->allwp[_channel];
}

//  Enable the trigger
void Client::start(TprBase::ACRate rate, unsigned timeSlotMask)
{
  _dump();
  _dev->base.setupChannel(_channel, TprBase::Any, rate, timeSlotMask, 0, 0, 1);
  _dump();

  char buff[32];
  if (read(_fdsh, &buff, 32 )) {}
  _rp = _queues->allwp[_channel];
}

//  Enable the trigger
void Client::start(TprBase::EventCode evcode)
{
  _dump();
  _dev->base.setupChannel(_channel, evcode, 0, 0, 1);
  _dump();

  char buff[32];
  if (read(_fdsh, &buff, 32 )) {}
  _rp = _queues->allwp[_channel];
}

//  Disable the trigger
void Client::stop()
{
  _dev->base.channel[_channel].control = 0;
}

  //
  //  Seek timing frame by pulseId
  //  Return address on success or 0
  //
const Pds::Tpr::Frame* Client::advance(uint64_t pulseId)
{
  char buff[32];
  const Pds::Tpr::Queues& q = *_queues;
  const Pds::Tpr::Frame* f=0;
  while(1) {
    while (_rp < q.allwp[_channel]) {
      f = reinterpret_cast<const Pds::Tpr::Frame*>(&q.allq [ q.allrp[_channel].idx[_rp &(MAX_TPR_ALLQ-1)] & (MAX_TPR_ALLQ-1)]);
      if (f->pulseId >  pulseId) return 0;
      _rp++;
      if (f->pulseId == pulseId) return f;
    }
    if (read(_fdsh, buff, 32)) {}
  }
  return 0;
}

const Pds::Tpr::Frame* Client::advance()
{
  char buff[32];
  const Pds::Tpr::Queues& q = *_queues;
  const Pds::Tpr::Frame* f=0;
  while(1) {
    while (_rp < q.allwp[_channel]) {
      f = reinterpret_cast<const Pds::Tpr::Frame*>(&q.allq [ q.allrp[_channel].idx[_rp &(MAX_TPR_ALLQ-1)] & (MAX_TPR_ALLQ-1)]);
      _rp++;
      return f;
    }
    if (read(_fdsh, buff, 32)) {}
  }
  return 0;
}
