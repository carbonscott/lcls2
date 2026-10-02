/**
 * @file
 * @brief MemPoolGpu, the memory pool of the GPU DRP (DMA, host write, calibration and reduce buffers), with DataDev, DetPanel, DmaDsc and Ptr. Also holds the HOST_REARMS_DMA and HOST_LAUNCHED_REDUCERS build switches, both commented out.
 */
#pragma once

#include "gpuUtils.hh"

#include <cstddef>
#include <vector>
#include <thread>
#include <atomic>

#include <cuda_runtime.h>
#include <nvtx3/nvtx3.hpp>

#include "drp/drp.hh"

// NVTX provides the ability to annotate code and structures for the purpose of
// making traces in the Nsight Systems profiler more easily identifiable.  It
// nominally adds very little overhead but the documentation warns against
// instrumenting code that takes less than 1 us to run.  The NVTX_DISABLE macro
// is used by NVTX header files to disable NVTX calls in the codebase.
/** Disable NVTX profiling annotations; per the comment above, NVTX headers check this macro. It is defined after nvtx3.hpp is included above. */
#define NVTX_DISABLE

// If the HOST_REARMS_DMA macro is defined, the GPU DRP can be run without
// privileges.  The CPU rearms the DMA buffers for writing as early as possible,
// but necessarily later than when the GPU can rearm them.  This will impact
// performance so this definition is normally commented out.  In order to have
// the GPU rearm the DMA buffers, the process must run with an as yet to be
// determined privilege (cap_sys_rawio, perhaps?), but I've not had success yet
// doing that.  Instead, set the executable up with root ownership and suid:
//
// sudo chown root $TESTRELDIR/bin/drp_gpu; sudo chmod u+s $TESTRELDIR/bin/drp_gpu
//
//#define HOST_REARMS_DMA                 // Commented out => need sudo

// The HOST_LAUNCHED_REDUCERS macro is used to determine when the Reducer GPU
// code is launched.  Without this macro defined, Reducers constructed using a
// CUDA graph are launched at startup time using the Reducer::startup() method.
// Reducers launched this way remain present on the GPU for the duration of a
// Configure/Unconfigure cycle.  The idea behind this is to amortise the launch
// overhead and to pay it at a non-critical time.
// Reducers composed of raw kernels are handled as if the macro were defined.
// With it defined, Reducers, whether constructed using a graph or composed of
// raw kernels are launched upon reception of a TEB result (in
// TebReceiver::complete()).  The Reducer runs for as long as it takes for it to
// process one event and then exits.  This means that the launch overhead is
// paid in the real-time loop.
//#define HOST_LAUNCHED_REDUCERS


namespace Drp {
  namespace Gpu {

// @todo: Move to a common header file or use std::pair/std::tuple
/** Pair of pointers of type T, one for the host and one for the device; Reducer uses it for each ring queue object and its device copy. */
template <class T>
struct Ptr
{
  /** Host pointer (null by default). */
  T* h = nullptr;                       // A host pointer
  /** Device pointer (null by default). */
  T* d = nullptr;                       // A device pointer
};

// DmaDsc structure from:
//   https://github.com/slaclab/surf/blob/main/axi/dma/rtl/v2/AxiStreamDmaV2Write.vhd
/** DmaDsc: the 8-byte DMA descriptor (header word and size word) defined by AxiStreamDmaV2Write.vhd in the SURF library (per the code comment). Doxygen parses this packed struct as a function named __attribute__. */
struct __attribute__((packed)) DmaDsc
{
  uint32_t header;
  uint32_t size;

  inline uint32_t result()    const { return  header        & 0x03; }
  inline uint32_t overflow()  const { return (header >>  2) & 0x01; }
  inline uint32_t cont()      const { return (header >>  3) & 0x01; }
  inline uint32_t lastUser()  const { return (header >> 16) & 0xFF; }
  inline uint32_t firstUser() const { return (header >> 24) & 0xFF; }

  // firstUser = 0x02 is SOF: not an error
  inline uint32_t errorMask() const { return 0xfdffffff; }
};

static_assert(sizeof(DmaDsc) == 8, "DmaDsc must be 64-bits (8-bytes)");

/**
 * Wraps a data_dev device so it can be automatically freed
 */
class DataDev
{
public:
  /** Open path for reading and writing; logs a critical message and aborts on failure. */
  DataDev(const char* path);
  /** Close the file descriptor. */
  ~DataDev()
  {
    close(fd_);
  }

  /** Return the file descriptor. */
  int fd() const { return fd_; }

protected:
  int fd_;
};

/** The PGP device of the GPU DRP and the GPU resources tied to it. */
struct DetPanel
{
  DataDev               datadev;  ///< The opened device (/dev/null in simulator mode).
  void*                 fpgaRegs;  ///< Host mapping of the GpuAsyncCore FPGA registers; in simulator mode, a zeroed pinned host block of 0x600 words.
  /** Device addresses of the DMA write buffers (FPGA to GPU), one per DMA buffer, kept on the host. */
  std::vector<uint8_t*> dmaBuffers;     // Host vector of dmaCount dptrs
  /** Device array holding the same DMA buffer addresses. */
  uint8_t**             dmaBuffers_d;   // Device array of dmaCount dptrs
  std::string           name;  ///< Device path.
  CoreRegisters         coreRegs;  ///< Register object for the GpuAsyncCore registers at fpgaRegs (simulated in simulator mode).

