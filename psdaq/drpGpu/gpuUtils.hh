/**
 * @file
 * @brief GPU DRP utilities: CUDA error checks, CudaContext, CoreRegisters (GpuAsyncCore registers, real or simulated), DMA target selection and GPUTimer.
 */
#ifndef GPU_UTILS_HH
#define GPU_UTILS_HH

#include "psdaq/aes-stream-drivers/GpuAsync.h"
#include "psdaq/aes-stream-drivers/GpuAsyncUser.h"

#include <string>
#include <memory>
#include <assert.h>
#include <stdint.h>

#if defined(__CUDACC_VER_MAJOR__) || defined(__clangd__)
#define _CUDA
#endif

#include <cuda.h>
#include <cuda_runtime.h>

#ifdef __NVCC__
#define globalFunc __global__
#define hostFunc __host__
#define deviceFunc __device__
#else
/** Empty when not compiling with nvcc; __device__ under nvcc. */
#define deviceFunc
/** Empty when not compiling with nvcc; __global__ under nvcc. */
#define globalFunc
/** Empty when not compiling with nvcc; __host__ under nvcc. */
#define hostFunc
#endif

namespace Drp {
  namespace Gpu {

//--------------------------------------------------------------------------------//
// CUDA Prototypes
/** Empty string literal put in front of the optional message, so that the message argument is never empty (per the code comment). */
#define NOARG ""           // Ensures there is an arg when __VA_ARGS__ is blank
/** Check a CUDA driver or runtime result rc with checkError(), logging any failure with the optional message and aborting. */
#define chkFatal(rc, ...)  checkError((rc), #rc, __FILE__, __LINE__, true,  NOARG __VA_ARGS__)
/** Check a CUDA driver or runtime result rc with checkError(), logging any failure with the optional message without aborting; evaluates to true on failure. */
#define chkError(rc, ...)  checkError((rc), #rc, __FILE__, __LINE__, false, NOARG __VA_ARGS__)

/** If status is not CUDA_SUCCESS, log file, line, the error name and description and msg, then abort if crash is true. Returns true on failure, else false; func is not used. */
bool checkError(CUresult  status, const char* func, const char* file, int line, bool crash=true, const char* msg="");
/** If status is not cudaSuccess, log file, line, the error name and description and msg, then abort if crash is true. Returns true on failure, else false; func is not used. */
bool checkError(cudaError status, const char* func, const char* file, int line, bool crash=true, const char* msg="");
//--------------------------------------------------------------------------------//

/**
 * Wraps a cuda context and handles some initialization for you.
 */
class CudaContext
{
public:
    /** Initialize the CUDA driver API (cuInit()), aborting on failure. */
    CudaContext() { chkFatal(cuInit(0)); }

    /**
     * Creates a CUDA context, selects a device and ensures that stream memory ops are available.
     * \param device If >= 0, selects a device to use
     * \param quiet Wheter to spew or not
     * \returns Bool if success
     */
    bool init(int device = -1, bool quiet = false);

    /**
     * \brief Dumps a list of devices to stdout
     */
    void listDevices();

    /** Return the value of device attribute attr for the selected device, or 0 if the query fails. */
    int getAttribute(CUdevice_attribute attr);

    /** Return the device handle selected by init(). */
    CUdevice device() const { return device_; }
    /** Return the context created by init(). */
    CUcontext context() const { return context_; }
    /** Return the device number selected by init(). */
    int deviceNo() const { return _devNo; }

    CUcontext context_;  ///< Context created by init().
    CUdevice device_;  ///< Device handle selected by init().
private:
    int _devNo;
};

//-----------------------------------------------------------------------------//

/** Access to the GpuAsyncCore registers, either through a GpuAsyncCoreRegs object on the mapped firmware registers or, in simulator mode, through a plain memory block laid out like them. */
class CoreRegisters
{
public:
  /** Start with neither register object nor simulated block; initialize() must be called before use. */
  CoreRegisters() : _swRegs(nullptr), _fwRegs(nullptr) {}
  /** If sim is false, wrap the mapped registers at regs in a new GpuAsyncCoreRegs; otherwise use regs as the simulated register block. */
  void initialize(bool sim, void* regs);

