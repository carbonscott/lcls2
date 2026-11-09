#pragma once

// The GPU DRP gives its Reader, TrgInpGen, Reducer and recorder their own SMs through
// the CUDA runtime's green contexts (cudaGreenCtxCreate and friends), which arrived in
// CUDA 13.  A toolkit older than that cannot compile them, and the newest toolkit a
// node can use is set by its driver: a 575 driver runs CUDA 12.9 at most, and refuses
// CUDA 13's forward-compatibility library ("system has unsupported display driver /
// cuda driver combination").
//
// CUDA 12 has the same green contexts in its driver API (cuGreenCtxCreate, 12.4;
// cuGreenCtxStreamCreate, 12.5), so with CUDA 12 this file maps the runtime calls the
// GPU DRP makes onto them, and PGPDrp::_setupGreenContexts() splits the SMs with
// cuDevSmResourceSplitByCount() (DRPGPU_DRIVER_GREEN_CONTEXTS).  The partition matters
// beyond speed: the Reader's _event kernel stops its late blocks once its first block is
// done (ReaderKernels.cuh), so its grid, sized from its context's SMs, must be resident
// at once, which only a context of its own guarantees.
//
// With CUDA 13 this file defines nothing, so production builds are unchanged.

#include <cuda.h>
#include <cuda_runtime.h>

#if CUDART_VERSION < 13000

#define DRPGPU_DRIVER_GREEN_CONTEXTS 1

typedef CUgreenCtx cudaExecutionContext_t;

enum cudaDevResourceType { cudaDevResourceTypeSm = CU_DEV_RESOURCE_TYPE_SM };

struct cudaDevSmResource
{
  unsigned smCount;
  unsigned minSmPartitionSize;
  unsigned smCoscheduledAlignment;
};

struct cudaDevResource
{
  cudaDevResourceType type;
  cudaDevSmResource   sm;
};

// cuGreenCtxStreamCreate() takes only non-blocking streams, which is what every caller asks for
inline CUresult cudaExecutionCtxStreamCreate(cudaStream_t*          stream,
                                             cudaExecutionContext_t ctx,
                                             unsigned               flags,
                                             int                    priority)
{
  return cuGreenCtxStreamCreate(stream, ctx, flags | CU_STREAM_NON_BLOCKING, priority);
}

inline CUresult cudaExecutionCtxGetDevResource(cudaExecutionContext_t ctx,
                                               cudaDevResource*       resource,
                                               cudaDevResourceType    type)
{
  CUdevResource res{};
  CUresult rc = cuGreenCtxGetDevResource(ctx, &res, CUdevResourceType(type));
  if (rc != CUDA_SUCCESS)  return rc;
  resource->type = type;
  resource->sm   = {res.sm.smCount, 0u, 0u};  // CUDA 12 reports the count only
  return CUDA_SUCCESS;
}

#endif