  /** Open device (DataDev aborts on failure) and keep its path as name. */
  DetPanel(std::string& device) : datadev(device.c_str()), name(device) {}
};

/** Memory pool of the GPU DRP. It opens the PGP device, or runs in simulator mode if the device is /dev/null, allocates the DMA buffers on the GPU and gives them to the FPGA. It also manages the pinned host write buffers and the calibration and reduce buffers on the GPU. */
class MemPoolGpu : public Drp::MemPool
{
public:
  /** Read the dmaBufSize (rounded up to a multiple of 64 kB, default 64 kB), dmaBufCount (power of 2, default 4) and gpuId kwargs, set up the CUDA context and check the required device attributes. Then set up the device registers (or simulated ones) and the DMA buffers, stop FPGA writes, set the write count and DMA target, and initialize the base pool. Aborts on errors. */
  MemPoolGpu(Parameters& para);
  /** Release the driver's GPU memory registration, then free the DMA buffers and the host write, calibration and reduce buffers. */
  virtual ~MemPoolGpu();
  /** Declared but not defined in MemPool.cc. */
  int initialize(Parameters& para);
public:   // Virtuals
  /** Return the file descriptor of the device panel's DataDev. */
  int fd() const override { return m_panel->datadev.fd(); }
  /** Set the driver DMA mask to the destinations (dmaDest of lane and virtChan) of the lanes in laneMask; once a call has succeeded, later calls only log that the earlier setting is in effect. Returns 1 if dmaSetMaskBytes fails, else 0. */
  int setMaskBytes(uint8_t laneMask, unsigned virtChan) override;
private:  // Virtuals
  ssize_t _freeDma(unsigned count, uint32_t* indices) override { return 0; /* Nothing to do */ }
public:
  /** Return the CUDA context. */
  const CudaContext& context() const { return m_context; }
  /** Return the device panel. */
  const std::shared_ptr<DetPanel> panel() const { return m_panel; }
  /** Allocate nbuffers() zeroed pinned host buffers of size bytes each, for the DMA descriptors, TimingHeaders and TEB input data (per the code comment). Logs an error and does nothing if they already exist. */
  void createHostBuffers(size_t size);
  /** Free the host write buffers if they exist. */
  void destroyHostBuffers();
  /** Allocate nbuffers() zeroed device buffers of nElements floats each for calibrated data. Logs an error and does nothing if they already exist. */
  void createCalibBuffers(unsigned nElements);
  /** Free the calibration buffers if they exist. */
  void destroyCalibBuffers();
  /** Allocate nbuffers() zeroed device buffers of reserved plus nBytes bytes each (both rounded up to multiples of 8); the reserved part at the front of each is for the datagram header. Logs an error and does nothing if they already exist. */
  void createReduceBuffers(size_t nBytes, size_t reserved);
  /** Free the reduce buffers if they exist. */
  void destroyReduceBuffers();
  /** Vector of uint32_t pointers; not used in drpGpu. */
  using vecpu32_t = std::vector<uint32_t*>;
  /** Return the pinned host write buffers: nbuffers() contiguous buffers of hostWrtBufsSize() bytes. */
  const auto& hostWrtBufs()      const { return m_hostWrtBufs; }
  /** Return the device calibration buffers: nbuffers() contiguous buffers of calibBufsSize() bytes. */
  const auto& calibBuffers_d ()  const { return m_calibBuffers_d; }
  /** Return the device address of the data part of reduce buffer 0; each further buffer starts reduceBufsReserved() plus reduceBufsSize() bytes later. */
  const auto& reduceBuffers_d()  const { return m_reduceBuffers_d; }
  /** Return the size in bytes of one host write buffer (0 if none). */
  size_t hostWrtBufsSize()       const { return m_hostWrtBufsSize; }
  /** Return the size in bytes of one calibration buffer (0 if none). */
  size_t calibBufsSize()         const { return m_calibBufsSize; }
  /** Return the size in bytes of the data part of one reduce buffer, without the reserved part (0 if none). */
  size_t reduceBufsSize()        const { return m_reduceBufsSize; }
  /** Return the size in bytes of the reserved header part at the front of each reduce buffer. */
  size_t reduceBufsReserved()    const { return m_reduceBufsRsvd; }
public:
  /** Return the driver's count of receive buffers held by the user (dmaGetRxBuffinUserCount()). */
  int64_t nPgpInUser () const { return dmaGetRxBuffinUserCount  (fd()); }
  /** Return the driver's count of receive buffers in hardware (dmaGetRxBuffinHwCount()). */
  int64_t nPgpInHw   () const { return dmaGetRxBuffinHwCount    (fd()); }
  /** Return the driver's count of receive buffers in the pre-hardware queue (dmaGetRxBuffinPreHwQCount()). */
  int64_t nPgpInPreHw() const { return dmaGetRxBuffinPreHwQCount(fd()); }
  /** Return the driver's count of receive buffers in the software queue (dmaGetRxBuffinSwQCount()). */
  int64_t nPgpInRx   () const { return dmaGetRxBuffinSwQCount   (fd()); }
private:
  int  _gpuMapFpgaMem(int fd, CUdeviceptr& buffer, uint64_t offset, size_t size, int write);
  void _gpuUnmapFpgaMem(CUdeviceptr& buffer);
private:
  CudaContext               m_context;
  std::shared_ptr<DetPanel> m_panel;
  bool                      m_setMaskBytesDone;
  size_t                    m_hostWrtBufsSize;
  uint32_t*                 m_hostWrtBufs;      // [nBuffers * nElements]
  size_t                    m_calibBufsSize;
  float*                    m_calibBuffers_d;   // [nBuffers * nElements]
  size_t                    m_reduceBufsSize;
  size_t                    m_reduceBufsRsvd;
  uint8_t*                  m_reduceBuffers_d;  // [nBuffers * nBytes]
};

  } // Gpu
} // Drp
