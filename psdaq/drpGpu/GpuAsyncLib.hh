/**
 * @file
 * @brief CUDA and GPU Async helpers (error checks, DataDev, CudaContext, FPGA and GPU memory mapping, DMA target selection, GPUTimer) from axi-pcie-devel. In psdaq they are built only into the pgpread_gpu tool.
 */
/**
 * ----------------------------------------------------------------------------
 * Company    : SLAC National Accelerator Laboratory
 * ----------------------------------------------------------------------------
 * Description: Library and utilities for CUDA and the GPU Async protocol.
 * ----------------------------------------------------------------------------
 * This file is part of 'axi-pcie-devel'. It is subject to
 * the license terms in the LICENSE.txt file found in the top-level directory
 * of this distribution and at:
 *    https://confluence.slac.stanford.edu/display/ppareg/LICENSE.html.
 * No part of 'axi-pcie-devel', including this file, may be copied, modified,
 * propagated, or distributed except according to the terms contained in
 * the LICENSE.txt file.
 * ----------------------------------------------------------------------------
 **/
#pragma once

#include "Utils.h"

#include <string>
#include "psdaq/aes-stream-drivers/GpuAsync.h"
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
#define deviceFunc
/** Empty when not compiling with nvcc; __global__ under nvcc. */
#define globalFunc
/** Empty when not compiling with nvcc; __host__ under nvcc. */
#define hostFunc
#endif

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

/**
 * Dumps a buffer from the GPU to a stream
 * \param devicePtr Pointer to the block of memory to dump on the GPU
 * \param sizeInBytes
 * \param buf The copy buffer (assumed to be sizeInBytes in size). If NULL, one will be allocated
 * \param stream The stream to dump to
 */
template<typename T, int COLS = 16>
static inline void dumpGpuMem(CUdeviceptr devicePtr, size_t sizeInBytes, void* buf = nullptr, FILE* stream = stdout)
{
    bool buffed = !buf;
    if (buffed) buf = malloc(sizeInBytes);
    cuMemcpyDtoH(buf, devicePtr, sizeInBytes);
    dumpMem<T, COLS>(reinterpret_cast<T*>(buf), sizeInBytes);
    if (buffed) free(buf);
}

/**
 * Simple utility to display a device buffer
 */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
static void show_buf(CUdeviceptr dptr, size_t size, CUstream stream = 0) {
    uint8_t buf[size];
    //cuMemcpyDtoH(buf, dptr, size);
    chkError(cudaMemcpyAsync(buf, (void*)dptr, size, cudaMemcpyDeviceToHost, stream));
    cuStreamSynchronize(stream);
    for (size_t i = 0; i < size / 4; ++i) {
        printf("offset=0x%zX,  0x%X\n",i*4,*((uint32_t*)(buf+(i*4))));
    }
}
#pragma GCC diagnostic pop

/**
 * \brief Describes FPGA memory that's mapped via RDMA to the GPU. The below functions wrap
 * the creation and destruction process of the memory.
 */
struct GpuDmaBuffer_t
{
    int fd;  ///< File descriptor of the FPGA device.
    /** Host-accessible address of the memory; set by gpuMapHostFpgaMem() and left null by gpuMapFpgaMem(). */
    uint8_t* ptr;       /** Host accessible pointer **/
    size_t size;        /** Size of the block **/
    CUdeviceptr dptr;   /** Pointer on the device **/
    int gpuOnly;        /** 1 if this is FPGA <-> GPU only, not mapped to host at all **/
};

/**
 * \brief Maps FPGA memory to the host and allows GPU access to it
 * This is the "standard" way of doing DMA with CUDA. cuMemHostRegister essentially just gives CUDA
 * access to some pages and allows the GPU to read/write to them.
 * Unlike RDMA, this doesn't require any custom code on the kernel side, this will work with any (properly aligned)
 * buffer given, whether it's IO memory or not. Again unlike RDMA, cuMemHostRegister has more latency
 * and lower throughput, since a DMA transfer must occur between the GPU <-> HOST <-> FPGA
 * \param outmem
 * \param fd File descriptor of the FPGA device
 * \param offset Offset of the register block
 * \param size Size of the register block
 * \returns 0 for success
 */