  /** Return the DMA data bytes field (GpuAsyncReg_DmaDataBytes when simulated). MemPoolGpu uses it as the DMA header size (per its code comment, DMA_AXI_CONFIG_G.DATA_BYTES_C). */
  uint32_t dmaDataBytes() const
  { return _fwRegs ? _fwRegs->dmaDataBytes()
                   : _readSwReg(_swRegs, GpuAsyncReg_DmaDataBytes); }
  /** Set the DMA data bytes field in simulator mode; does nothing with real registers. */
  void     setDataBytes(uint32_t val)
  { if    (_swRegs)  _writeSwReg(_swRegs, GpuAsyncReg_DmaDataBytes, val); }
  /** Return the write enable field (GpuAsyncReg_WriteEnableV1 when simulated). */
  uint32_t writeEnable() const
  { return _fwRegs ? _fwRegs->writeEnable()
                   : _readSwReg(_swRegs, GpuAsyncReg_WriteEnableV1); }
  /** Set the write enable field. MemPoolGpu writes 0 to stop the FPGA side, and dmaIdxReset() writes 0 then 1 to reset the DMA buffer index (per the code comments). */
  void     setWriteEnable(uint32_t val)
  { if    (_fwRegs)  _fwRegs->setWriteEnable(val);
    else             _writeSwReg(_swRegs, GpuAsyncReg_WriteEnableV1, val); }
  /** Set the write count field (GpuAsyncReg_WriteCountV1 when simulated); MemPoolGpu writes the number of DMA buffers less 1. */
  void     setWriteCount(uint32_t val)
  { if    (_fwRegs)  _fwRegs->setWriteCount(val);
    else             _writeSwReg(_swRegs, GpuAsyncReg_WriteCountV1, val); }
  /** Return the AXI stream demux select field, which dmaTgtGet() reads. */
  uint32_t axisDeMuxSelect() const
  { return _fwRegs ? _fwRegs->axisDeMuxSelect()
                   : _readSwReg(_swRegs, GpuAsyncReg_AxisDeMuxSelect); }
  /** Set the AXI stream demux select field, which dmaTgtSet() writes. */
  void     setAxisDeMuxSelect(uint32_t val)
  { if    (_fwRegs)  _fwRegs->setAxisDeMuxSelect(val);
    else             _writeSwReg(_swRegs, GpuAsyncReg_AxisDeMuxSelect, val); }
  /** Call GpuAsyncCoreRegs::returnFreeListIndex(buffer); in simulator mode, write 1 to the register at freeListOffset(buffer). */
  void     returnFreeListIndex(uint32_t buffer)
  { if    (_fwRegs)  _fwRegs->returnFreeListIndex(buffer);
    else             _writeSwReg(_swRegs, freeListOffset(buffer), 1); }
  /** Return the register offset of the free-list entry of buffer (GPU_ASYNC_REG_WRITE_DETECT_OFFSET_V1 when simulated). */
  uint32_t freeListOffset(uint32_t buffer) const
  { return _fwRegs ? _fwRegs->freeListOffset(buffer)
                   : GPU_ASYNC_REG_WRITE_DETECT_OFFSET_V1(buffer); }
  /** Set the remote write maximum size of buffer (GPU_ASYNC_REG_WRITE_SIZE_OFFSET_V1 when simulated); MemPoolGpu sets it to the DMA buffer size. */
  void     setRemoteWriteMaxSize(uint32_t buffer, uint32_t size)
  { if    (_fwRegs)  _fwRegs->setRemoteWriteMaxSize(buffer, size);
    else             _writeSwReg(_swRegs, GPU_ASYNC_REG_WRITE_SIZE_OFFSET_V1(buffer), size); }
private:
  static uint32_t _readSwReg(const void* baseptr, const struct GpuAsyncRegister& reg) {
    uint32_t val = reg.bitMask & *(const uint32_t*)(((const uint8_t*)baseptr) + reg.offset);
    return val >> reg.bitOffset;
  }
  static uint32_t _readSwReg(const void* baseptr, uint32_t offset) {
    return *(uint32_t*)((uint8_t*)baseptr + offset);
  }
  static void     _writeSwReg(void* baseptr, const struct GpuAsyncRegister& reg, uint32_t value) {
    uint32_t* regp = (uint32_t*)(((uint8_t*)baseptr) + reg.offset);
    *regp = (*regp & ~reg.bitMask) | ((value << reg.bitOffset) & reg.bitMask);
  }
  static void     _writeSwReg(void* baseptr, uint32_t offset, uint32_t value) {
    *(uint32_t*)((uint8_t*)baseptr + offset) = value;
  }
private:
  uint32_t*                         _swRegs;
  std::unique_ptr<GpuAsyncCoreRegs> _fwRegs;
};

//-----------------------------------------------------------------------------//

/**
 * Functions to get and set the DMA destination.
 * \param fd The file descriptor of the PGP PCIe device
 * \param mode The enumerated value of the destination
 */
enum DmaTgt_t { TGT_CPU=0x0, /**< Value 0: destination CPU. */ TGT_GPU=0x1, /**< Value 1: destination GPU. */ TGT_ERR=-1u  /**< Returned by dmaTgtGet() for any other register value. */ };
/** Return TGT_CPU or TGT_GPU for the AXI stream demux select value of coreRegs, or TGT_ERR for any other value. */
DmaTgt_t dmaTgtGet(CoreRegisters&);
/** Write tgt to the AXI stream demux select field of coreRegs. MemPoolGpu sets TGT_GPU so that timing messages are sent to the GPU (per its code comment). */
void dmaTgtSet(CoreRegisters&, DmaTgt_t);

/**
 * Function to reset the DMA buffer round-robin index.
 * \param fd The file descriptor of the PGP PCIe device
 */
void dmaIdxReset(CoreRegisters&);

/**
 * Class for timing various things
 */
struct GPUTimer
{
  cudaEvent_t beg, /**< Start event, recorded by start(). */ end;  ///< Stop event, recorded by stop().
  /** Create the start and stop events (return codes not checked). */
  GPUTimer() {
    cudaEventCreate(&beg);
    cudaEventCreate(&end);
  }
  /** Destroy the two events. */
  ~GPUTimer() {
    cudaEventDestroy(beg);
    cudaEventDestroy(end);
  }
  /** Record the start event on the default stream. */
  void start() { cudaEventRecord(beg, 0); }
  /** Record the stop event on the default stream, wait for it and return the time since the start event in milliseconds. */
  float stop() {
    cudaEventRecord(end, 0);
    cudaEventSynchronize(end);
    float ms;
    cudaEventElapsedTime(&ms, beg, end);
    return ms;
  }
};

  } // Gpu
} // Drp

#endif