int gpuMapHostFpgaMem(GpuDmaBuffer_t* outmem, int fd, uint64_t offset, size_t size);

/**
 * \brief Maps GPU memory to the FPGA using RDMA
 * This function uses gpuAddNvidiaMemory to give the FPGA access to some pages of memory located
 * on the GPU. This is the other method of doing DMA, and it requires custom driver code and a
 * very specific PCIe topology.
 * Regardless, RDMA allows for low-latency, high-bandwidth DMA transfers between two devices on
 * the bus, without needing to interact with the CPU.
 * \param outmem
 * \param fd File descriptor of the FPGA device
 * \param offset Offset of the register block
 * \param size Size of the register block
 * \param write If 1, this will be writable
 */
int gpuMapFpgaMem(GpuDmaBuffer_t* outmem, int fd, uint64_t offset, size_t size, int write);

/**
 * \brief Unmaps memory, clears out the pointer and size
 */
void gpuUnmapFpgaMem(GpuDmaBuffer_t* mem);

//-----------------------------------------------------------------------------//

/** A read buffer and a write buffer on the GPU, mapped to the FPGA by gpuInitBufferState(). */
struct GpuBufferState_t
{
    uint8_t* swFpgaRegs;  ///< Register pointer; not set or read anywhere in psdaq.

    GpuDmaBuffer_t bread;  ///< Buffer mapped with write set to 0.
    GpuDmaBuffer_t bwrite;  ///< Buffer mapped with write set to 1.
};

/**
 * Allocates and inits buffer pairs on the GPU for RDMA operation.
 * \param b Buffer state to init
 * \param fd The file descriptor of the DataDev device to allocate for
 * \param bufSize The size of the buffers to allocate
 * \return 0 for success, -1 on error
 */
int gpuInitBufferState(GpuBufferState_t* b, int fd, size_t bufSize);
/** Unmap and free both buffers of b with gpuUnmapFpgaMem(). */
void gpuDestroyBufferState(GpuBufferState_t* b);

//-----------------------------------------------------------------------------//

/**
 * 64-bit write AXI descriptor data
 */
struct __attribute__((packed)) AxiWrDesc64_t
{
    uint32_t result     : 2;
    uint32_t overflow   : 1;        /** Overflow bit */
    uint32_t cont       : 1;        /** Continue bit */
    uint32_t reserved0  : 12;
    uint32_t lastUser   : 8;
    uint32_t firstUser  : 8;
    uint32_t size;
};

static_assert(sizeof(AxiWrDesc64_t) == 8, "AxiWrDesc64_t must be 64-bits (8-bytes)");

/** Return the 8 bytes at data as an AxiWrDesc64_t. */
deviceFunc inline AxiWrDesc64_t UnpackAxiWriteDescriptor(const void* data)
{
    return *(AxiWrDesc64_t*)data;
}

//-----------------------------------------------------------------------------//

/**
 * Functions to get and set the DMA destination.
 * \param fd The file descriptor of the PGP PCIe device
 * \param mode The enumerated value of the destination
 */
//enum DmaTgt_t { TGT_CPU=0x0000ffff, TGT_GPU=0xffff0000, TGT_ERR=-1u };
enum DmaTgt_t { TGT_CPU=0x0, /**< Value 0: destination CPU. */ TGT_GPU=0x1, /**< Value 1: destination GPU. */ TGT_ERR=-1u  /**< Returned by dmaTgtGet() for any other register value. */ };
/** Read the AXI stream demux select register of the GPU Async core and return TGT_CPU or TGT_GPU for its value, or TGT_ERR for any other value. A read error is only reported with perror(). */
DmaTgt_t dmaTgtGet(const DataDev&);
/** Write tgt to the AXI stream demux select register of the GPU Async core; a write error is only reported with perror(). */
void dmaTgtSet(const DataDev&, DmaTgt_t);

/**
 * Function to reset the DMA buffer round-robin index.
 * \param fd The file descriptor of the PGP PCIe device
 */
void dmaIdxReset(const DataDev&);

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
